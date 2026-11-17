def __getattr__(name):
    if name in {"ingest_harvest_rows", "settle_harvest_periods", "match_harvest_row"}:
        from app.services.harvest import ingest as _ingest

        return getattr(_ingest, name)
    if name in {"persist_unmatched", "list_unmatched", "attach_unmatched", "count_unmatched"}:
        from app.services.harvest import unmatched as _unmatched

        return getattr(_unmatched, name)
    raise AttributeError(name)
