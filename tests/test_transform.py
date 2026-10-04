from skillradar import transform as t


def test_city_normalisation():
    assert t.normalize_city("Gurgaon, Haryana") == "Delhi NCR"
    assert t.normalize_city("Bangalore") == "Bengaluru"
    assert t.normalize_city("India") == "Unspecified"
    assert t.normalize_city("Pune, Maharashtra") == "Pune"
    assert t.normalize_city("Anywhere", "Remote Python Developer") == "Remote"
    assert t.normalize_city("Somewhere small") == "Other"


def test_role_family():
    cases = {"Senior Data Analyst": "Data Analyst", "MERN Stack Developer": "Full Stack",
             "Machine Learning Engineer": "ML/AI Engineer", "Python Developer": "Backend",
             "SDET": "QA/Test", "Site Reliability Engineer": "DevOps/Cloud", "Android Developer": "Mobile",
             "React Developer": "Frontend", "ETL Developer": "Data Engineer"}
    for title, role in cases.items():
        assert t.classify_role(title) == role, title


def test_min_years():
    assert t.parse_min_years("0-2 years of experience") == 0
    assert t.parse_min_years("Minimum 3+ years experience") == 3
    assert t.parse_min_years("A company with 25 years in business") is None


def test_seniority():
    assert t.classify_seniority("Data Analyst Intern", "")[0] == "entry"
    assert t.classify_seniority("Senior Backend Developer", "0-1 years experience")[0] == "senior"
    assert t.classify_seniority("Software Engineer", "3-5 years of experience required")[0] == "mid"
    assert t.classify_seniority("Software Engineer", "Freshers welcome")[0] == "entry"
    assert t.classify_seniority("Software Engineer", "Build things")[0] == "unspecified"


def test_salary_bounds():
    assert t.salary_lpa(600000, 800000) == 7.0
    assert t.salary_lpa(None, None) is None
    assert t.salary_lpa(25000, 30000) is None          # monthly figure mistaken for annual
    assert t.salary_lpa(9e8, 9e8) is None


def test_dedupe_key_ignores_case_and_punctuation():
    assert t.dedupe_key("Data  Analyst!", "Acme Ltd.", "Pune") == t.dedupe_key("data analyst", "ACME LTD", "pune")
    assert t.week_start(__import__("datetime").date(2026, 10, 1)).isoformat() == "2026-09-28"
