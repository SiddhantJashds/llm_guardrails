"""Decision-model detector package (Laya / Typesafe `systemOne`).

Self-contained by design: everything Laya-specific lives in this directory so
edits to the regex/NER packs (`detectors/hipaa/`, `detectors/dpdp/`,
`detectors/ner.py`) or to `governance_api/compliance/engine.py` never collide
with it. The only touch point outside this package is the ~5-line mode check
in `compliance/engine.py::_run_detectors`, which delegates here and defaults
to the pre-existing `ner` path when `DECISION_MODE` is unset.

Modes (`DECISION_MODE`):
  ner      -- current behavior, regex + spaCy NER only (default).
  laya     -- decision-model questions only (spans fall back to full text).
  cascade  -- both; union of violations, worst verdict wins (max-score rule).

Laya returns per-question P(yes) probabilities, not spans. A firing question
emits `(laya_<qid>, <full text>)` so the existing engine redacts the whole
segment coarsely instead of crashing on an empty span
(`str.replace(\"\", ...)` would poison the text). Laya hits are ordered FIRST
so a coarse full-text redact wins before precise NER spans run.
Identifiers are `laya_*`-namespaced: high-confidence by default (full -20,
configurable to `block`), and they can never collide with regex identifiers
upstream may add later.
"""
from .router import find_all, get_mode

__all__ = ["find_all", "get_mode"]
