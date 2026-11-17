import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.api.rate_limits import check_login_rate_limit, check_otp_send_rate_limit, check_register_rate_limit
from app.api.schemas import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    EmailOtpLogin,
    EmailOtpRequest,
    PasswordResetRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    VerifyEmailRequest,
)
from app.database import get_db
from app.models.schemas import Tenant, User
from app.services.auth import (
    allocate_username,
    assert_account_login_allowed,
    create_access_token,
    find_user_by_email,
    hash_password,
    mark_email_verified,
    verify_password,
)
from app.services.email_otp import (
    OTP_PURPOSES,
    assert_send_cooldown,
    consume_otp,
    drop_otp,
    email_delivery_ready,
    generate_otp,
    is_placeholder_email,
    mark_send_cooldown,
    normalize_email,
    otp_email_copy,
    store_otp,
)
from app.services.legal import apply_registration_consents, require_registration_consents

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_account(db: Session, payload: UserRegister, request: Request, email: str) -> User:
    username = allocate_username(db, email, payload.username)
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name or username,
        email_verified_at=datetime.utcnow(),
    )
    if payload.invite_code:
        tenant = db.query(Tenant).filter(Tenant.invite_code == payload.invite_code.strip()).first()
        if tenant:
            user.tenant_id = tenant.id
    db.add(user)
    db.flush()
    apply_registration_consents(
        db,
        user,
        payload.accepted_terms_version,
        payload.accepted_privacy_version,
        request=request,
    )
    from app.services.credits import grant_welcome_credits
    from app.services.growth import apply_referral_on_signup, ensure_referral_code

    grant_welcome_credits(db, user.id)
    apply_referral_on_signup(db, user, payload.referral_code)
    ensure_referral_code(db, user)
    return user


def _user_response(user: User) -> UserResponse:
    from app.services.legal import consent_status

    status = consent_status(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        tenant_id=user.tenant_id,
        is_tenant_admin=bool(user.is_tenant_admin),
        is_admin=bool(user.is_admin),
        deletion_scheduled_at=status.get("deletion_scheduled_at"),
        consent_missing=status.get("missing", []),
        email_verified=bool(getattr(user, "email_verified_at", None)),
        email_bound=not is_placeholder_email(user.email),
    )


@router.post("/email-otp")
async def send_email_otp(
    payload: EmailOtpRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    purpose = (payload.purpose or "").strip().lower()
    if purpose not in OTP_PURPOSES:
        raise HTTPException(status_code=400, detail="otp_invalid")
    email = normalize_email(payload.email)
    check_otp_send_rate_limit(request, email)
    assert_send_cooldown(email)
    existing = find_user_by_email(db, email)
    if purpose in {"rebind", "bind"}:
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        current = normalize_email(user.email)
        if purpose == "rebind":
            if is_placeholder_email(current):
                raise HTTPException(status_code=400, detail="email_unbound")
            if email != current:
                raise HTTPException(status_code=400, detail="email_mismatch")
        else:
            if email == current:
                raise HTTPException(status_code=400, detail="same_email")
            if is_placeholder_email(email):
                raise HTTPException(status_code=400, detail="otp_invalid")
            if existing and existing.id != user.id:
                raise HTTPException(status_code=409, detail="email_taken")
    elif purpose == "register" and existing:
        raise HTTPException(status_code=409, detail="email_taken")
    elif purpose in {"login", "reset"} and not existing:
        raise HTTPException(status_code=404, detail="unknown_email")
    if not email_delivery_ready():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="otp_unavailable")

    code = generate_otp()
    store_otp(purpose, email, code)
    from app.services.email_notify import send_email

    subject, html, text = otp_email_copy(code, purpose)
    sent = await send_email(email, subject, html, body_text=text)
    if not sent:
        drop_otp(purpose, email)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="otp_unavailable")
    mark_send_cooldown(email)
    return {"ok": True, "cooldown_seconds": 60}


@router.post("/register", response_model=TokenResponse)
def register(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    check_register_rate_limit(request)
    require_registration_consents(payload.accepted_terms_version, payload.accepted_privacy_version)
    email = normalize_email(payload.email)
    if find_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="email_taken")
    if not (payload.otp or "").strip():
        raise HTTPException(status_code=400, detail="otp_required")
    consume_otp("register", email, payload.otp)
    user = _create_account(db, payload, request, email)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    check_login_rate_limit(request, payload.email)
    user = find_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=401, detail="unknown_email")
    assert_account_login_allowed(user)
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="wrong_password")
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/login-otp", response_model=TokenResponse)
def login_otp(payload: EmailOtpLogin, request: Request, db: Session = Depends(get_db)):
    check_login_rate_limit(request, payload.email)
    email = normalize_email(payload.email)
    user = find_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=401, detail="unknown_email")
    assert_account_login_allowed(user)
    consume_otp("login", email, payload.otp)
    mark_email_verified(user)
    db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/reset-password", response_model=TokenResponse)
def reset_password(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    check_login_rate_limit(request, payload.email)
    email = normalize_email(payload.email)
    user = find_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="unknown_email")
    assert_account_login_allowed(user)
    consume_otp("reset", email, payload.otp)
    user.hashed_password = hash_password(payload.password)
    mark_email_verified(user)
    db.commit()
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/verify-email", response_model=UserResponse)
def verify_email(payload: VerifyEmailRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = normalize_email(user.email)
    if is_placeholder_email(email):
        raise HTTPException(status_code=400, detail="email_unbound")
    consume_otp("rebind", email, payload.otp)
    mark_email_verified(user)
    db.commit()
    db.refresh(user)
    invalidate_me_cache(user.id)
    return _user_response(user)


@router.post("/change-email", response_model=UserResponse)
def change_email(payload: ChangeEmailRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current = normalize_email(user.email)
    new_email = normalize_email(payload.new_email)
    if new_email == current:
        raise HTTPException(status_code=400, detail="same_email")
    if is_placeholder_email(new_email):
        raise HTTPException(status_code=400, detail="otp_invalid")
    if find_user_by_email(db, new_email):
        raise HTTPException(status_code=409, detail="email_taken")
    consume_otp("bind", new_email, payload.new_otp)
    if not is_placeholder_email(current):
        if not (payload.current_otp or "").strip():
            raise HTTPException(status_code=400, detail="otp_required")
        consume_otp("rebind", current, payload.current_otp)
    user.email = new_email
    user.email_verified_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    invalidate_me_cache(user.id)
    return _user_response(user)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    email = normalize_email(user.email)
    if is_placeholder_email(email):
        raise HTTPException(status_code=400, detail="email_unbound")
    if (payload.otp or "").strip():
        consume_otp("reset", email, payload.otp)
    elif payload.current_password:
        if not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=401, detail="wrong_password")
    else:
        raise HTTPException(status_code=400, detail="otp_required")
    user.hashed_password = hash_password(payload.password)
    db.commit()
    invalidate_me_cache(user.id)
    return {"ok": True}


_ME_TTL_S = 8.0
_me_cache: dict[str, tuple[float, UserResponse]] = {}


def invalidate_me_cache(user_id: object | None = None) -> None:
    if user_id is None:
        _me_cache.clear()
        return
    _me_cache.pop(str(user_id), None)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    key = str(user.id)
    now = time.monotonic()
    hit = _me_cache.get(key)
    if hit and now - hit[0] < _ME_TTL_S:
        return hit[1]
    payload = _user_response(user)
    _me_cache[key] = (now, payload)
    return payload
