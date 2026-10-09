"""Creates all tables and seeds the HIPAA/DPDP compliance pack config from
data_pipeline/config/*.yaml. Run once before starting either service:

`python scripts/init_db.py` from the repo root.

Safe to re-run: seeding is idempotent and migrate_schema() repairs any stale
table structures left over from earlier schema versions without touching data.
"""
import sys
from pathlib import Path

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.db import Base, engine, SessionLocal
from shared.models import CompliancePackConfig, ToolThresholdConfig

CONFIG_DIR = Path(__file__).resolve().parents[1] / "data_pipeline" / "config"


def migrate_schema() -> None:
    """Repair schema differences that create_all() silently skips.

    create_all() never alters existing tables, so a developer who created their
    governance.db before a model change (e.g. adding a column, or changing a
    PRIMARY KEY) keeps the old structure even after pulling the new code.  This
    function detects and fixes known divergences in-place, preserving all rows.

    Add a new block here whenever shared/models.py changes an existing table.
    """
    with engine.connect() as conn:
        # ------------------------------------------------------------------
        # agent_trust_state: PK was (agent_id) alone; now (agent_id, session_id)
        # Symptom: "UNIQUE constraint failed: agent_trust_state.agent_id" on the
        # second tool-check call that reuses the same agent name in a new session.
        # ------------------------------------------------------------------
        row = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_trust_state'"
            )
        ).fetchone()
        if row and "PRIMARY KEY (agent_id)" in row[0] and "session_id" not in row[0].split("PRIMARY KEY")[1]:
            print("migrate: agent_trust_state has single-column PK -- rebuilding with composite PK ...")
            conn.execute(__import__("sqlalchemy").text("""
                CREATE TABLE agent_trust_state_new (
                    agent_id    VARCHAR NOT NULL,
                    session_id  VARCHAR NOT NULL,
                    parent_agent_id VARCHAR,
                    current_score   FLOAT NOT NULL,
                    last_updated    DATETIME,
                    history         JSON,
                    PRIMARY KEY (agent_id, session_id)
                )
            """))
            conn.execute(__import__("sqlalchemy").text(
                "INSERT INTO agent_trust_state_new SELECT agent_id, session_id, parent_agent_id, "
                "current_score, last_updated, history FROM agent_trust_state"
            ))
            conn.execute(__import__("sqlalchemy").text("DROP TABLE agent_trust_state"))
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE agent_trust_state_new RENAME TO agent_trust_state"
            ))
            conn.execute(__import__("sqlalchemy").text(
                "CREATE INDEX IF NOT EXISTS ix_agent_trust_state_session_id "
                "ON agent_trust_state (session_id)"
            ))
            conn.commit()
            print("migrate: agent_trust_state rebuilt -- all rows preserved")


def seed_pack(db, path: Path) -> None:
    data = yaml.safe_load(path.read_text())
    pack_id = data["pack_id"]
    for identifier in data["identifiers"]:
        existing = db.get(CompliancePackConfig, (pack_id, identifier["name"]))
        if existing is None:
            db.add(CompliancePackConfig(pack_id=pack_id, identifier=identifier["name"], action=identifier["action"]))
        else:
            existing.action = identifier["action"]


def seed_tool_thresholds(db, path: Path) -> None:
    """Only seeds rows that don't exist yet -- once an admin edits a
    threshold via the API, re-running this script must not clobber it."""
    data = yaml.safe_load(path.read_text())
    for tool_id, threshold in data["thresholds"].items():
        if db.get(ToolThresholdConfig, tool_id) is None:
            db.add(ToolThresholdConfig(tool_id=tool_id, threshold=threshold))


def main() -> None:
    migrate_schema()           # repair stale schemas before create_all touches anything
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_pack(db, CONFIG_DIR / "hipaa_pack.yaml")
        seed_pack(db, CONFIG_DIR / "dpdp_pack.yaml")
        seed_tool_thresholds(db, CONFIG_DIR / "tool_thresholds.yaml")
        db.commit()
        print("tables created + compliance packs + tool thresholds seeded")
    finally:
        db.close()


if __name__ == "__main__":
    main()
