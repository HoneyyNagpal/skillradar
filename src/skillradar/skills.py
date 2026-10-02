"""Skill dictionary and extractor.

Each skill has a canonical name, a category and plain-text aliases. Matching is case-insensitive with
custom boundaries so that "Java" never fires inside "JavaScript", "SQL" never fires inside "NoSQL",
and "C++" / "C#" / ".NET" / "Node.js" work. Ambiguous words (Go, R) are only matched through
unambiguous aliases ("golang", "R programming") to protect precision.
"""
import re


def _s(category, *aliases):
    return {"category": category, "aliases": list(aliases)}


SKILLS = {
    # languages
    "Python": _s("Language", "python", "python3"),
    "Java": _s("Language", "java", "core java", "java 8", "java 11", "java 17"),
    "JavaScript": _s("Language", "javascript", "js", "es6"),
    "TypeScript": _s("Language", "typescript"),
    "C++": _s("Language", "c++"),
    "C#": _s("Language", "c#"),
    "Go": _s("Language", "golang", "go lang"),
    "Rust": _s("Language", "rust"),
    "Kotlin": _s("Language", "kotlin"),
    "Swift": _s("Language", "swiftui", "swift programming", "swift language"),
    "PHP": _s("Language", "php"),
    "Ruby": _s("Language", "ruby", "ruby on rails"),
    "R": _s("Language", "r programming", "r language", "rstudio"),
    "Scala": _s("Language", "scala"),
    "SQL": _s("Language", "sql", "t-sql", "pl/sql", "plsql"),
    "Bash": _s("Language", "bash", "shell scripting", "shell script"),
    # web
    "React": _s("Web", "react", "reactjs", "react.js"),
    "Angular": _s("Web", "angular", "angularjs"),
    "Vue.js": _s("Web", "vue", "vue.js", "vuejs"),
    "Next.js": _s("Web", "next.js", "nextjs"),
    "Node.js": _s("Web", "node.js", "nodejs", "node js"),
    "Express.js": _s("Web", "express.js", "expressjs"),
    "HTML": _s("Web", "html", "html5"),
    "CSS": _s("Web", "css", "css3"),
    "Tailwind CSS": _s("Web", "tailwind", "tailwindcss"),
    "jQuery": _s("Web", "jquery"),
    "Django": _s("Web", "django"),
    "Flask": _s("Web", "flask"),
    "FastAPI": _s("Web", "fastapi", "fast api"),
    "Spring Boot": _s("Web", "spring boot", "springboot", "spring framework"),
    ".NET": _s("Web", ".net", "dotnet", "asp.net"),
    "GraphQL": _s("Web", "graphql"),
    "REST APIs": _s("Web", "rest api", "rest apis", "restful", "restful apis"),
    "Microservices": _s("Web", "microservices", "microservice"),
    # data
    "Pandas": _s("Data", "pandas"),
    "NumPy": _s("Data", "numpy"),
    "Excel": _s("Data", "excel", "ms excel", "advanced excel"),
    "Power BI": _s("Data", "power bi", "powerbi"),
    "Tableau": _s("Data", "tableau"),
    "Looker": _s("Data", "looker", "looker studio"),
    "Statistics": _s("Data", "statistics", "statistical analysis", "statistical modeling"),
    "A/B Testing": _s("Data", "a/b testing", "ab testing", "a/b tests", "experimentation"),
    "Data Visualization": _s("Data", "data visualization", "data visualisation", "dashboards"),
    "ETL": _s("Data", "etl", "elt", "data pipelines", "data pipeline"),
    "Airflow": _s("Data", "airflow"),
    "dbt": _s("Data", "dbt"),
    "Spark": _s("Data", "pyspark", "apache spark", "spark sql", "spark streaming"),
    "Kafka": _s("Data", "kafka"),
    "Hadoop": _s("Data", "hadoop", "hive"),
    "Snowflake": _s("Data", "snowflake"),
    "BigQuery": _s("Data", "bigquery"),
    "Redshift": _s("Data", "redshift"),
    "Data Warehousing": _s("Data", "data warehouse", "data warehousing", "data modeling", "data modelling"),
    # databases
    "PostgreSQL": _s("Database", "postgresql", "postgres"),
    "MySQL": _s("Database", "mysql"),
    "MongoDB": _s("Database", "mongodb", "mongo db"),
    "Redis": _s("Database", "redis"),
    "Elasticsearch": _s("Database", "elasticsearch", "elastic search"),
    "Oracle": _s("Database", "oracle db", "oracle database", "oracle sql"),
    "SQL Server": _s("Database", "sql server", "mssql"),
    "NoSQL": _s("Database", "nosql"),
    # ai / ml
    "Machine Learning": _s("AI/ML", "machine learning", "ml"),
    "Deep Learning": _s("AI/ML", "deep learning"),
    "NLP": _s("AI/ML", "nlp", "natural language processing"),
    "Computer Vision": _s("AI/ML", "computer vision", "opencv"),
    "TensorFlow": _s("AI/ML", "tensorflow", "keras"),
    "PyTorch": _s("AI/ML", "pytorch"),
    "scikit-learn": _s("AI/ML", "scikit-learn", "sklearn", "scikit learn"),
    "LLMs": _s("AI/ML", "llm", "llms", "large language model", "large language models"),
    "Generative AI": _s("AI/ML", "generative ai", "genai", "gen ai"),
    "LangChain": _s("AI/ML", "langchain", "langgraph"),
    "RAG": _s("AI/ML", "rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "Hugging Face": _s("AI/ML", "hugging face", "huggingface"),
    "Prompt Engineering": _s("AI/ML", "prompt engineering"),
    "Vector Databases": _s("AI/ML", "vector database", "vector databases", "pinecone", "faiss", "chromadb"),
    "MLOps": _s("AI/ML", "mlops", "mlflow"),
    # cloud / devops
    "AWS": _s("Cloud/DevOps", "aws", "amazon web services"),
    "Azure": _s("Cloud/DevOps", "azure"),
    "GCP": _s("Cloud/DevOps", "gcp", "google cloud"),
    "Docker": _s("Cloud/DevOps", "docker"),
    "Kubernetes": _s("Cloud/DevOps", "kubernetes", "k8s"),
    "Terraform": _s("Cloud/DevOps", "terraform"),
    "CI/CD": _s("Cloud/DevOps", "ci/cd", "cicd", "continuous integration", "github actions"),
    "Jenkins": _s("Cloud/DevOps", "jenkins"),
    "Git": _s("Cloud/DevOps", "git", "github", "gitlab"),
    "Linux": _s("Cloud/DevOps", "linux", "unix"),
    # testing / security / practice
    "Selenium": _s("Testing", "selenium"),
    "Postman": _s("Testing", "postman"),
    "JUnit": _s("Testing", "junit", "testng"),
    "Cybersecurity": _s("Security", "cybersecurity", "cyber security", "infosec", "siem"),
    "Agile": _s("Practice", "agile", "scrum"),
}

_BEFORE = r"(?<![A-Za-z0-9+#.])"
_AFTER = r"(?![A-Za-z0-9+#])"


def _compile(aliases):
    parts = sorted((re.escape(a) for a in aliases), key=len, reverse=True)
    return re.compile(_BEFORE + "(?:" + "|".join(parts) + ")" + _AFTER, re.IGNORECASE)


# Canonical names that are ordinary English words: only their explicit aliases may match.
_NO_SELF_MATCH = {"Go", "R", "Swift", "Spark"}
# Skills named after ordinary words ("react quickly", "excel in a team") match only in their proper
# capitalisation, which is how job descriptions write the technology.
_CASE_SENSITIVE = {
    "React": ["React", "ReactJS", "React.js", "reactjs", "react.js"],
    "Excel": ["Excel", "MS Excel", "MS-Excel", "Advanced Excel", "Microsoft Excel"],
    "Rust": ["Rust"], "Flask": ["Flask"], "Ruby": ["Ruby", "Ruby on Rails"], "Scala": ["Scala"],
    "Snowflake": ["Snowflake"], "Angular": ["Angular", "AngularJS"],
}


def _compile_cs(aliases):
    parts = sorted((re.escape(a) for a in aliases), key=len, reverse=True)
    return re.compile(_BEFORE + "(?:" + "|".join(parts) + ")" + _AFTER)


_PATTERNS = {
    name: (_compile_cs(_CASE_SENSITIVE[name]) if name in _CASE_SENSITIVE
           else _compile(([] if name in _NO_SELF_MATCH else [name]) + meta["aliases"]))
    for name, meta in SKILLS.items()
}
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean_text(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text or "")).strip()


def extract_skills(text: str) -> set[str]:
    text = clean_text(text)
    return {name for name, pat in _PATTERNS.items() if pat.search(text)}


def display_forms(skill: str) -> list[str]:
    """Surface forms a job post might use for a skill (used by the demo generator)."""
    if skill in _CASE_SENSITIVE:
        return _CASE_SENSITIVE[skill]
    aliases = SKILLS[skill]["aliases"]
    return aliases if skill in _NO_SELF_MATCH else [skill] + aliases
