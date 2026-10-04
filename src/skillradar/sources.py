"""Ingestion. Every source writes its original payload to raw_postings (append-only) and exposes an
adapter that maps that payload onto one common shape for the transform step."""
import csv
import json
import logging
import time
from datetime import datetime, timezone

import requests
from sqlalchemy import insert

from . import config
from .db import raw_postings

log = logging.getLogger("skillradar.ingest")

COMMON_FIELDS = ("external_id", "title", "company", "location", "description",
                 "salary_min", "salary_max", "posted_date")


def adapt(source: str, payload: dict) -> dict:
    """Map a raw payload to the common shape."""
    if source == "adzuna":
        predicted = str(payload.get("salary_is_predicted", "0")) == "1"  # Adzuna's own estimates are not real pay
        return {
            "external_id": str(payload.get("id", "")),
            "title": payload.get("title") or "",
            "company": (payload.get("company") or {}).get("display_name"),
            "location": (payload.get("location") or {}).get("display_name"),
            "description": payload.get("description") or "",
            "salary_min": None if predicted else payload.get("salary_min"),
            "salary_max": None if predicted else payload.get("salary_max"),
            "posted_date": payload.get("created"),
        }
    if source == "jsearch":
        mult = {"YEAR": 1, "MONTH": 12, "WEEK": 52}.get((payload.get("job_salary_period") or "").upper())
        smin, smax = payload.get("job_min_salary"), payload.get("job_max_salary")
        where = "Remote" if payload.get("job_is_remote") else (
            ", ".join(x for x in (payload.get("job_city"), payload.get("job_state")) if x)
            or payload.get("job_location") or payload.get("job_country"))
        return {
            "external_id": str(payload.get("job_id", "")),
            "title": payload.get("job_title") or "",
            "company": payload.get("employer_name"),
            "location": where,
            "description": payload.get("job_description") or "",
            "salary_min": smin * mult if smin and mult else None,
            "salary_max": smax * mult if smax and mult else None,
            "posted_date": payload.get("job_posted_at_datetime_utc"),
        }
    # demo, csv: payloads are already stored in the common shape
    return {k: payload.get(k) for k in COMMON_FIELDS}


def store_raw(engine, source: str, payloads: list[dict], fetched_at: datetime | None = None) -> int:
    fetched_at = fetched_at or datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [{"source": source, "fetched_at": fetched_at, "payload": json.dumps(p, default=str), "processed": 0}
            for p in payloads]
    if rows:
        with engine.begin() as conn:
            conn.execute(insert(raw_postings), rows)
    return len(rows)


# ---------------------------------------------------------------- Adzuna
def fetch_adzuna(terms=None, pages=3, per_page=50, max_days_old=30, pause=1.5):
    """Yield raw Adzuna results. Needs ADZUNA_APP_ID / ADZUNA_APP_KEY. Check your plan's rate limits."""
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        raise RuntimeError("Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com).")
    session = requests.Session()
    for term in terms or config.SEARCH_TERMS:
        for page in range(1, pages + 1):
            url = f"https://api.adzuna.com/v1/api/jobs/{config.ADZUNA_COUNTRY}/search/{page}"
            params = {"app_id": config.ADZUNA_APP_ID, "app_key": config.ADZUNA_APP_KEY,
                      "what": term, "results_per_page": per_page, "max_days_old": max_days_old,
                      "sort_by": "date", "content-type": "application/json"}
            results = None
            for attempt in range(4):
                resp = session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    log.warning("rate limited, sleeping %ss", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                results = resp.json().get("results", [])
                break
            if not results:
                break  # no more pages for this term
            log.info("adzuna %-28s page %d: %d results", term, page, len(results))
            yield from results
            time.sleep(pause)


def ingest_adzuna(engine, terms=None, pages=3) -> int:
    return store_raw(engine, "adzuna", list(fetch_adzuna(terms, pages)))


# ---------------------------------------------------------------- JSearch (full descriptions)
JSEARCH_URL = "https://api.openwebninja.com/jsearch/search-v2"


def _jobs_in(body):
    """The response layout is not guaranteed, so look in the likely places."""
    if not isinstance(body, dict):
        return []
    for holder in (body, body.get("data") if isinstance(body.get("data"), dict) else {}):
        for key in ("data", "jobs", "results"):
            if isinstance(holder.get(key), list):
                return holder[key]
    return []


def _cursor_in(body):
    if not isinstance(body, dict):
        return None
    holders = [body] + [body[k] for k in ("data", "parameters", "meta", "pagination") if isinstance(body.get(k), dict)]
    for h in holders:
        for key in ("cursor", "next_cursor"):
            if h.get(key):
                return h[key]
    return None


def _jsearch_get(session, params, retries=3):
    if not config.JSEARCH_API_KEY:
        raise RuntimeError("Set JSEARCH_API_KEY (free at openwebninja.com/api/jsearch).")
    for attempt in range(retries + 1):
        resp = session.get(JSEARCH_URL, params=params, headers={"x-api-key": config.JSEARCH_API_KEY}, timeout=60)
        if resp.status_code == 429 and attempt < retries:
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code in (401, 403):
            raise RuntimeError(f"JSearch rejected the key (HTTP {resp.status_code}). Check JSEARCH_API_KEY and your plan.")
        resp.raise_for_status()
        return resp.json()


def probe_jsearch() -> dict:
    """One request, to see the real response layout before spending the monthly quota."""
    body = _jsearch_get(requests.Session(), {"query": "data analyst in India", "country": "in", "language": "en"})
    jobs = _jobs_in(body)
    return {"top_level_keys": sorted(body) if isinstance(body, dict) else type(body).__name__,
            "jobs_found": len(jobs), "cursor_found": bool(_cursor_in(body)),
            "first_job_fields": sorted(jobs[0]) if jobs else [],
            "description_chars_first_job": len((jobs[0].get("job_description") or "")) if jobs else 0}


def fetch_jsearch(terms=None, pages=2, max_requests=None, date_posted="month", pause=0.5):
    """Breadth first: page 1 of every term, then page 2, and so on, stopping at the request cap."""
    terms = list(terms or config.SEARCH_TERMS)
    cap = max_requests if max_requests is not None else config.JSEARCH_MAX_REQUESTS
    session, used = requests.Session(), 0
    cursors = {t: None for t in terms}
    live = set(terms)
    for page in range(pages):
        for term in terms:
            if term not in live:
                continue
            if used >= cap:
                log.warning("request cap of %d reached; stopping", cap)
                return
            params = {"query": f"{term} in India", "country": "in", "language": "en", "date_posted": date_posted}
            if cursors[term]:
                params["cursor"] = cursors[term]
            body = _jsearch_get(session, params)
            used += 1
            jobs = _jobs_in(body)
            cursors[term] = _cursor_in(body)
            log.info("jsearch %-30s page %d: %d results (%d/%d requests)", term, page + 1, len(jobs), used, cap)
            if not jobs or (page > 0 and not cursors[term]) or not cursors[term]:
                live.discard(term)
            yield from jobs
            time.sleep(pause)


def ingest_jsearch(engine, terms=None, pages=2, max_requests=None, date_posted="month") -> int:
    return store_raw(engine, "jsearch", list(fetch_jsearch(terms, pages, max_requests, date_posted)))


# ---------------------------------------------------------------- CSV (Kaggle dumps etc.)
def ingest_csv(engine, path: str, colmap: dict | None = None, fetched_at: datetime | None = None) -> int:
    """colmap maps common field -> csv column, e.g. {"title": "Job Title", "description": "Job Desc"}."""
    colmap = colmap or {}
    payloads = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            p = {f: row.get(colmap.get(f, f)) for f in COMMON_FIELDS}
            p["external_id"] = p["external_id"] or f"csv-{i}"
            payloads.append(p)
    return store_raw(engine, "csv", payloads, fetched_at)