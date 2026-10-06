"""Turns the analysis dict into a self-contained dashboard (docs/index.html, ready for GitHub Pages)
and a plain-language findings file (reports/findings.md)."""
import json
from datetime import date
from pathlib import Path

from . import analysis, config

TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"


def build_data(engine) -> dict:
    data = analysis.compute_all(engine)
    data["generated"] = date.today().isoformat()
    data["config"] = {"coverage_threshold": config.COVERAGE_THRESHOLD, "fdr": config.FDR_ALPHA,
                      "min_pair_support": config.MIN_PAIR_SUPPORT}
    return data


def headline(d: dict) -> str:
    ov, top = d["overview"], d["top_skills"][:3]
    parts = [f"{ov['n_postings']:,} tech postings over {ov['n_weeks']} week{'s' if ov['n_weeks'] != 1 else ''}."]
    if top:
        lead = f"{top[0]['skill']} appears in {top[0]['share']:.0%} of them"
        if len(top) > 1:
            lead += ", ahead of " + " and ".join(f"{t['skill']} ({t['share']:.0%})" for t in top[1:])
        parts.append(lead + ".")
    rising = [t["skill"] for t in d["trends"] if t["direction"] == "rising"][:3]
    falling = [t["skill"] for t in d["trends"] if t["direction"] == "falling"][-2:]
    if rising:
        parts.append(f"Climbing fastest: {', '.join(rising)}.")
    if falling:
        parts.append(f"Fading: {', '.join(falling)}.")
    if not rising and not falling and d["trend_note"]:
        parts.append("Trends need more weeks of data before they mean anything.")
    return " ".join(parts)


def render_html(d: dict) -> str:
    blob = json.dumps(d, default=str).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    return (html.replace("__HEADLINE__", headline(d)).replace("__GENERATED__", d["generated"])
            .replace("__DATA__", blob))


def render_markdown(d: dict) -> str:
    ov = d["overview"]
    L = []
    if ov["is_demo"]:
        L += ["> **Demo data.** Synthetic postings from `skillradar demo`. None of the findings below describe the real market.", ""]
    L += ["# Findings", "", headline(d), "",
          f"Window: {ov['first_week']} to {ov['last_week']}. Salary stated in {ov['salary_coverage']:.0%} of postings. "
          f"Average {ov['avg_skills']} recognised skills per posting; {ov['no_skill_share']:.1%} of postings matched none.", ""]
    L += ["## Most requested skills", "", "| Skill | Postings | Share |", "|---|---:|---:|"]
    L += [f"| {t['skill']} | {t['n']} | {t['share']:.1%} |" for t in d["top_skills"][:10]]
    L += ["", "## Trends", ""]
    if d["trend_note"]:
        L.append(d["trend_note"])
    else:
        for name, flag in (("Rising", "rising"), ("Falling", "falling")):
            rows = [t for t in d["trends"] if t["direction"] == flag]
            L.append(f"**{name}** (false discovery rate 5%): " + (", ".join(
                f"{t['skill']} ({t['first_avg']:.1f}% to {t['last_avg']:.1f}%)" for t in rows) or "none"))
            L.append("")
    L += ["## Skills that travel together", "", "| Pair | Both | Lift | Phi |", "|---|---:|---:|---:|"]
    L += [f"| {p['skill_a']} + {p['skill_b']} | {p['n_both']} | {p['lift']:.1f}x | {p['phi']:.2f} |" for p in d["pairs"][:10]]
    L += ["", "## Where a new skill pays off first (heuristic)", "", "| Skill | Score | Entry demand | Growth pts/wk | Roles |", "|---|---:|---:|---:|---:|"]
    L += [f"| {o['skill']} | {o['score']:.0f} | {o['entry_share']:.0%} | {o['slope']:+.2f} | {o['breadth']} |" for o in d["opportunity"][:10]]
    pp = d["profile_plan"]
    L += ["", "## Gap plan for the configured profile (entry level, all roles)", "",
          f"Profile fits {pp['start']:.0%} of {pp['n_postings']} postings today."]
    L += [f"{i}. Add **{s['skill']}**: {s['coverage']:.0%} (+{s['gain'] * 100:.1f} pts)" for i, s in enumerate(pp["steps"], 1)]
    L += ["", "## Limits", "",
          "Dictionary-based skill extraction, truncated API descriptions, sparse salary data and a short observation window. "
          "See the dashboard footer for the full method.", ""]
    return "\n".join(L)


def write_all(engine, docs_dir=None, reports_dir=None) -> dict:
    docs_dir, reports_dir = Path(docs_dir or config.DOCS_DIR), Path(reports_dir or config.REPORTS_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    d = build_data(engine)
    (docs_dir / "index.html").write_text(render_html(d), encoding="utf-8")
    (reports_dir / "findings.md").write_text(render_markdown(d), encoding="utf-8")
    return d