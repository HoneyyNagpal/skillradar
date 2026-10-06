import argparse
import json
import logging

from . import config, demo, report, sources, transform
from .analysis import load, plan_gap, planner_data
from .db import copy_raw, get_engine, init_db


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skillradar", description="Hiring market intelligence for Indian tech jobs")
    ap.add_argument("--db", help="database URL (default: DATABASE_URL or data/skillradar.db). Use one database per source.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create tables and seed the skill dimension")
    sub.add_parser("probe-jsearch", help="make ONE JSearch request and print the response layout")

    p = sub.add_parser("ingest", help="fetch postings into the raw layer")
    p.add_argument("--source", choices=["jsearch", "adzuna", "csv", "demo"], default="jsearch")
    p.add_argument("--pages", type=int, default=2, help="pages per search term (jsearch, adzuna)")
    p.add_argument("--terms", help="comma separated search terms")
    p.add_argument("--max-requests", type=int, help="hard cap on API calls this run (jsearch)")
    p.add_argument("--date-posted", default="month", choices=["all", "today", "3days", "week", "month"], help="jsearch")
    p.add_argument("--path", help="csv file (csv)")
    p.add_argument("--colmap", help='json, e.g. \'{"title": "Job Title"}\' (csv)')
    p.add_argument("--weeks", type=int, default=12, help="weeks of synthetic history (demo)")

    c = sub.add_parser("copy-raw", help="copy raw postings from another database into this one")
    c.add_argument("--from", dest="src", required=True, help="source database URL, e.g. sqlite:///data/jsearch.db")
    c.add_argument("--force", action="store_true", help="copy even if the target already has raw rows")

    sub.add_parser("build", help="clean, deduplicate and tag raw postings")
    sub.add_parser("report", help="write docs/index.html and reports/findings.md")

    g = sub.add_parser("gap", help="which skill to learn next")
    g.add_argument("--skills", help="comma separated; default is PROFILE_SKILLS")
    g.add_argument("--role", help="e.g. 'Data Analyst'")
    g.add_argument("--level", default="entry", choices=["entry", "mid", "senior", "unspecified", "all"])

    r = sub.add_parser("run", help="ingest + build + report in one go (used by the weekly job)")
    r.add_argument("--source", choices=["jsearch", "adzuna", "demo"], default="jsearch")
    r.add_argument("--pages", type=int, default=2)
    r.add_argument("--max-requests", type=int)
    r.add_argument("--date-posted", default="week", choices=["all", "today", "3days", "week", "month"])

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "probe-jsearch":
        print(json.dumps(sources.probe_jsearch(), indent=2))
        return

    engine = get_engine(args.db)
    init_db(engine)

    if args.cmd == "init":
        print("database ready:", engine.url.render_as_string(hide_password=True))
    elif args.cmd == "ingest":
        print("raw rows added:", _ingest(engine, args))
    elif args.cmd == "copy-raw":
        print("raw rows copied:", copy_raw(get_engine(args.src), engine, force=args.force))
    elif args.cmd == "build":
        print(transform.build(engine))
    elif args.cmd == "report":
        d = report.write_all(engine)
        print("wrote docs/index.html and reports/findings.md for", d["overview"]["n_postings"], "postings;",
              d["overview"]["avg_skills"], "skills found per posting on average")
    elif args.cmd == "gap":
        posts, long = load(engine)
        data = planner_data(long, posts)
        have = [s.strip() for s in args.skills.split(",")] if args.skills else config.PROFILE_SKILLS
        res = plan_gap(data, have, role=args.role, level=None if args.level == "all" else args.level)
        print(f"{res['n_postings']} postings in slice. You fit {res['start']:.0%} today.")
        for i, s in enumerate(res["steps"], 1):
            print(f"  {i}. learn {s['skill']:<18} -> {s['coverage']:.0%} (+{s['gain'] * 100:.1f} pts)")
    elif args.cmd == "run":
        args.terms, args.path, args.colmap, args.weeks = None, None, None, 12
        print("raw rows added:", _ingest(engine, args))
        print(transform.build(engine))
        report.write_all(engine)
        print("report written")


def _ingest(engine, args) -> int:
    terms = [t.strip() for t in args.terms.split(",")] if getattr(args, "terms", None) else None
    if args.source == "demo":
        return demo.generate(engine, weeks=args.weeks)
    if args.source == "csv":
        if not args.path:
            raise SystemExit("--path is required for csv ingest")
        return sources.ingest_csv(engine, args.path, json.loads(args.colmap) if args.colmap else None)
    if args.source == "jsearch":
        return sources.ingest_jsearch(engine, terms, args.pages, args.max_requests, args.date_posted)
    return sources.ingest_adzuna(engine, terms, args.pages)


if __name__ == "__main__":
    main()