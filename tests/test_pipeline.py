import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skillradar import analysis, report, transform

ROOT = Path(__file__).resolve().parents[1]


def test_dedupe_collapses_reposts(engine):
    s = engine.build_stats
    assert s["reseen"] > 0 and s["new_postings"] < s["raw_rows"]
    assert s["new_postings"] + s["reseen"] == s["raw_rows"]


def test_build_is_idempotent(engine):
    again = transform.build(engine)
    assert again["raw_rows"] == 0 and again["new_postings"] == 0


def test_no_false_positive_skills_from_prose(frames):
    posts, long = frames
    da = posts[posts.role_family == "Data Analyst"]
    in_da = long[long.posting_id.isin(da.posting_id)]
    share = lambda s: (in_da.skill == s).sum() / len(da)
    assert share("React") < 0.01          # the word "react" appears in filler text
    assert share("Go") < 0.01 and share("R") < 0.01
    assert share("SQL") > 0.8             # while a planted core skill is found


def test_planted_trends_are_recovered(engine):
    wk = analysis.q(engine, "weekly_skill_share")
    tr, note = analysis.trend_table(wk)
    assert note is None
    d = tr.set_index("skill")["direction"]
    assert d["LangChain"] == "rising" and d["RAG"] == "rising"
    assert d["jQuery"] == "falling" and d["Hadoop"] == "falling"
    assert d.get("Docker", "flat") == "flat"


def test_trends_refuse_to_run_on_short_history(engine):
    wk = analysis.q(engine, "weekly_skill_share")
    wk["week_start"] = __import__("pandas").to_datetime(wk["week_start"])
    short = wk[wk.week_start <= sorted(wk.week_start.unique())[3]]
    tr, note = analysis.trend_table(short)
    assert tr.empty and "weeks" in note


def test_planted_clusters_surface_as_pairs(engine, frames):
    posts, long = frames
    pairs = analysis.pair_table(engine, long, len(posts))
    found = {frozenset((r.skill_a, r.skill_b)) for r in pairs.itertuples()}
    assert frozenset(("HTML", "CSS")) in found
    assert frozenset(("Excel", "Power BI")) in found
    assert (pairs.q < 0.05).all() and (pairs.lift > 1).all()


def test_bh_correction_is_monotone_and_bounded():
    import numpy as np
    p = np.array([0.001, 0.01, 0.02, 0.5, 0.9])
    q = analysis.bh_qvalues(p)
    assert (q >= p).all() and (q <= 1).all() and (np.diff(q[np.argsort(p)]) >= 0).all()


def test_gap_planner_is_monotone_and_sensible(frames):
    posts, long = frames
    data = analysis.planner_data(long, posts)
    res = analysis.plan_gap(data, ["Python", "SQL"], role="Data Analyst", level="entry")
    cov = [res["start"]] + [s["coverage"] for s in res["steps"]]
    assert all(b > a for a, b in zip(cov, cov[1:]))
    assert res["steps"][0]["skill"] in {"Excel", "Power BI"}


def test_salary_premium_reports_coverage_and_intervals(frames):
    posts, long = frames
    sal = analysis.salary_table(long, posts)
    assert 0.3 < sal["coverage"] < 0.4
    assert sal["rows"] and all(r["lo"] <= r["premium"] <= r["hi"] for r in sal["rows"])


def test_report_renders_and_flags_demo_data(engine, tmp_path):
    d = report.write_all(engine, docs_dir=tmp_path / "docs", reports_dir=tmp_path / "reports")
    html = (tmp_path / "docs" / "index.html").read_text()
    assert "__DATA__" not in html and "__HEADLINE__" not in html
    blob = html.split("const D = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(blob)["overview"]["is_demo"] is True
    assert "Demo data" in (tmp_path / "reports" / "findings.md").read_text()
    assert d["overview"]["n_postings"] > 5000


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_planner_matches_python(frames, tmp_path):
    posts, long = frames
    data = analysis.planner_data(long, posts)
    py = analysis.plan_gap(data, ["Python", "SQL", "React"], role="Full Stack", level="entry")
    src = (ROOT / "src/skillradar/templates/dashboard.html").read_text()
    block = src.split("/* ---------- pure planner logic", 1)[1].split("if (typeof module", 1)[0]
    block = block.split("*/", 1)[1]
    (tmp_path / "p.json").write_text(json.dumps(data))
    script = block + "\nconst P = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'));" + \
        "console.log(JSON.stringify(planGap(P, ['Python','SQL','React'], %d, %d, 5, 0.6)));" % (
            data["roles"].index("Full Stack"), data["levels"].index("entry"))
    out = subprocess.run(["node", "-e", script, str(tmp_path / "p.json")], capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    assert js["n"] == py["n_postings"]
    assert abs(js["start"] - py["start"]) < 1e-12
    assert [s["skill"] for s in js["steps"]] == [s["skill"] for s in py["steps"]]
