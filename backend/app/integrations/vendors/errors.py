"""Typed failures for music providers. The router decides retry, switch, or stop from `kind`."""

from __future__ import annotations

FAIL = "fail"
RETRY_SAME = "retry_same"
SWITCH = "switch"

_FAIL_KINDS = frozenset({"params", "moderation"})
_SWITCH_KINDS = frozenset({"auth", "balance", "rate_limit"})
_RETRY_KINDS = frozenset({"server", "timeout"})


class MusicProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str,
        retryable: bool = False,
        trace_id: str | None = None,
        user_message: str | None = None,
        status_code: int | None = None,
        provider: str = "",
        audio_url: str | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.trace_id = trace_id
        self.user_message = user_message or message
        self.status_code = status_code
        self.provider = provider
        self.audio_url = audio_url


def provider_failure_policy(exc: Exception, *, attempts_on_vendor: int) -> str:
    """One vendor failure: stop, try another key of the same vendor, or leave the vendor."""
    kind = getattr(exc, "kind", None)
    if kind in _FAIL_KINDS:
        return FAIL
    if kind in _SWITCH_KINDS:
        return SWITCH
    if kind in _RETRY_KINDS or kind is None:
        if attempts_on_vendor < 2:
            return RETRY_SAME
        return SWITCH
    return SWITCH


def cooldown_for(exc: Exception) -> int:
    kind = getattr(exc, "kind", "") or ""
    if kind in {"auth", "balance"}:
        return 1800
    if kind == "rate_limit":
        return 120
    if kind in {"server", "timeout"}:
        return 60
    return 120


def error_from_status(
    *,
    http_status: int | None = None,
    status_code: int | None = None,
    status_msg: str | None = None,
    trace_id: str | None = None,
    provider: str = "",
) -> MusicProviderError:
    kind, retryable, user_message = _classify(http_status, status_code, status_msg)
    detail = (status_msg or "").strip()
    code_bit = status_code if status_code is not None else http_status
    message = user_message
    if detail and detail.lower() not in user_message.lower():
        message = f"{user_message}（{detail}）"
    if code_bit is not None:
        message = f"{message} [code={code_bit}]"
    if trace_id:
        message = f"{message} trace_id={trace_id}"
    return MusicProviderError(
        message,
        kind=kind,
        retryable=retryable,
        trace_id=trace_id,
        user_message=user_message,
        status_code=status_code if status_code is not None else http_status,
        provider=provider,
    )


def coerce_music_error(exc: Exception, *, provider: str = "") -> MusicProviderError:
    if isinstance(exc, MusicProviderError):
        if provider and not exc.provider:
            exc.provider = provider
        return exc
    name = type(exc).__name__
    msg = str(exc)
    lowered = msg.lower()
    if "Timeout" in name or "timeout" in lowered or "timed out" in lowered:
        return MusicProviderError(
            msg or "音乐生成超时",
            kind="timeout",
            retryable=True,
            user_message="音乐生成超时，请稍后重试",
            provider=provider,
        )
    kind, retryable, user_message = _classify(None, _code_in_message(msg), msg)
    if kind == "server" and not any(token in msg for token in ("审核", "余额", "API Key", "参数", "限流", "频繁")):
        if "connect" in lowered or "network" in lowered or "disconnected" in lowered:
            kind, retryable = "timeout", True
            user_message = "音乐生成服务连接中断，请稍后重试"
    return MusicProviderError(
        msg or user_message,
        kind=kind,
        retryable=retryable,
        user_message=user_message,
        status_code=_code_in_message(msg),
        provider=provider,
    )


def _code_in_message(msg: str) -> int | None:
    import re

    match = re.search(r"\[code=(\d+)\]|\[(\d+)\]", msg or "")
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    try:
        return int(raw)
    except ValueError:
        return None


def _classify(
    http_status: int | None,
    status_code: int | None,
    status_msg: str | None,
) -> tuple[str, bool, str]:
    msg = (status_msg or "").lower()
    code = status_code
    if code in {1004, 2049} or http_status in {401, 403} or any(token in msg for token in ("api key", "unauthorized", "鉴权", "未授权")):
        return "auth", False, "音乐服务鉴权失败，请稍后再试"
    if code == 1008 or any(token in msg for token in ("余额", "balance", "quota", "用量")):
        return "balance", False, "音乐服务额度不足，请稍后再试"
    if code in {1026, 1027} or any(token in msg for token in ("审核", "涉敏", "moderation", "违规")):
        return "moderation", False, "内容未通过审核，请修改描述或歌词后再试"
    if code == 2013 or http_status in {400, 422} or any(token in msg for token in ("参数", "必填", "invalid param", "missing")):
        return "params", False, "生成参数不完整，请检查描述和歌词"
    if code == 1002 or http_status == 429 or any(token in msg for token in ("限流", "频繁", "rate limit", "too many")):
        return "rate_limit", True, "音乐生成排队较多，请稍后再试"
    if code == 1001 or "timeout" in msg or "超时" in msg:
        return "timeout", True, "音乐生成超时，请稍后重试"
    if http_status is not None and http_status >= 500:
        return "server", True, "音乐服务暂时不可用，请稍后重试"
    if code in {1000, 1024, 1033, 2045, 2151}:
        return "server", True, "音乐服务暂时不可用，请稍后重试"
    return "server", True, "音乐生成失败，请稍后重试"
