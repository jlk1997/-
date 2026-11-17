"""One next step for the creator. Same order the desk already uses."""

from __future__ import annotations


def primary_creator_step(
    *,
    works: int = 0,
    releases: int = 0,
    unpublished_count: int = 0,
    degraded_count: int = 0,
    needs_beautify_count: int = 0,
    qc_pending_count: int = 0,
    session_wait_count: int = 0,
    upload_wait_count: int = 0,
    unmatched_count: int = 0,
    in_review_count: int = 0,
    has_live: bool = False,
    delivering: bool = False,
    has_available: bool = False,
    has_pending: bool = False,
    pending_confirm_count: int = 0,
) -> dict:
    if works <= 0:
        step = "generate"
    elif degraded_count > 0:
        step = "reprocess"
    elif needs_beautify_count > 0:
        step = "beautify"
    elif qc_pending_count > 0:
        step = "qc"
    elif unpublished_count > 0 or releases <= 0:
        step = "release"
    elif upload_wait_count > 0 and session_wait_count <= 0 and delivering:
        step = "stores"
    elif session_wait_count > 0 and delivering:
        step = "connector"
    elif in_review_count > 0:
        step = "wait_review"
    elif not delivering or not has_live:
        step = "stores"
    elif unmatched_count > 0:
        step = "import"
    elif pending_confirm_count > 0 and not has_available:
        step = "settlements"
    elif has_live and not has_available and not has_pending:
        step = "sync"
    else:
        step = "wallet"
    return {"step": step, "source": "primary_creator_step"}


def next_for_work(
    *,
    has_audio: bool = True,
    degraded: bool = False,
    needs_beautify: bool = False,
    has_release: bool = False,
    delivering: bool = False,
    live: bool = False,
    has_revenue: bool = False,
    pending_confirm: bool = False,
    requested_fields: list[str] | None = None,
) -> dict:
    """One next step for a single song. Release stays ahead of store handoff."""
    if requested_fields:
        step = "fill_release"
    elif not has_audio:
        step = "generate"
    elif degraded:
        step = "reprocess"
    elif needs_beautify:
        step = "beautify"
    elif not has_release:
        step = "release"
    elif delivering and not live:
        step = "stores"
    elif live and not has_revenue:
        step = "sync"
    elif pending_confirm:
        step = "settlements"
    else:
        step = "wallet"
    return {"step": step, "source": "next_for_work"}
