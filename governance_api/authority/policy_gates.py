"""Per-tool authority thresholds -- admin-editable via /admin/tool-thresholds,
seeded from data_pipeline/config/tool_thresholds.yaml (scripts/init_db.py).
"""
from sqlalchemy.orm import Session

from shared.models import ToolThresholdConfig

# Fallback used only if a tool_id has no row at all (e.g. init_db.py wasn't run).
DEFAULT_THRESHOLD = 60.0


def required_threshold(db: Session, tool_id: str) -> float:
    row = db.get(ToolThresholdConfig, tool_id)
    return row.threshold if row is not None else DEFAULT_THRESHOLD


def set_threshold(db: Session, tool_id: str, threshold: float) -> ToolThresholdConfig:
    row = db.get(ToolThresholdConfig, tool_id)
    if row is None:
        row = ToolThresholdConfig(tool_id=tool_id, threshold=threshold)
        db.add(row)
    else:
        row.threshold = threshold
    db.commit()
    db.refresh(row)
    return row


def list_thresholds(db: Session) -> list:
    return db.query(ToolThresholdConfig).all()
