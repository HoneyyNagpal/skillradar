from skillradar.skills import extract_skills as ex


def test_boundaries_do_not_leak():
    assert ex("JavaScript and NoSQL") == {"JavaScript", "NoSQL"}          # not Java, not SQL
    assert ex("MySQL, PostgreSQL") == {"MySQL", "PostgreSQL"}
    assert "SQL" in ex("PL/SQL and T-SQL")


def test_symbols_and_dots():
    assert ex("C++, C# and .NET with Node.js") == {"C++", "C#", ".NET", "Node.js"}


def test_aliases_normalise():
    assert ex("k8s, postgres, nodejs, GenAI") == {"Kubernetes", "PostgreSQL", "Node.js", "Generative AI"}


def test_ordinary_words_are_not_skills():
    text = "We are go-getters in R&D. You will react quickly and excel in teams. Go-live is in spring. Swift response, spark of interest."
    assert ex(text) == set()


def test_ordinary_words_still_match_when_used_as_tech():
    assert ex("Golang, R programming, PySpark, React, Excel") == {"Go", "R", "Spark", "React", "Excel"}


def test_html_is_stripped():
    assert ex("<li>Python</li><br/>Docker") == {"Python", "Docker"}
