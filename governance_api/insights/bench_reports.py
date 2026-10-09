"""Read GuardRailBench report JSON files for the dashboard's Bench view.

Read-only, and only files directly inside the reports directory whose names
match a strict pattern -- the name comes from the URL, so it's untrusted.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

_NAME = re.compile(r"[A-Za-z0-9._-]+\.json")
_SUMMARY_KEYS = ("started_at", "duration_s", "edition", "totals", "scenarios_run", "users", "governance_url")
_SCENARIO_KEYS = ("number", "name", "user", "role", "status", "reason", "duration_s", "session_ids", "checks", "requests")


def bench_reports_dir() -> Path:
    default = Path(__file__).resolve().parents[2].parent / "GuardRailBench-Sample" / "reports"
    return Path(os.getenv("BENCH_REPORTS_DIR", str(default)))


def _read(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_runs(d: Path) -> list:
    if not d.is_dir():
        return []
    runs = []
    for path in d.glob("*.json"):
        data = _read(path)
        if data is not None:
            runs.append({
                "name": path.name,
                **{k: data.get(k) for k in _SUMMARY_KEYS},
                # Per-scenario status so the Bench view can show a
                # scenario x run matrix (spot a regression between runs).
                "scenario_status": [
                    {"number": s.get("number"), "name": s.get("name"), "status": s.get("status")}
                    for s in data.get("scenarios") or []
                ],
            })
    return sorted(runs, key=lambda r: r.get("started_at") or "", reverse=True)


def _load(d: Path, name: str) -> Optional[dict]:
    if not _NAME.fullmatch(name):
        return None
    path = d / name
    if path.resolve().parent != d.resolve() or not path.is_file():
        return None
    return _read(path)


def load_hooks(d: Path, name: str, index: int) -> Optional[list]:
    """One scenario's full hook log (input/output per hook) for debugging."""
    data = _load(d, name)
    scenarios = (data or {}).get("scenarios") or []
    if not 0 <= index < len(scenarios):
        return None
    return scenarios[index].get("hook_log") or []


def load_run(d: Path, name: str) -> Optional[dict]:
    data = _load(d, name)
    if data is None:
        return None
    scenarios = [
        {**{k: s.get(k) for k in _SCENARIO_KEYS}, "hook_events": len(s.get("hook_log") or [])}
        for s in data.get("scenarios") or []
    ]
    return {
        "name": name,
        **{k: data.get(k) for k in _SUMMARY_KEYS},
        "per_user_summary": data.get("per_user_summary"),
        "scenarios": scenarios,
    }
