from skillradar import sources
from skillradar.sources import adapt, fetch_jsearch


JOB = {"job_id": "abc", "job_title": "Data Analyst", "employer_name": "Acme", "job_city": "Pune", "job_state": "MH",
       "job_description": "SQL and Excel required", "job_is_remote": False,
       "job_min_salary": 50000, "job_max_salary": 70000, "job_salary_period": "MONTH",
       "job_posted_at_datetime_utc": "2026-09-30T00:00:00.000Z"}


def test_jsearch_adapter_maps_fields_and_annualises_salary():
    c = adapt("jsearch", JOB)
    assert c["title"] == "Data Analyst" and c["company"] == "Acme" and c["location"] == "Pune, MH"
    assert c["salary_min"] == 600000 and c["salary_max"] == 840000          # monthly x 12


def test_jsearch_adapter_drops_unusable_salary_and_flags_remote():
    c = adapt("jsearch", {**JOB, "job_salary_period": "HOUR", "job_is_remote": True})
    assert c["salary_min"] is None and c["location"] == "Remote"


class FakeResp:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


def test_fetch_respects_request_cap_and_follows_cursor(monkeypatch):
    calls = []

    def fake_get(self, url, params=None, headers=None, timeout=None):
        calls.append(dict(params))
        return FakeResp({"data": [dict(JOB, job_id=f"j{len(calls)}")], "cursor": f"c{len(calls)}"})

    monkeypatch.setattr(sources.config, "JSEARCH_API_KEY", "test")
    monkeypatch.setattr("requests.Session.get", fake_get)
    jobs = list(fetch_jsearch(["a", "b"], pages=5, max_requests=3, pause=0))
    assert len(calls) == 3 and len(jobs) == 3
    assert "cursor" not in calls[0] and "cursor" in calls[2]             # second page of term "a" carries its cursor


def test_layout_detection_is_tolerant():
    assert sources._jobs_in({"data": {"jobs": [1, 2]}}) == [1, 2]
    assert sources._cursor_in({"data": {"next_cursor": "x"}}) == "x"
    assert sources._jobs_in("garbage") == []


def test_copy_raw_moves_snapshots_once(tmp_path):
    import pytest
    from sqlalchemy import func, select

    from skillradar import db, demo
    a = db.get_engine(f"sqlite:///{tmp_path}/a.db"); db.init_db(a)
    b = db.get_engine(f"sqlite:///{tmp_path}/b.db"); db.init_db(b)
    n = demo.generate(a, weeks=2, per_week=20)
    assert db.copy_raw(a, b) == n
    with b.connect() as c:
        assert c.execute(select(func.count()).select_from(db.raw_postings)).scalar() == n
        assert c.execute(select(func.sum(db.raw_postings.c.processed))).scalar() == 0
    with pytest.raises(SystemExit):
        db.copy_raw(a, b)