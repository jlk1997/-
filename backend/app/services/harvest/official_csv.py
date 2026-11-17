"""Official store CSV parser — preferred over DOM scrape when the creator exports a file."""

from __future__ import annotations

import csv
import io
import re

from app.services.royalty.ingest import HEADER_ALIASES

TRACK_CODE_RE = re.compile(r"\[?(VS[0-9A-F]{12})\]?", re.I)


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").strip().lower())


def _header_index(headers: list[str], aliases: set[str]) -> int:
    wanted = {_norm_header(item) for item in aliases}
    for index, header in enumerate(headers):
        if _norm_header(header) in wanted:
            return index
    return -1


def _parse_number(raw: str) -> float:
    text = re.sub(r"[^\d.-]", "", (raw or "").replace(",", ""))
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def parse_official_csv(text: str, channel_code: str | None = None) -> list[dict]:
    if not (text or "").strip():
        return []
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    try:
        headers = next(reader)
    except StopIteration:
        return []
    title_idx = _header_index(headers, HEADER_ALIASES["title"])
    stream_idx = _header_index(headers, HEADER_ALIASES["streams"])
    revenue_idx = _header_index(headers, HEADER_ALIASES.get("revenue") or set())
    isrc_idx = _header_index(headers, HEADER_ALIASES.get("isrc") or set())
    if title_idx < 0 and stream_idx < 0 and revenue_idx < 0:
        return []
    blob = " ".join(headers)
    currency = "USD" if re.search(r"usd|\$", blob, re.I) else "CNY"
    rows: list[dict] = []
    for cells in reader:
        if not cells:
            continue
        title = (cells[title_idx] if 0 <= title_idx < len(cells) else (cells[0] if cells else "")).strip()
        streams = int(_parse_number(cells[stream_idx])) if 0 <= stream_idx < len(cells) else 0
        revenue_raw = cells[revenue_idx] if 0 <= revenue_idx < len(cells) else ""
        revenue = _parse_number(revenue_raw)
        revenue_minor = int(round(revenue)) if abs(revenue) >= 100 and revenue == int(revenue) else int(round(revenue * 100))
        if not title and not streams and not revenue_minor:
            continue
        code_match = TRACK_CODE_RE.search(title)
        code = code_match.group(1).upper() if code_match else ""
        isrc = (cells[isrc_idx].strip() if 0 <= isrc_idx < len(cells) else "") or code
        if "$" in revenue_raw:
            currency = "USD"
        rows.append(
            {
                "title": title,
                "channel_code": channel_code,
                "isrc": isrc or None,
                "track_code": code or None,
                "streams": streams,
                "revenue_minor": revenue_minor,
                "currency": currency,
                "confidence": 0.95,
                "extractor_version": "official_csv",
                "raw": {"source": "official_csv"},
            }
        )
    return rows
