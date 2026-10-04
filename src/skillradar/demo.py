"""Synthetic postings so the whole pipeline can run offline.

THIS IS NOT REAL DATA. Every record is tagged source="demo" and the dashboard prints a banner while
only demo rows exist. The generator plants a few known effects (rising GenAI skills, a fading jQuery,
skill clusters per role) so the test suite can check that the analysis recovers them.
"""
import random
from datetime import datetime, timedelta

from .skills import display_forms
from .sources import store_raw
from .transform import week_start

# role -> (market weight, title templates, [(skill, probability)])
ROLES = {
    "Data Analyst": (0.17, ["Data Analyst", "Business Analyst", "BI Developer", "Analytics Associate"], [
        ("SQL", .93), ("Excel", .72), ("Power BI", .52), ("Tableau", .30), ("Python", .50), ("Statistics", .30),
        ("Pandas", .22), ("Data Visualization", .35), ("A/B Testing", .08), ("Looker", .06), ("Snowflake", .06)]),
    "Data Scientist": (0.07, ["Data Scientist", "Applied Scientist"], [
        ("Python", .95), ("Machine Learning", .85), ("SQL", .70), ("Statistics", .60), ("Pandas", .55), ("scikit-learn", .50),
        ("Deep Learning", .30), ("NLP", .25), ("A/B Testing", .15), ("TensorFlow", .20), ("PyTorch", .22)]),
    "ML/AI Engineer": (0.09, ["Machine Learning Engineer", "AI Engineer", "GenAI Engineer", "NLP Engineer"], [
        ("Python", .96), ("Machine Learning", .70), ("PyTorch", .40), ("Deep Learning", .40), ("NLP", .30), ("Docker", .35),
        ("AWS", .30), ("LLMs", .22), ("Generative AI", .18), ("LangChain", .08), ("RAG", .07), ("MLOps", .12), ("FastAPI", .15)]),
    "Data Engineer": (0.08, ["Data Engineer", "ETL Developer", "Big Data Engineer"], [
        ("SQL", .92), ("Python", .80), ("ETL", .60), ("Spark", .45), ("Airflow", .35), ("AWS", .45), ("Snowflake", .22),
        ("Kafka", .20), ("Hadoop", .12), ("Data Warehousing", .35), ("Azure", .22), ("BigQuery", .12), ("dbt", .10)]),
    "Backend": (0.17, ["Java Developer", "Python Developer", "Backend Developer", "Node.js Developer", ".NET Developer"], [
        ("Java", .35), ("Spring Boot", .28), ("Python", .30), ("Django", .10), ("FastAPI", .08), ("Node.js", .20), ("SQL", .60),
        ("REST APIs", .55), ("Microservices", .35), ("Docker", .35), ("Git", .55), ("PostgreSQL", .22), ("MySQL", .25),
        ("AWS", .30), ("Kafka", .10), ("MongoDB", .15), ("Redis", .12)]),
    "Frontend": (0.10, ["Frontend Developer", "React Developer", "Angular Developer", "UI Developer"], [
        ("JavaScript", .90), ("React", .60), ("HTML", .80), ("CSS", .80), ("TypeScript", .40), ("Angular", .22), ("Git", .55),
        ("REST APIs", .30), ("Tailwind CSS", .12), ("jQuery", .14), ("Next.js", .12)]),
    "Full Stack": (0.12, ["Full Stack Developer", "Full Stack Engineer", "MERN Stack Developer"], [
        ("JavaScript", .80), ("React", .60), ("Node.js", .50), ("SQL", .45), ("MongoDB", .35), ("REST APIs", .55), ("Git", .60),
        ("TypeScript", .35), ("Docker", .25), ("AWS", .22), ("PostgreSQL", .20), ("Python", .25), ("Express.js", .30), ("jQuery", .08)]),
    "DevOps/Cloud": (0.08, ["DevOps Engineer", "Cloud Engineer", "Site Reliability Engineer"], [
        ("AWS", .70), ("Docker", .70), ("Kubernetes", .55), ("CI/CD", .60), ("Linux", .65), ("Terraform", .35), ("Jenkins", .30),
        ("Git", .55), ("Bash", .35), ("Python", .35), ("Azure", .25), ("GCP", .12)]),
    "QA/Test": (0.06, ["QA Engineer", "Test Automation Engineer", "SDET"], [
        ("Selenium", .60), ("Java", .40), ("SQL", .40), ("Postman", .35), ("REST APIs", .35), ("Agile", .45), ("Python", .30), ("CI/CD", .20), ("JUnit", .20)]),
    "Mobile": (0.04, ["Android Developer", "iOS Developer", "Mobile App Developer"], [
        ("Kotlin", .40), ("Java", .30), ("Swift", .30), ("REST APIs", .55), ("Git", .50), ("Agile", .20)]),
    "Security": (0.02, ["Security Analyst", "Cybersecurity Engineer"], [
        ("Cybersecurity", .70), ("Linux", .45), ("Python", .30), ("AWS", .25)]),
}

# planted multiplicative drift per week on a skill's probability
PLANTED_TREND = {"LangChain": +0.30, "RAG": +0.28, "Generative AI": +0.14, "FastAPI": +0.08,
                 "LLMs": +0.12, "jQuery": -0.075, "Hadoop": -0.07}

CITIES = [("Bengaluru, Karnataka", .17), ("Bangalore", .08), ("Hyderabad, Telangana", .13), ("Pune, Maharashtra", .12),
          ("Mumbai, Maharashtra", .07), ("Navi Mumbai", .02), ("Gurgaon, Haryana", .05), ("Noida, Uttar Pradesh", .05),
          ("New Delhi", .04), ("Chennai, Tamil Nadu", .08), ("Kolkata, West Bengal", .02), ("Ahmedabad, Gujarat", .02),
          ("Indore, Madhya Pradesh", .015), ("Jaipur, Rajasthan", .015), ("Coimbatore", .01), ("Remote", .05), ("India", .02)]

LEVELS = [("entry", .24), ("mid", .46), ("senior", .30)]
LEVEL_PAY = {"entry": 4.5, "mid": 10.0, "senior": 21.0}
ROLE_PAY = {"ML/AI Engineer": 1.28, "Data Scientist": 1.15, "Data Engineer": 1.12, "DevOps/Cloud": 1.1,
            "Data Analyst": 0.85, "QA/Test": 0.8, "Frontend": 0.95, "Security": 1.05}
FLUFF = ["We are a go-getter team with a strong R&D culture.", "Plan the Go-live carefully with stakeholders.",
         "You will react quickly to production incidents.", "Hybrid work, great learning environment.",
         "Our spark of curiosity drives the product forward.", "People who excel in teamwork thrive here.", "Fast growing product company in the India market."]


def _pick(rng, pairs):
    r, acc = rng.random(), 0.0
    for item, w in pairs:
        acc += w
        if r <= acc:
            return item
    return pairs[-1][0]


def _prob(skill, p, week_idx):
    drift = PLANTED_TREND.get(skill, 0.0)
    return min(0.95, max(0.01, p * (1 + drift * week_idx)))


def _years_text(level, rng):
    if level == "entry":
        return rng.choice(["Freshers welcome. 0-2 years of experience.", "0-1 years experience required.", "Entry level role, no experience required."])
    if level == "mid":
        return rng.choice(["3-5 years of experience required.", "Minimum 2 years experience.", "3+ years experience in a similar role."])
    return rng.choice(["8+ years of experience required.", "Minimum 6 years experience leading teams.", "7-10 years experience."])


def _make_job(rng, week_idx, serial):
    role = _pick(rng, [(r, v[0]) for r, v in ROLES.items()])
    _, titles, skill_probs = ROLES[role]
    level = _pick(rng, LEVELS)
    title = rng.choice(titles)
    if level == "senior" and rng.random() < .55:
        title = f"Senior {title}"
    elif level == "entry" and rng.random() < .35:
        title = rng.choice([f"{title} Trainee", f"Junior {title}", f"{title} Intern"])
    chosen = [s for s, p in skill_probs if rng.random() < _prob(s, p, week_idx)]
    rng.shuffle(chosen)
    must, nice = chosen[:max(1, int(len(chosen) * .7))], chosen[max(1, int(len(chosen) * .7)):]
    sent = [f"Hands-on experience with {', '.join(rng.choice(display_forms(s)) for s in must)}."]
    if nice:
        sent.append(f"Good to have: {', '.join(rng.choice(display_forms(s)) for s in nice)}.")
    sent += [_years_text(level, rng)] + rng.sample(FLUFF, 2)
    rng.shuffle(sent)
    company = f"Demo Company {rng.randint(1, 260):03d}"
    city = _pick(rng, CITIES)
    job = {"external_id": f"demo-{serial}", "title": title, "company": company, "location": city,
           "description": " ".join(sent), "salary_min": None, "salary_max": None}
    if rng.random() < .35:
        lpa = LEVEL_PAY[level] * ROLE_PAY.get(role, 1.0) * rng.lognormvariate(0, .22)
        job["salary_min"], job["salary_max"] = round(lpa * .9 * 1e5), round(lpa * 1.1 * 1e5)
    return job


def generate(engine, weeks=12, per_week=600, seed=7, end=None) -> int:
    """Insert `weeks` weeks of synthetic fetches ending at `end` (default: this week). Returns raw rows."""
    rng = random.Random(seed)
    end_week = week_start(end or datetime.now())
    live, serial, total = [], 0, 0
    for w in range(weeks):
        monday = datetime.combine(end_week - timedelta(weeks=weeks - 1 - w), datetime.min.time())
        batch = []
        for job in live:                                   # reposts: same job seen again in later weeks
            if rng.random() < .30:
                batch.append(dict(job))
        for _ in range(per_week):
            serial += 1
            job = _make_job(rng, w, serial)
            batch.append(job)
            if rng.random() < .25:
                live.append(job)
        live = [j for j in live if rng.random() < .75]       # postings expire
        for job in batch:
            job["posted_date"] = (monday - timedelta(days=rng.randint(0, 20))).isoformat()
        total += store_raw(engine, "demo", batch, fetched_at=monday + timedelta(hours=rng.randint(1, 100)))
    return total
