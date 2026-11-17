"""Stripe / mock billing for credit packs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.schemas import CreditTransaction, PaymentOrder, User
from app.services.credits import add_credits, grant_credits_with_transaction

logger = logging.getLogger(__name__)

STRIPE_CURRENCY = "USD"

CREDIT_PACKS: dict[str, dict[str, Any]] = {
    "pack_10": {"credits": 10, "amount_cents": 999, "amount_fen": 700, "label": "10 次"},
    "pack_50": {"credits": 50, "amount_cents": 3999, "amount_fen": 2800, "label": "50 次"},
    "pack_100": {"credits": 100, "amount_cents": 6999, "amount_fen": 4800, "label": "100 次"},
    "duel_season_pass": {
        "credits": 0,
        "duel_starts": 10,
        "amount_cents": 199,
        "amount_fen": 1200,
        "label": "决斗季卡",
        "description": "10 次免费发起情绪决斗",
        "type": "duel_pass",
    },
}

SUBSCRIPTION_PLANS: dict[str, dict[str, Any]] = {
    "sub_monthly": {
        "type": "subscription",
        "label": "会员月卡",
        "amount_cents": 499,
        "amount_fen": 2900,
        "monthly_credits": 30,
        "duration_days": 30,
        "description": "每月 30 次 · 优先排队 · 专属风格",
    },
    "sub_yearly": {
        "type": "subscription",
        "label": "会员年卡",
        "amount_cents": 4999,
        "amount_fen": 26800,
        "monthly_credits": 30,
        "duration_days": 365,
        "description": "全年会员 · 开通即赠 360 次 · 约 8 折",
        "upfront_credits": 360,
    },
    "sub_pro_commercial": {
        "type": "subscription",
        "label": "Pro 商用",
        "amount_cents": 1499,
        "amount_fen": 9900,
        "monthly_credits": 50,
        "duration_days": 30,
        "description": "无限 HQ 导出 · 商用证书 · API 500 次/月",
    },
    "sub_team": {
        "type": "subscription",
        "label": "团队版",
        "amount_cents": 2999,
        "amount_fen": 19900,
        "monthly_credits": 100,
        "duration_days": 30,
        "description": "5 人共用次数 · 一起管理",
        "seats": 5,
    },
    "sub_api_starter": {
        "type": "subscription",
        "label": "API Starter",
        "amount_cents": 2999,
        "amount_fen": 19900,
        "monthly_credits": 0,
        "duration_days": 30,
        "description": "1000 次/月 API · Webhook · 开发者集成",
        "api_quota": 1000,
    },
}


def get_product(product_id: str) -> dict[str, Any] | None:
    if product_id in CREDIT_PACKS:
        return {"id": product_id, "type": "credits", **CREDIT_PACKS[product_id]}
    if product_id in SUBSCRIPTION_PLANS:
        return {"id": product_id, **SUBSCRIPTION_PLANS[product_id]}
    return None


def product_amount_fen(product: dict[str, Any]) -> int:
    return int(product.get("amount_fen") or product["amount_cents"])


def product_label(product_id: str) -> str:
    product = get_product(product_id)
    return product["label"] if product else product_id


def is_subscription_product(product_id: str) -> bool:
    return product_id in SUBSCRIPTION_PLANS


# 微信「虚拟支付-道具直购」道具ID 映射。
#
# 你在小程序后台「虚拟支付 -> 道具管理」为每个商品创建道具后，把返回的 productId
# 填到这里（键=我们自己的商品ID，值=微信道具ID）。留空表示该商品在小程序里还没开卖，
# 下单会被直接拒掉，定价页也会写「未配置」——配好后即通。
#
# 重要：道具在后台配置的价格(单位:分)必须与本商品的 amount_fen 完全一致，
# 否则微信会因金额不符拒绝下单。
WECHAT_VPAY_GOODS: dict[str, str] = {
    "pack_10": "",
    "pack_50": "",
    "pack_100": "",
    "duel_season_pass": "",
    "sub_monthly": "",
    "sub_yearly": "",
    "sub_pro_commercial": "",
    "sub_team": "",
    "sub_api_starter": "",
}


def wechat_vpay_product_id(product_id: str) -> str:
    """返回该商品对应的微信道具ID；没配就返回空串。

    优先级：.env 的 WECHAT_VPAY_GOODS_JSON > 代码内 WECHAT_VPAY_GOODS。
    绝不回退成商品ID本身：那个 ID 在小程序后台并不存在，拿它下单只会得到一张
    看起来在走流程、实际永远付不掉的单子。
    """
    env_map = settings.wechat_vpay_goods_map
    return (env_map.get(product_id) or WECHAT_VPAY_GOODS.get(product_id) or "").strip()


def wechat_vpay_ready(product_id: str) -> bool:
    return bool(settings.wechat_vpay_enabled and wechat_vpay_product_id(product_id))


def wechat_vpay_configured_products() -> list[str]:
    return [pid for pid in all_purchasable_products() if wechat_vpay_product_id(pid)]


def all_purchasable_products() -> dict[str, dict[str, Any]]:
    """所有可购买商品（额度包 + 会员套餐），用于配置校验/对账。"""
    merged: dict[str, dict[str, Any]] = {}
    for pid in list(CREDIT_PACKS.keys()) + list(SUBSCRIPTION_PLANS.keys()):
        p = get_product(pid)
        if p:
            merged[pid] = p
    return merged


# A test price that reaches production is a silent giveaway: the order looks paid and
# the credits land, but the money never does. These bounds only need to be tight enough
# to catch placeholder values like `amount_fen = 1`.
MIN_AMOUNT_FEN = 100  # ¥1.00
MIN_AMOUNT_CENTS = 50  # Stripe rejects charges under $0.50


def audit_product_prices() -> list[str]:
    """Return human-readable problems with the hardcoded price table (empty = healthy)."""
    problems: list[str] = []
    for pid, product in all_purchasable_products().items():
        amount_fen = int(product.get("amount_fen") or 0)
        amount_cents = int(product.get("amount_cents") or 0)
        if amount_fen < MIN_AMOUNT_FEN:
            problems.append(f"{pid}: amount_fen={amount_fen} is below the ¥{MIN_AMOUNT_FEN / 100:.2f} floor")
        if amount_cents < MIN_AMOUNT_CENTS:
            problems.append(
                f"{pid}: amount_cents={amount_cents} is below the ${MIN_AMOUNT_CENTS / 100:.2f} Stripe floor"
            )

    # Bigger credit packs must never be cheaper per credit than smaller ones. A single
    # mistyped digit breaks this long before it breaks the eyeball test.
    packs = sorted(
        ((pid, p) for pid, p in CREDIT_PACKS.items() if int(p.get("credits") or 0) > 0),
        key=lambda item: int(item[1]["credits"]),
    )
    for field, unit in (("amount_fen", "fen"), ("amount_cents", "cents")):
        previous: tuple[str, float] | None = None
        for pid, pack in packs:
            per_credit = int(pack.get(field) or 0) / int(pack["credits"])
            if previous and per_credit > previous[1]:
                problems.append(
                    f"{pid}: {per_credit:.2f} {unit}/credit is more expensive than the smaller "
                    f"pack {previous[0]} at {previous[1]:.2f} {unit}/credit"
                )
            previous = (pid, per_credit)
    return problems


def vpay_goods_report() -> list[dict[str, Any]]:
    """列出每个商品的道具映射状态与应配置的价格（分），供后台配置对照。"""
    report: list[dict[str, Any]] = []
    for pid, product in all_purchasable_products().items():
        mapped = wechat_vpay_product_id(pid)
        report.append(
            {
                "product_id": pid,
                "label": product.get("label", pid),
                "amount_fen": product_amount_fen(product),
                "wechat_product_id": mapped or None,
                "configured": bool(mapped),
            }
        )
    return report


def list_plans() -> list[dict[str, Any]]:
    return [
        {
            "id": pid,
            **plan,
            "price_cny_yuan": round(product_amount_fen(plan) / 100, 2),
            "wechat_enabled": settings.wechat_pay_enabled,
            "alipay_enabled": settings.alipay_enabled,
            "stripe_enabled": bool(settings.stripe_secret_key),
            "wechat_vpay_enabled": wechat_vpay_ready(pid),
        }
        for pid, plan in SUBSCRIPTION_PLANS.items()
    ]


def list_packs() -> list[dict[str, Any]]:
    return [
        {
            "id": pid,
            **pack,
            "currency_usd": "usd",
            "currency_cny": "cny",
            "price_cny_yuan": round((pack.get("amount_fen") or pack["amount_cents"]) / 100, 2),
            "stripe_enabled": bool(settings.stripe_secret_key),
            "wechat_enabled": settings.wechat_pay_enabled,
            "alipay_enabled": settings.alipay_enabled,
            "wechat_vpay_enabled": wechat_vpay_ready(pid),
        }
        for pid, pack in CREDIT_PACKS.items()
    ]


def list_payment_methods() -> dict[str, Any]:
    channels: list[dict[str, Any]] = []
    if settings.wechat_pay_enabled or settings.wechat_vpay_enabled:
        channels.append(
            {
                "id": "wechat",
                "label": "微信支付",
                "enabled": True,
                "scenes": [
                    {"id": "native", "label": "扫码支付", "for": "web"},
                    {"id": "jsapi", "label": "小程序支付", "for": "miniprogram"},
                    {"id": "h5", "label": "H5 支付", "for": "mobile_web"},
                ],
            }
        )
    if settings.alipay_enabled:
        channels.append(
            {
                "id": "alipay",
                "label": "支付宝",
                "enabled": True,
                "scenes": [
                    {"id": "web", "label": "电脑网站支付", "for": "web"},
                    {"id": "h5", "label": "手机网站支付", "for": "mobile_web"},
                ],
            }
        )
    if settings.stripe_secret_key:
        channels.append(
            {
                "id": "stripe",
                "label": "Stripe（国际卡）",
                "enabled": True,
                "scenes": [{"id": "checkout", "label": "信用卡", "for": "web"}],
            }
        )
    return {
        "mock_mode": bool(settings.payment_mock_allowed),
        "channels": channels,
    }


def _success_url() -> str:
    return settings.frontend_page("/pages/settings/index", checkout="success")


def _cancel_url() -> str:
    return settings.frontend_page("/pages/settings/index", checkout="cancel")


def create_mock_checkout(db: Session, user: User, pack_id: str) -> dict[str, Any]:
    """Dev fallback when Stripe is not configured — grants credits immediately."""
    if not settings.payment_mock_allowed:
        raise HTTPException(status_code=503, detail="支付未配置，请联系管理员")
    if not get_product(pack_id):
        raise HTTPException(status_code=400, detail="Unknown product_id")
    mock_id = f"mock_{uuid.uuid4().hex}"
    result = fulfill_payment(db, user.id, pack_id, source="mock", external_id=mock_id)
    return {
        "mode": "mock",
        "pack_id": pack_id,
        **result,
        "url": _success_url() + ("&sub=1" if is_subscription_product(pack_id) else ""),
    }


def new_stripe_out_trade_no() -> str:
    return f"stp{uuid.uuid4().hex[:24]}"


async def create_stripe_checkout(
    db: Session,
    user: User,
    pack_id: str,
    *,
    payment_terms_version: str | None = None,
) -> dict[str, Any]:
    product = get_product(pack_id)
    if not product:
        raise HTTPException(status_code=400, detail="Unknown pack_id")
    if product.get("type") != "credits" and not is_subscription_product(pack_id):
        raise HTTPException(status_code=400, detail="Unknown pack_id")
    if not settings.stripe_secret_key:
        return create_mock_checkout(db, user, pack_id)

    from app.services.payment_orders import register_pending_order

    pack = product
    credits_meta = pack.get("credits") or pack.get("upfront_credits") or pack.get("monthly_credits") or 0
    amount_cents = int(pack["amount_cents"])
    out_trade_no = new_stripe_out_trade_no()

    payload = {
        "mode": "payment",
        "success_url": _success_url() + ("&sub=1" if is_subscription_product(pack_id) else ""),
        "cancel_url": _cancel_url(),
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[pack_id]": pack_id,
        "metadata[credits]": str(credits_meta),
        "metadata[out_trade_no]": out_trade_no,
        "payment_intent_data[metadata][out_trade_no]": out_trade_no,
        "line_items[0][price_data][currency]": STRIPE_CURRENCY.lower(),
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": pack["label"],
        "line_items[0][quantity]": "1",
    }

    if settings.stripe_tax_enabled:
        payload["automatic_tax[enabled]"] = "true"
        payload["tax_id_collection[enabled]"] = "true"

    register_pending_order(
        db,
        user_id=user.id,
        pack_id=pack_id,
        channel="stripe",
        out_trade_no=out_trade_no,
        amount_fen=amount_cents,
        currency=STRIPE_CURRENCY,
        payment_terms_version=payment_terms_version,
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            auth=(settings.stripe_secret_key, ""),
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Stripe checkout failed")
    data = resp.json()
    return {
        "mode": "stripe",
        "session_id": data.get("id"),
        "url": data.get("url"),
        "out_trade_no": out_trade_no,
    }


def fulfill_checkout(
    db: Session,
    user_id: uuid.UUID,
    pack_id: str,
    *,
    source: str = "stripe",
    stripe_session_id: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    dedupe_id = external_id or stripe_session_id
    if dedupe_id:
        existing = (
            db.query(CreditTransaction)
            .filter(
                or_(
                    CreditTransaction.external_id == dedupe_id,
                    CreditTransaction.stripe_session_id == dedupe_id,
                )
            )
            .first()
        )
        if existing:
            from app.services.credits import get_or_create_credits

            row = get_or_create_credits(db, user_id)
            return {
                "credits_granted": existing.credits,
                "balance": row.balance,
                "duplicate": True,
            }

    if stripe_session_id:
        existing = (
            db.query(CreditTransaction)
            .filter(CreditTransaction.stripe_session_id == stripe_session_id)
            .first()
        )
        if existing:
            from app.services.credits import get_or_create_credits

            row = get_or_create_credits(db, user_id)
            return {
                "credits_granted": existing.credits,
                "balance": row.balance,
                "duplicate": True,
            }

    pack = CREDIT_PACKS.get(pack_id)
    if not pack:
        raise HTTPException(status_code=400, detail="Unknown pack_id")

    row = grant_credits_with_transaction(
        db,
        user_id,
        pack["credits"],
        source=source,
        external_id=external_id or stripe_session_id,
        pack_id=pack_id,
    )
    if stripe_session_id:
        tx = (
            db.query(CreditTransaction)
            .filter(CreditTransaction.external_id == (external_id or stripe_session_id))
            .order_by(CreditTransaction.created_at.desc())
            .first()
        )
        if tx and not tx.stripe_session_id:
            tx.stripe_session_id = stripe_session_id
            db.commit()
    _track_purchase(db, user_id, pack_id, pack["credits"], source)
    return {"credits_granted": pack["credits"], "balance": row.balance}


def fulfill_payment(
    db: Session,
    user_id: uuid.UUID,
    product_id: str,
    *,
    source: str = "stripe",
    stripe_session_id: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Route credit packs vs subscription plans to the correct fulfillment handler."""
    if is_subscription_product(product_id):
        from app.services.subscriptions import activate_subscription_from_payment

        return activate_subscription_from_payment(
            db,
            user_id,
            product_id,
            source=source,
            external_id=external_id or stripe_session_id,
            channel=source.split("_")[0] if source else None,
        )
    pack = CREDIT_PACKS.get(product_id)
    if pack and pack.get("type") == "duel_pass":
        from app.services.duels import grant_duel_pass_starts

        starts = int(pack.get("duel_starts") or 10)
        grant_duel_pass_starts(db, user_id, starts=starts)
        _track_purchase(db, user_id, product_id, 0, source)
        return {"duel_starts_granted": starts, "product_id": product_id}
    return fulfill_checkout(
        db,
        user_id,
        product_id,
        source=source,
        stripe_session_id=stripe_session_id,
        external_id=external_id,
    )


def _track_purchase(db: Session, user_id: uuid.UUID, product_id: str, credits: int, source: str) -> None:
    try:
        from app.services.analytics import track_event

        track_event(
            db,
            "credit_purchase",
            user_id=user_id,
            payload={"product_id": product_id, "credits": credits, "source": source},
        )
    except Exception:
        pass


async def create_subscription_checkout(db: Session, user: User, *, plan_id: str = "sub_monthly") -> dict[str, Any]:
    """Stripe subscription for monthly credits, or mock grant in dev."""
    from app.services.subscriptions import activate_subscription_from_payment

    if plan_id not in SUBSCRIPTION_PLANS:
        raise HTTPException(status_code=400, detail="Unknown subscription plan")

    if not settings.stripe_secret_key or not settings.stripe_subscription_price_id:
        if not settings.payment_mock_allowed:
            raise HTTPException(status_code=503, detail="订阅支付未配置")
        return {
            "mode": "mock",
            **activate_subscription_from_payment(
                db,
                user.id,
                plan_id,
                source="mock",
                external_id=f"mock_sub_{uuid.uuid4().hex}",
                channel="mock",
            ),
        }

    plan = SUBSCRIPTION_PLANS[plan_id]
    stripe_price = settings.stripe_subscription_price_id
    if plan_id == "sub_yearly" and settings.stripe_subscription_yearly_price_id:
        stripe_price = settings.stripe_subscription_yearly_price_id
    elif plan_id == "sub_yearly":
        return await create_stripe_checkout(db, user, plan_id)

    payload = {
        "mode": "subscription",
        "success_url": _success_url() + "&sub=1",
        "cancel_url": _cancel_url(),
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[plan_id]": plan_id,
        "line_items[0][price]": stripe_price,
        "line_items[0][quantity]": "1",
    }
    if settings.stripe_tax_enabled:
        payload["automatic_tax[enabled]"] = "true"
        payload["tax_id_collection[enabled]"] = "true"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            auth=(settings.stripe_secret_key, ""),
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Stripe subscription checkout failed")
    data = resp.json()
    return {"mode": "stripe", "session_id": data.get("id"), "url": data.get("url")}


def verify_stripe_webhook_payload(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    """Verify Stripe-Signature when webhook secret is configured."""
    secret = settings.stripe_webhook_secret
    if not secret:
        if settings.stripe_secret_key:
            raise HTTPException(
                status_code=503,
                detail="Stripe webhook secret is not configured",
            )
        if not settings.payment_mock_allowed:
            raise HTTPException(
                status_code=503,
                detail="Stripe webhook verification is required outside dev mode",
            )
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    parts: dict[str, list[str]] = {}
    for item in sig_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts.setdefault(key, []).append(value)

    timestamp = parts.get("t", [""])[0]
    signatures = parts.get("v1", [])
    if not timestamp or not signatures:
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature header")

    tolerance = settings.stripe_webhook_tolerance_seconds
    if abs(time.time() - int(timestamp)) > tolerance:
        raise HTTPException(status_code=400, detail="Webhook timestamp outside tolerance")

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc


def parse_stripe_webhook_payload(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    return verify_stripe_webhook_payload(payload, sig_header)


def handle_stripe_webhook_event(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    """Route Stripe webhook events to pack checkout or subscription handlers."""
    from app.services.cache import cache_get, cache_set
    from app.services.subscriptions import (
        activate_subscription_from_checkout,
        grant_subscription_invoice,
        sync_stripe_subscription_status,
    )

    event_id = event.get("id")
    if event_id:
        dedupe_key = f"stripe:event:{event_id}"
        if cache_get(dedupe_key):
            return {"received": True, "duplicate": event_id}
        cache_set(dedupe_key, "1", 86400 * 7)

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        if obj.get("mode") == "subscription":
            return activate_subscription_from_checkout(db, obj)
        return _fulfill_stripe_checkout_session(db, obj)

    if event_type == "invoice.paid":
        return grant_subscription_invoice(db, obj)

    if event_type in ("customer.subscription.deleted", "customer.subscription.updated"):
        return sync_stripe_subscription_status(db, obj)

    if event_type in ("charge.refunded", "charge.dispute.created", "charge.dispute.closed"):
        return _revoke_stripe_charge(db, obj, event_type)

    return {"received": True, "skipped": event_type}


def _fulfill_stripe_checkout_session(db: Session, session: dict[str, Any]) -> dict[str, Any]:
    """Fulfill a one-time Stripe Checkout Session against its PaymentOrder.

    Never trusts `metadata.pack_id` on its own — the amount actually charged has to
    match the order we recorded when the session was created.
    """
    from app.services.payment_orders import complete_paid_order
    from app.services.payment_security import validate_stripe_session_fields

    metadata = session.get("metadata") or {}
    stripe_session_id = str(session.get("id") or "") or None
    payment_intent = session.get("payment_intent")
    payment_intent_id = str(payment_intent) if isinstance(payment_intent, str) else None
    out_trade_no = str(metadata.get("out_trade_no") or "")

    if out_trade_no:
        row = db.query(PaymentOrder).filter(PaymentOrder.out_trade_no == out_trade_no).first()
        if not row:
            return {"received": True, "skipped": "order_not_found"}
        err = validate_stripe_session_fields(session, row)
        if err == "already_paid":
            return {"received": True, "duplicate": out_trade_no}
        if err == "order_expired":
            row.status = "expired"
            db.commit()
            _alert_stripe_mismatch(out_trade_no, err, session)
            return {"received": True, "skipped": err}
        if err:
            _alert_stripe_mismatch(out_trade_no, err, session)
            return {"received": True, "skipped": err}
        return complete_paid_order(
            db,
            out_trade_no,
            provider_tx_id=stripe_session_id,
            provider_ref=payment_intent_id,
            source="stripe",
        )

    # Sessions created before orders were recorded still need to be honoured, but only
    # after the charged amount is checked against the catalogue price.
    user_id = metadata.get("user_id") or session.get("client_reference_id")
    pack_id = metadata.get("pack_id")
    if not user_id or not pack_id:
        return {"received": True, "skipped": "missing pack metadata"}
    product = get_product(str(pack_id))
    if not product:
        return {"received": True, "skipped": "unknown_pack"}
    try:
        amount_total = int(session.get("amount_total"))
    except (TypeError, ValueError):
        return {"received": True, "skipped": "invalid_amount_total"}
    currency = str(session.get("currency") or STRIPE_CURRENCY).upper()
    if currency != STRIPE_CURRENCY or amount_total != int(product["amount_cents"]):
        _alert_stripe_mismatch(str(stripe_session_id), "legacy_amount_mismatch", session)
        return {"received": True, "skipped": "amount_mismatch"}
    return fulfill_payment(
        db,
        uuid.UUID(str(user_id)),
        str(pack_id),
        source="stripe",
        stripe_session_id=stripe_session_id,
    )


def _revoke_stripe_charge(db: Session, charge: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Roll back credits when Stripe reports a refund or a dispute on a charge."""
    from app.services.payment_orders import find_order_by_provider_ref, revoke_paid_order

    if event_type == "charge.refunded" and not charge.get("refunded"):
        # Partial refunds keep the order alive; a human decides what to claw back.
        _alert_stripe_mismatch(str(charge.get("id") or ""), "partial_refund", charge)
        return {"received": True, "skipped": "partial_refund"}

    # `charge.dispute.*` delivers a Dispute object, `charge.refunded` a Charge object.
    payment_intent = charge.get("payment_intent")
    candidates = [
        str(payment_intent) if isinstance(payment_intent, str) else "",
        str((charge.get("metadata") or {}).get("out_trade_no") or ""),
        str(charge.get("charge") or "") if isinstance(charge.get("charge"), str) else "",
    ]
    row = None
    for candidate in candidates:
        if not candidate:
            continue
        row = find_order_by_provider_ref(db, candidate)
        if row:
            break
    if not row:
        _alert_stripe_mismatch(candidates[0] or "unknown", f"{event_type}_unmatched", charge)
        return {"received": True, "skipped": "order_not_found"}

    reason = "dispute" if "dispute" in event_type else "refund"
    if event_type == "charge.dispute.closed" and str(charge.get("status") or "") == "won":
        return {"received": True, "skipped": "dispute_won"}
    return {"received": True, **revoke_paid_order(db, row.out_trade_no, reason=reason)}


def _alert_stripe_mismatch(reference: str, reason: str, payload: dict[str, Any]) -> None:
    logger.error(
        "stripe webhook needs review: reference=%s reason=%s amount_total=%s currency=%s",
        reference,
        reason,
        payload.get("amount_total") or payload.get("amount"),
        payload.get("currency"),
    )
    try:
        from app.services.alerting import alert

        alert(
            "stripe_webhook_mismatch",
            f"Stripe webhook {reason} for {reference}",
            severity="error",
            context={"reference": reference, "reason": reason},
        )
    except Exception:
        pass
