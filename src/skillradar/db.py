"""Schema and connection handling. Core tables only, so it runs unchanged on SQLite and PostgreSQL.

Layers
  raw_postings    append-only, one row per fetch, original payload untouched
  postings        cleaned, deduplicated, one row per real-world posting
  skills / posting_skills   the skill dimension and its bridge table
"""
from sqlalchemy import (Column, Date, DateTime, Float, ForeignKey, Index, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, create_engine, insert, select)

from . import config
from .skills import SKILLS

metadata = MetaData()

raw_postings = Table(
    "raw_postings", metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(32), nullable=False),
    Column("fetched_at", DateTime, nullable=False),
    Column("payload", Text, nullable=False),
    Column("processed", Integer, nullable=False, default=0),
)
Index("ix_raw_processed", raw_postings.c.processed)

postings = Table(
    "postings", metadata,
    Column("posting_id", Integer, primary_key=True),
    Column("dedupe_key", String(64), nullable=False),
    Column("source", String(32), nullable=False),
    Column("title", String(300), nullable=False),
    Column("company", String(200)),
    Column("city", String(80)),
    Column("role_family", String(40), nullable=False),
    Column("seniority", String(16), nullable=False),
    Column("min_years", Integer),
    Column("salary_lpa", Float),
    Column("first_seen_week", Date, nullable=False),
    Column("last_seen_week", Date, nullable=False),
    Column("times_seen", Integer, nullable=False, default=1),
    UniqueConstraint("dedupe_key", name="uq_postings_dedupe"),
)
Index("ix_postings_week", postings.c.first_seen_week)

skills = Table(
    "skills", metadata,
    Column("skill_id", Integer, primary_key=True),
    Column("name", String(60), nullable=False, unique=True),
    Column("category", String(30), nullable=False),
)

posting_skills = Table(
    "posting_skills", metadata,
    Column("posting_id", Integer, ForeignKey("postings.posting_id"), primary_key=True),
    Column("skill_id", Integer, ForeignKey("skills.skill_id"), primary_key=True),
)
Index("ix_ps_skill", posting_skills.c.skill_id)


def get_engine(url: str | None = None):
    return create_engine(url or config.DATABASE_URL, future=True)


def init_db(engine) -> None:
    """Create tables and seed the skill dimension (idempotent)."""
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        from pathlib import Path
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    metadata.create_all(engine)
    with engine.begin() as conn:
        have = {r[0] for r in conn.execute(select(skills.c.name))}
        new = [{"name": n, "category": meta["category"]} for n, meta in SKILLS.items() if n not in have]
        if new:
            conn.execute(insert(skills), new)


def copy_raw(src_engine, dst_engine, chunk=2000, force=False) -> int:
    """Copy the append-only raw layer from one database to another (for example local SQLite to hosted
    PostgreSQL) as unprocessed rows, so the target rebuilds the clean layers itself. Snapshots cost API
    quota, so they are worth carrying over."""
    from sqlalchemy import func
    with dst_engine.connect() as d:
        existing = d.execute(select(func.count()).select_from(raw_postings)).scalar()
    if existing and not force:
        raise SystemExit(f"Target already holds {existing} raw rows. Refusing to copy twice (use --force to override).")
    n, batch = 0, []
    with src_engine.connect() as s, dst_engine.begin() as d:
        for r in s.execute(select(raw_postings).order_by(raw_postings.c.id)).mappings():
            batch.append({"source": r["source"], "fetched_at": r["fetched_at"], "payload": r["payload"], "processed": 0})
            if len(batch) >= chunk:
                d.execute(insert(raw_postings), batch)
                n, batch = n + len(batch), []
        if batch:
            d.execute(insert(raw_postings), batch)
            n += len(batch)
    return n