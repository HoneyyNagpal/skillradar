"""Central configuration. Everything overridable through environment variables or .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql"
DOCS_DIR = ROOT / "docs"
REPORTS_DIR = ROOT / "reports"

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'data' / 'skillradar.db'}"

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRY = os.getenv("ADZUNA_COUNTRY", "in")

# JSearch (OpenWeb Ninja). Free tier is a hard 200 requests per month, so runs are capped.
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY", "")
JSEARCH_MAX_REQUESTS = int(os.getenv("JSEARCH_MAX_REQUESTS", "38"))   # 19 terms x 2 pages

# One query per role family keeps coverage balanced. Edit freely.
SEARCH_TERMS = [
    # core roles
    "data analyst", "business analyst", "data scientist", "data engineer",
    "machine learning engineer", "full stack developer", "backend developer",
    "frontend developer", "python developer", "java developer", "devops engineer",
    # entry-level queries: Adzuna snippets rarely show "0-2 years", so ask for it by title
    "fresher", "trainee", "graduate engineer trainee", "junior software developer",
    "entry level data analyst", "data analyst intern", "software developer intern",
    "associate software engineer",
]

PROFILE_SKILLS = [
    s.strip()
    for s in os.getenv(
        "PROFILE_SKILLS",
        "Python,SQL,React,Node.js,FastAPI,PostgreSQL,Docker,Git,Java,Spring Boot,LangChain",
    ).split(",")
    if s.strip()
]

# Statistical guardrails. Nothing below these thresholds is reported.
MIN_PAIR_SUPPORT = 25        # postings containing both skills
MIN_SKILL_POSTINGS = 30      # postings mentioning a skill before it gets a trend or salary row
MIN_WEEKS_FOR_TREND = 6      # a trend line from fewer weeks is noise
FDR_ALPHA = 0.05             # Benjamini-Hochberg false discovery rate
COVERAGE_THRESHOLD = 0.6     # a candidate "fits" a posting if they hold this share of its skills