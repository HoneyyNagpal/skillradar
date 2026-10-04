import pytest

from skillradar import analysis, db, demo, transform


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    eng = db.get_engine(f"sqlite:///{path}")
    db.init_db(eng)
    demo.generate(eng)
    eng.build_stats = transform.build(eng)
    return eng


@pytest.fixture(scope="session")
def frames(engine):
    return analysis.load(engine)
