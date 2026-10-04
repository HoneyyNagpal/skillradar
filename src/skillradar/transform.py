"""Raw -> clean. Normalisation, classification, deduplication and skill tagging.

Design notes
  * Trends use `first_seen_week` (the week *we* first saw a posting), not the posting's own date.
    Using posted_date would make old weeks look thin, because only still-open postings survive in an API.
  * A posting is one real-world job: identical title + company + city across weeks counts once.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import insert, select, update

from .db import posting_skills, postings, raw_postings, skills
from .skills import clean_text, extract_skills
from .sources import adapt

# ---------------------------------------------------------------- cities
_CITY_ALIASES = {
    "Bengaluru": ["bengaluru", "bangalore", "bengaluru rural", "bangalore urban"],
    "Hyderabad": ["hyderabad", "secunderabad"],
    "Pune": ["pune", "pimpri chinchwad", "pimpri-chinchwad"],
    "Mumbai": ["mumbai", "navi mumbai", "thane"],
    "Delhi NCR": ["delhi", "new delhi", "gurgaon", "gurugram", "noida", "greater noida", "ghaziabad", "faridabad"],
    "Chennai": ["chennai"],
    "Kolkata": ["kolkata", "calcutta"],
    "Ahmedabad": ["ahmedabad"],
    "Indore": ["indore"],
    "Jaipur": ["jaipur"],
    "Chandigarh": ["chandigarh", "mohali", "panchkula"],
    "Kochi": ["kochi", "cochin", "ernakulam"],
    "Coimbatore": ["coimbatore"],
    "Thiruvananthapuram": ["thiruvananthapuram", "trivandrum"],
    "Bhubaneswar": ["bhubaneswar"],
    "Nagpur": ["nagpur"],
    "Lucknow": ["lucknow"],
}
_CITY_LOOKUP = {alias: canon for canon, aliases in _CITY_ALIASES.items() for alias in aliases}


def normalize_city(raw: str | None, title: str = "") -> str:
    text = (raw or "").strip().lower()
    if "remote" in text or "work from home" in text or "remote" in title.lower():
        return "Remote"
    if not text or text in {"india", "in"}:
        return "Unspecified"
    for part in re.split(r"[,/|]", text):
        part = part.strip()
        if part in _CITY_LOOKUP:
            return _CITY_LOOKUP[part]
    return "Other"


# ---------------------------------------------------------------- role family
_ROLE_RULES = [
    ("Full Stack", r"full[\s-]?stack|\bmern\b|\bmean stack\b"),
    ("Data Analyst", r"data analyst|business analyst|bi (developer|analyst|engineer)|business intelligence|analytics (engineer|analyst|associate)|reporting analyst"),
    ("Data Scientist", r"data scien"),
    ("ML/AI Engineer", r"machine learning|\bml\b|\bai\b|artificial intelligence|\bnlp\b|gen ?ai|\bllm\b|deep learning|computer vision"),
    ("Data Engineer", r"data engineer|\betl\b|big data|dataops|data platform"),
    ("DevOps/Cloud", r"devops|\bsre\b|site reliability|cloud (engineer|architect)|platform engineer|infrastructure"),
    ("QA/Test", r"\bqa\b|quality assurance|test engineer|\bsdet\b|automation test|tester|testing"),
    ("Mobile", r"android|\bios\b|mobile|flutter|react native"),
    ("Security", r"security|cyber|soc analyst|infosec"),
    ("Frontend", r"front[\s-]?end|\bui\b (developer|engineer)|react (developer|engineer)|angular (developer|engineer)|vue (developer|engineer)"),
    ("Backend", r"back[\s-]?end|(java|python|node|\.net|php|golang|go|spring|django) (developer|engineer)|api (developer|engineer)"),
    ("Software Engineer", r"software (engineer|developer)|\bsde\b|programmer|developer|engineer"),
]
_ROLE_RULES = [(name, re.compile(rx, re.I)) for name, rx in _ROLE_RULES]


def classify_role(title: str) -> str:
    for name, rx in _ROLE_RULES:
        if rx.search(title or ""):
            return name
    return "Other"


# ---------------------------------------------------------------- seniority
_SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|head|director|vp)\b", re.I)
_ENTRY_TITLE = re.compile(r"\b(intern|internship|trainee|fresher|freshers|graduate|junior|jr\.?|entry[\s-]level)\b", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|\s*(?:-|–|to)\s*\d{1,2})?\s*(?:years?|yrs?)\b", re.I)
_EXP_CONTEXT = re.compile(r"experience|exp\b|required|minimum|min\.", re.I)


def parse_min_years(text: str) -> int | None:
    """First 'N years' mention that sits next to experience language. '0-2 years' -> 0, '3+ years' -> 3."""
    text = clean_text(text)
    for m in _YEARS.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60]
        n = int(m.group(1))
        if n <= 15 and _EXP_CONTEXT.search(window):
            return n
    return None


def classify_seniority(title: str, description: str) -> tuple[str, int | None]:
    years = parse_min_years(description)
    if _ENTRY_TITLE.search(title or ""):
        return "entry", years
    if _SENIOR_TITLE.search(title or ""):
        return "senior", years
    if years is not None:
        return ("entry" if years <= 1 else "mid" if years <= 5 else "senior"), years
    if re.search(r"\bfreshers?\b|\bentry[\s-]level\b", description or "", re.I):
        return "entry", None
    return "unspecified", None


# ---------------------------------------------------------------- misc helpers
def week_start(d: date | datetime) -> date:
    d = d.date() if isinstance(d, datetime) else d
    return d - timedelta(days=d.weekday())


_NORM = re.compile(r"[^a-z0-9]+")


def dedupe_key(title: str, company: str | None, city: str) -> str:
    raw = "|".join([_NORM.sub(" ", (title or "").lower()).strip(),
                    _NORM.sub(" ", (company or "").lower()).strip(), city.lower()])
    return hashlib.sha1(raw.encode()).hexdigest()


def salary_lpa(smin, smax) -> float | None:
    """Annual INR -> lakhs per annum. Out-of-range values are treated as data errors, not outliers."""
    vals = [float(v) for v in (smin, smax) if v not in (None, "", 0, "0")]
    if not vals:
        return None
    lpa = sum(vals) / len(vals) / 1e5
    return round(lpa, 2) if 1.5 <= lpa <= 150 else None


# ---------------------------------------------------------------- the build step
def build(engine, chunk=5000) -> dict:
    stats = {"raw_rows": 0, "new_postings": 0, "reseen": 0, "skipped": 0}
    with engine.begin() as conn:
        skill_ids = {n: i for n, i in conn.execute(select(skills.c.name, skills.c.skill_id).order_by(skills.c.skill_id)).fetchall()}
        existing = {r.dedupe_key: dict(id=r.posting_id, first=r.first_seen_week, last=r.last_seen_week, n=r.times_seen)
                    for r in conn.execute(select(postings.c.dedupe_key, postings.c.posting_id, postings.c.first_seen_week,
                                                 postings.c.last_seen_week, postings.c.times_seen))}
        while True:
            rows = conn.execute(select(raw_postings).where(raw_postings.c.processed == 0)
                                .order_by(raw_postings.c.fetched_at, raw_postings.c.id).limit(chunk)).fetchall()
            if not rows:
                break
            new_rows, new_skill_sets = [], {}
            for r in rows:
                stats["raw_rows"] += 1
                c = adapt(r.source, json.loads(r.payload))
                title = clean_text(c["title"])
                if not title:
                    stats["skipped"] += 1
                    continue
                desc = clean_text(c["description"])
                city = normalize_city(c["location"], title)
                key = dedupe_key(title, c["company"], city)
                wk = week_start(r.fetched_at)
                hit = existing.get(key)
                if hit:
                    stats["reseen"] += 1
                    if wk > hit["last"]:
                        hit["last"], hit["n"] = wk, hit["n"] + 1
                    hit["first"] = min(hit["first"], wk)
                    hit["dirty"] = True
                    continue
                seniority, years = classify_seniority(title, desc)
                new_rows.append(dict(
                    dedupe_key=key, source=r.source, title=title[:300], company=(c["company"] or None),
                    city=city, role_family=classify_role(title), seniority=seniority, min_years=years,
                    salary_lpa=salary_lpa(c["salary_min"], c["salary_max"]),
                    first_seen_week=wk, last_seen_week=wk, times_seen=1))
                new_skill_sets[key] = extract_skills(f"{title}. {desc}")
                existing[key] = dict(id=None, first=wk, last=wk, n=1)
            if new_rows:
                conn.execute(insert(postings), new_rows)
                stats["new_postings"] += len(new_rows)
                keys = list(new_skill_sets)
                ids = {}
                for i in range(0, len(keys), 500):  # keep IN lists small for portability
                    sub = keys[i:i + 500]
                    ids.update({k: pid for k, pid in conn.execute(
                        select(postings.c.dedupe_key, postings.c.posting_id).where(postings.c.dedupe_key.in_(sub)))})
                bridge = []
                for k, sset in new_skill_sets.items():
                    existing[k]["id"] = ids[k]
                    bridge += [{"posting_id": ids[k], "skill_id": skill_ids[s]} for s in sset]
                if bridge:
                    conn.execute(insert(posting_skills), bridge)
            conn.execute(update(raw_postings).where(raw_postings.c.id.in_([r.id for r in rows])).values(processed=1))
        # persist re-seen updates
        for v in existing.values():
            if v.get("dirty") and v["id"] is not None:
                conn.execute(update(postings).where(postings.c.posting_id == v["id"])
                             .values(first_seen_week=v["first"], last_seen_week=v["last"], times_seen=v["n"]))
    return stats
