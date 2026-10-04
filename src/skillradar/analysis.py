"""Analysis layer. SQL does the heavy lifting (window functions, joins); pandas/scipy do the statistics.

Everything reported passes a guardrail from config.py: minimum sample sizes, a false discovery rate
correction for multiple tests, and explicit coverage numbers for sparse fields such as salary.
"""
import math

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text

from . import config

LEVELS = ["entry", "mid", "senior", "unspecified"]


def q(engine, name: str, **params) -> pd.DataFrame:
    sql = (config.SQL_DIR / f"{name}.sql").read_text()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params)


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(ranked, 1.0)
    return out


# ------------------------------------------------------------------ loading
def load(engine):
    posts = q(engine, "postings_all")
    long = q(engine, "posting_skill_long")
    for df in (posts, long):
        df["first_seen_week"] = pd.to_datetime(df["first_seen_week"])
    return posts, long


# ------------------------------------------------------------------ overview
def overview(posts: pd.DataFrame, long: pd.DataFrame) -> dict:
    n = len(posts)
    sources = posts["source"].value_counts().to_dict()
    per_post = long.groupby("posting_id").size().reindex(posts["posting_id"]).fillna(0)
    return {
        "n_postings": int(n),
        "n_weeks": int(posts["first_seen_week"].nunique()),
        "first_week": posts["first_seen_week"].min().strftime("%Y-%m-%d") if n else None,
        "last_week": posts["first_seen_week"].max().strftime("%Y-%m-%d") if n else None,
        "sources": sources,
        "is_demo": bool(n) and set(sources) == {"demo"},
        "salary_coverage": round(float(posts["salary_lpa"].notna().mean()), 3) if n else 0,
        "no_skill_share": round(float((per_post == 0).mean()), 3) if n else 0,
        "avg_skills": round(float(per_post.mean()), 2) if n else 0,
        "seniority_mix": {k: round(float(v), 3) for k, v in posts["seniority"].value_counts(normalize=True).items()},
        "n_skills": int(long["skill"].nunique()),
    }


# ------------------------------------------------------------------ demand and trend
def top_skills(long: pd.DataFrame, n_postings: int, k=20) -> pd.DataFrame:
    t = long.groupby("skill").size().sort_values(ascending=False).head(k).rename("n").reset_index()
    t["share"] = t["n"] / n_postings
    return t


def cochran_armitage(x: np.ndarray, n: np.ndarray) -> tuple[float, float]:
    """Cochran-Armitage test for a linear trend in proportions x_i / n_i across ordered weeks.
    Returns (z, two-sided p). Handles the unequal and small counts that break plain OLS on shares."""
    t = np.arange(len(x), dtype=float)
    N, X = n.sum(), x.sum()
    p = X / N
    if p in (0.0, 1.0):
        return 0.0, 1.0
    num = np.sum(t * (x - n * p))
    var = p * (1 - p) * (np.sum(n * t ** 2) - np.sum(n * t) ** 2 / N)
    if var <= 0:
        return 0.0, 1.0
    z = num / math.sqrt(var)
    return z, float(2 * stats.norm.sf(abs(z)))


def trend_table(wk: pd.DataFrame, max_weeks=12) -> tuple[pd.DataFrame, str | None]:
    wk = wk.copy()
    wk["week_start"] = pd.to_datetime(wk["week_start"])
    weeks = sorted(wk["week_start"].unique())[-max_weeks:]
    if len(weeks) < config.MIN_WEEKS_FOR_TREND:
        return pd.DataFrame(), (f"Only {len(weeks)} weeks of data. Trends need at least "
                                f"{config.MIN_WEEKS_FOR_TREND}; keep the weekly job running.")
    wk = wk[wk["week_start"].isin(weeks)]
    rows = []
    for skill, g in wk.groupby("skill"):
        if g["n_mentions"].sum() < config.MIN_SKILL_POSTINGS:
            continue
        g = g.sort_values("week_start")
        x, n = g["n_mentions"].to_numpy(float), g["n_postings"].to_numpy(float)
        z, p = cochran_armitage(x, n)
        y = g["share"].to_numpy() * 100
        slope = stats.linregress(np.arange(len(y)), y).slope
        rows.append({"skill": skill, "slope_pp_per_week": slope, "z": z, "p": p,
                     "first_avg": y[:3].mean(), "last_avg": y[-3:].mean(), "mentions": int(x.sum())})
    t = pd.DataFrame(rows)
    if t.empty:
        return t, "No skill has enough mentions to trend yet."
    t["q"] = bh_qvalues(t["p"].to_numpy())
    sig = t["q"] < config.FDR_ALPHA
    t["direction"] = np.where(sig & (t["z"] > 0), "rising", np.where(sig & (t["z"] < 0), "falling", "flat"))
    return t.sort_values("z", ascending=False), None


def trend_series(wk: pd.DataFrame, skills_list: list[str]) -> dict:
    wk = wk.copy()
    wk["week_start"] = pd.to_datetime(wk["week_start"])
    weeks = sorted(wk["week_start"].unique())
    out = {"weeks": [pd.Timestamp(w).strftime("%Y-%m-%d") for w in weeks], "share": {}, "ma4": {}}
    for s in skills_list:
        g = wk[wk["skill"] == s].set_index("week_start").reindex(weeks)
        out["share"][s] = [round(float(v) * 100, 2) for v in g["share"]]
        out["ma4"][s] = [round(float(v) * 100, 2) for v in g["share_ma4"]]
    return out


# ------------------------------------------------------------------ co-occurrence
def pair_table(engine, long: pd.DataFrame, n_postings: int) -> pd.DataFrame:
    pairs = q(engine, "skill_pairs", min_support=config.MIN_PAIR_SUPPORT)
    if pairs.empty:
        return pairs
    with engine.connect() as conn:
        names = dict(conn.execute(text("SELECT skill_id, name FROM skills")).fetchall())
    marg = long.groupby("skill").size().to_dict()
    rows = []
    for r in pairs.itertuples():
        a, b = names[r.skill_a], names[r.skill_b]
        na, nb, both = marg[a], marg[b], int(r.n_both)
        table = np.array([[both, na - both], [nb - both, n_postings - na - nb + both]])
        if (table < 0).any() or (table.sum(axis=0) == 0).any() or (table.sum(axis=1) == 0).any():
            continue
        _, p, _, _ = stats.chi2_contingency(table, correction=False)
        lift = both * n_postings / (na * nb)
        denom = math.sqrt(na * nb * (n_postings - na) * (n_postings - nb))
        phi = (both * n_postings - na * nb) / denom if denom else 0.0
        rows.append({"skill_a": a, "skill_b": b, "n_both": both, "lift": lift, "phi": phi, "p": p})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["q"] = bh_qvalues(t["p"].to_numpy())
    return t[(t["q"] < config.FDR_ALPHA) & (t["lift"] > 1)].sort_values("phi", ascending=False)


# ------------------------------------------------------------------ levels, roles, cities
def level_gap(long: pd.DataFrame, posts: pd.DataFrame) -> pd.DataFrame:
    n_e, n_s = (posts["seniority"] == "entry").sum(), (posts["seniority"] == "senior").sum()
    if n_e < config.MIN_SKILL_POSTINGS or n_s < config.MIN_SKILL_POSTINGS:
        return pd.DataFrame()
    e = long[long["seniority"] == "entry"].groupby("skill").size().rename("n_entry")
    s = long[long["seniority"] == "senior"].groupby("skill").size().rename("n_senior")
    t = pd.concat([e, s], axis=1).fillna(0).reset_index()
    t["entry_share"], t["senior_share"] = t["n_entry"] / n_e, t["n_senior"] / n_s
    t["ratio"] = (t["entry_share"] + .005) / (t["senior_share"] + .005)
    return t[(t["n_entry"] >= 10) | (t["n_senior"] >= 10)].sort_values("entry_share", ascending=False)


def role_profiles(engine, k=12) -> dict:
    t = q(engine, "role_skill_ranking", min_role_postings=config.MIN_SKILL_POSTINGS)
    out = {}
    for role, g in t[t["rnk"] <= k].groupby("role_family"):
        out[role] = [{"skill": r.skill, "share": round(float(r.share), 4)} for r in g.sort_values(["rnk", "skill"]).itertuples()]
    sizes = t.drop_duplicates("role_family").set_index("role_family")["n_role"].to_dict()
    return {"skills": out, "sizes": {k_: int(v) for k_, v in sizes.items()}}


def city_table(long: pd.DataFrame, posts: pd.DataFrame, top=10) -> list[dict]:
    """Skills over-represented in a city versus the national mix: location quotient, kept only if a
    one-sided binomial test survives a false discovery rate correction across every city x skill tested."""
    real = posts[~posts["city"].isin(["Remote", "Unspecified", "Other"])]
    counts = real["city"].value_counts()
    nat_n = long.groupby("skill").size()
    nat = (nat_n / len(posts))[nat_n >= config.MIN_SKILL_POSTINGS]
    tests = []
    for city in counts[counts >= 50].head(top).index:
        n_city = int(counts[city])
        c = long[long["city"] == city].groupby("skill").size()
        for skill, k in c[c >= 15].items():
            if skill in nat.index:
                p0 = float(nat[skill])
                tests.append((city, skill, int(k), n_city, p0, stats.binomtest(int(k), n_city, p0, alternative="greater").pvalue))
    qv = bh_qvalues(np.array([t[5] for t in tests])) if tests else []
    found = {}
    for t, qq in zip(tests, qv):
        lq = t[2] / t[3] / t[4]
        if qq < config.FDR_ALPHA and lq > 1.25:
            found.setdefault(t[0], []).append({"skill": t[1], "lq": round(lq, 2), "n": t[2]})
    return [{"city": city, "postings": int(counts[city]), "share": round(int(counts[city]) / len(posts), 3),
             "distinctive": sorted(found.get(city, []), key=lambda d: -d["lq"])[:3]}
            for city in counts[counts >= 50].head(top).index]


# ------------------------------------------------------------------ salary
def salary_table(long: pd.DataFrame, posts: pd.DataFrame, seed=11) -> dict:
    sal = posts.dropna(subset=["salary_lpa"]).copy()
    cover = float(posts["salary_lpa"].notna().mean()) if len(posts) else 0.0
    if len(sal) < 2 * config.MIN_SKILL_POSTINGS:
        return {"coverage": round(cover, 3), "n": int(len(sal)), "rows": []}
    grp = sal.groupby(["role_family", "seniority"])["salary_lpa"]
    sal["base"] = grp.transform("median")
    sal = sal[grp.transform("size") >= 5]
    sal["ratio"] = sal["salary_lpa"] / sal["base"]
    m = long[["posting_id", "skill"]].merge(sal[["posting_id", "salary_lpa", "ratio"]], on="posting_id")
    rng = np.random.default_rng(seed)
    rows = []
    for skill, g in m.groupby("skill"):
        if len(g) < config.MIN_SKILL_POSTINGS:
            continue
        r = g["ratio"].to_numpy()
        boots = np.median(rng.choice(r, size=(300, len(r)), replace=True), axis=1)
        lo, hi = np.percentile(boots, [5, 95])
        rows.append({"skill": skill, "n": int(len(g)), "median_lpa": round(float(g["salary_lpa"].median()), 1),
                     "premium": round(float(np.median(r)) - 1, 3), "lo": round(float(lo) - 1, 3), "hi": round(float(hi) - 1, 3)})
    rows.sort(key=lambda x: x["premium"], reverse=True)
    return {"coverage": round(cover, 3), "n": int(len(sal)), "rows": rows}


# ------------------------------------------------------------------ opportunity score
def opportunity(long, posts, levels, trends) -> pd.DataFrame:
    base = long.groupby("skill").size().rename("n").to_frame()
    base = base[base["n"] >= config.MIN_SKILL_POSTINGS]
    if base.empty:
        return pd.DataFrame()
    base["overall_share"] = base["n"] / len(posts)
    if not levels.empty:
        base = base.join(levels.set_index("skill")[["entry_share"]]).fillna({"entry_share": 0})
    else:
        base["entry_share"] = base["overall_share"]
    slope = trends.set_index("skill")["slope_pp_per_week"] if not trends.empty else pd.Series(dtype=float)
    base["slope"] = slope.reindex(base.index).fillna(0.0)
    roles = posts["role_family"].value_counts()
    roles = roles[roles >= config.MIN_SKILL_POSTINGS].index
    per_role = (long[long["role_family"].isin(roles)].groupby(["skill", "role_family"]).size().unstack(fill_value=0))
    role_n = posts["role_family"].value_counts()[per_role.columns]
    base["breadth"] = ((per_role / role_n) >= .10).sum(axis=1).reindex(base.index).fillna(0)
    rk = lambda s: s.rank(pct=True)
    base["score"] = 100 * (0.5 * rk(base["entry_share"]) + 0.25 * rk(base["slope"]) + 0.25 * rk(base["breadth"]))
    return base.sort_values("score", ascending=False).reset_index().rename(columns={"index": "skill"})


# ------------------------------------------------------------------ skill gap planner
def planner_data(long: pd.DataFrame, posts: pd.DataFrame) -> dict:
    """Compact dataset for the in-browser planner: [role_idx, level_idx, [skill_idx, ...]] per posting."""
    counts = long.groupby("skill").size()
    names = list(counts[counts >= 10].sort_values(ascending=False).index)
    sidx = {n: i for i, n in enumerate(names)}
    roles = [r for r in posts["role_family"].value_counts().index if r != "Other"]
    ridx = {r: i for i, r in enumerate(roles)}
    lidx = {l: i for i, l in enumerate(LEVELS)}
    meta = posts.set_index("posting_id")[["role_family", "seniority"]]
    rows = []
    for pid, g in long[long["skill"].isin(sidx)].groupby("posting_id"):
        if len(g) < 2:
            continue
        role, lvl = meta.loc[pid, "role_family"], meta.loc[pid, "seniority"]
        if role in ridx:
            rows.append([ridx[role], lidx[lvl], sorted(sidx[s] for s in g["skill"])])
    return {"skills": names, "roles": roles, "levels": LEVELS, "postings": rows}


def coverage(rows, have: set[int], thr=None) -> float:
    thr = thr or config.COVERAGE_THRESHOLD
    if not rows:
        return 0.0
    ok = sum(1 for r in rows if sum(1 for s in r[2] if s in have) / len(r[2]) >= thr)
    return ok / len(rows)


def plan_gap(data: dict, have_names, role=None, level="entry", k=5) -> dict:
    """Greedy set cover: which missing skill unlocks the most additional postings next?"""
    idx = {n: i for i, n in enumerate(data["skills"])}
    have = {idx[n] for n in have_names if n in idx}
    ridx = data["roles"].index(role) if role else None
    lidx = data["levels"].index(level) if level else None
    rows = [r for r in data["postings"] if (ridx is None or r[0] == ridx) and (lidx is None or r[1] == lidx)]
    start = coverage(rows, have)
    steps, cur = [], set(have)
    for _ in range(k):
        base = coverage(rows, cur)
        best = max(((coverage(rows, cur | {i}), i) for i in range(len(data["skills"])) if i not in cur),
                   default=None)
        if not best or best[0] <= base:
            break
        cur.add(best[1])
        steps.append({"skill": data["skills"][best[1]], "coverage": best[0], "gain": best[0] - base})
    return {"n_postings": len(rows), "start": start, "steps": steps}


# ------------------------------------------------------------------ everything
def _records(df: pd.DataFrame, nd=3) -> list[dict]:
    if df is None or df.empty:
        return []
    df = df.copy()
    for c in df.select_dtypes("float").columns:
        df[c] = df[c].round(nd)
    return df.replace({np.nan: None}).to_dict("records")


def compute_all(engine) -> dict:
    posts, long = load(engine)
    if posts.empty:
        raise SystemExit("No postings yet. Run: skillradar ingest ... then skillradar build")
    wk = q(engine, "weekly_skill_share")
    ov = overview(posts, long)
    tr, tr_note = trend_table(wk)
    lv = level_gap(long, posts)
    pairs = pair_table(engine, long, len(posts))
    opp = opportunity(long, posts, lv, tr)
    top = top_skills(long, len(posts), 25)
    series_skills = list(top_skills(long, len(posts), 14)["skill"])
    rising = list(tr[tr["direction"] == "rising"].head(3)["skill"]) if not tr.empty else []
    falling = list(tr[tr["direction"] == "falling"].tail(2)["skill"]) if not tr.empty else []
    series_skills = list(dict.fromkeys(series_skills + rising + falling))
    planner = planner_data(long, posts)
    default_role = "Data Analyst" if "Data Analyst" in planner["roles"] else None
    return {
        "overview": ov,
        "top_skills": _records(top, 4),
        "trends": _records(tr, 4), "trend_note": tr_note,
        "series": trend_series(wk, series_skills),
        "pairs": _records(pairs.head(15), 3),
        "levels": _records(lv.head(40), 4),
        "opportunity": _records(opp.head(15), 3),
        "opportunity_basis": "entry" if not lv.empty else "all",
        "roles": role_profiles(engine),
        "cities": city_table(long, posts),
        "salary": salary_table(long, posts),
        "planner": planner,
        "profile": config.PROFILE_SKILLS,
        "profile_plan": plan_gap(planner, config.PROFILE_SKILLS, role=None, level="entry"),
    }