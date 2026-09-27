"""Creates all tables and seeds the HIPAA/DPDP compliance pack config from
data_pipeline/config/*.yaml. Run once before starting either service:

`python scripts/init_db.py` from the repo root.
"""
import sys
from pathlib import Path

import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from shared.db import Base, engine, SessionLocal
from shared.models import CompliancePackConfig, ToolThresholdConfig

CONFIG_DIR = Path(__file__).resolve().parents[1] / "data_pipeline" / "config"


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
