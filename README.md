# SkillRadar India

A weekly pipeline that tracks Indian tech job postings, extracts the skills employers ask for, and turns them into decisions: what is rising, what travels together, and what a fresher should learn next.

It answers one question properly: **given the skills I have today, which one skill should I add next to open the most entry-level doors?**

**Live dashboard:** https://honeyynagpal.github.io/skillradar/ (rebuilt every Monday by GitHub Actions)
Findings write-up: [`reports/findings.md`](reports/findings.md)

## What I found building it

**The first data source was wrong for this job, and the pipeline told me.** Adzuna's API returns shortened job descriptions. Across 1,441 postings the skill extractor found 0.9 skills per posting and 65% of postings had none, so every demand percentage was an undercount and the entry-versus-senior comparison was an artifact of text length. The dashboard now raises a warning when that happens. I switched the primary source to JSearch, which returns full descriptions: 6.9 skills per posting on 350 postings. Adzuna remains supported as a secondary source.

**Week 1 snapshot, 350 postings, preliminary** (the sample is defined by my search terms, so read it as "postings matching these searches", not the whole market):

- Excel appears in 33% of entry-level postings and 4% of senior ones. CI/CD is the reverse: 3% of entry-level, 53% of senior.
- HTML + CSS co-occur 9.1x more often than chance (31 postings); Docker + Kubernetes 4.9x (40 postings). Both survive false discovery control.
- Trends are not reported yet: the code refuses to draw one from fewer than 6 weekly snapshots. The first trend appears with the 6th Monday run.

## Architecture

```
JSearch API (Adzuna / CSV also supported)
        |  ingest  (append-only, original payload kept)
        v
  raw_postings  --build-->  postings  +  skills  +  posting_skills
                  |  normalise city, classify role + seniority,
                  |  dedupe reposts, tag skills, parse salary
                  v
   sql/*.sql (window functions, joins)  +  pandas / scipy statistics
                  |
                  v
   docs/index.html (interactive dashboard)   reports/findings.md
```

Runs on SQLite locally and on PostgreSQL by setting `DATABASE_URL`. A GitHub Actions job runs every Monday against a hosted PostgreSQL (the runner's disk is wiped after each run, so snapshots must live elsewhere).

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src

# 1. See it work offline (synthetic data, clearly labelled with a banner)
python -m skillradar --db sqlite:///data/demo.db ingest --source demo
python -m skillradar --db sqlite:///data/demo.db build
python -m skillradar --db sqlite:///data/demo.db report      # open docs/index.html

# 2. Real data
cp .env.example .env     # add JSEARCH_API_KEY (free: openwebninja.com/api/jsearch)
python -m skillradar probe-jsearch                          # one request, checks the key and response layout
python -m skillradar ingest --source jsearch                # capped at JSEARCH_MAX_REQUESTS
python -m skillradar build && python -m skillradar report
```

The JSearch free tier is a hard 200 requests per month and each request returns 10 postings, so the weekly job is capped at 38 requests (19 search terms, 2 pages). Four Monday runs fit inside the month.

Use one database per source so data never mixes. `copy-raw --from <url>` moves stored snapshots between databases, for example from local SQLite to hosted PostgreSQL, without spending API quota. No API access? `ingest --source csv --path jobs.csv --colmap '{"title":"Job Title","description":"Job Description"}'` works with any jobs CSV. Do not scrape sites whose terms forbid it.

## What is in the analysis

| Question | Method |
|---|---|
| What is in demand? | Share of postings mentioning each skill, per role family, from SQL window functions |
| What is rising or falling? | Cochran-Armitage trend test on weekly proportions, Benjamini-Hochberg false discovery control |
| What travels together? | Pair counts in SQL, chi-square test per pair, FDR correction, ranked by phi (effect size) plus lift |
| What do freshers need versus seniors? | Skill share within entry-level and senior postings |
| Where does a new skill pay off first? | Transparent heuristic: 50% entry demand, 25% growth, 25% breadth across roles |
| Does a skill pay more? | Salary relative to the median of the same role family and level, bootstrap intervals, explicit coverage figure (skipped when under 5% of postings state pay) |
| Which city over-indexes on what? | Location quotient, one-sided binomial test, FDR correction |
| What should I learn next? | Greedy set cover over postings: a posting "fits" when you hold at least 60% of its listed skills |

## Design decisions worth knowing

- **Trends use first-seen week, not posted date.** An API only returns open postings, so old posted dates make early weeks look thin and fake a boom.
- **A posting is one real job.** Title, company and city are normalised and hashed; reposts across weeks count once.
- **Precision beats recall in skill matching.** Boundaries stop `Java` firing inside `JavaScript`; ordinary words (`react`, `excel`, `go`, `R&D`) only count in their technical form. Tests pin this.
- **Statistical guardrails are code, not caveats.** Minimum sample sizes, FDR correction, a refusal to trend fewer than 6 weeks, a refusal to advise from a planner slice under 30 postings, and a data-quality banner when the source truncates text.
- **The pipeline is validated against known truth.** The demo generator plants rising, falling and clustered skills; the tests check that the analysis recovers them and does not invent others.
- **The dashboard planner is tested against the Python planner** so the browser and the CLI never disagree.
- **Verified on both databases.** The same data produces identical report output on SQLite and PostgreSQL.

## Tests

```bash
PYTHONPATH=src pytest -q
```

## Limitations

Dictionary-based skill extraction misses unusual phrasing; the sample is defined by the search terms, so it describes postings matching those searches; one source is one view of the market; Indian postings rarely state salary, so pay is mostly unanalysed; "fit" measures overlap with what postings list, not hiring outcomes.

## Roadmap

Embedding-based skill extraction compared against the dictionary (precision and recall on a hand-labelled sample), a second full-text source to cross-check JSearch, and a salary model once enough pay data accumulates.