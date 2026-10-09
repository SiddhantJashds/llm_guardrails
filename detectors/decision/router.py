"""Mode router: the package's only entry point used by compliance/engine.py.

`find_all(text, pack_id)` mirrors the `detectors.<pack>.identifiers.find_all`
signature so the engine hook stays a 5-line delegation. NER callables are
passed in by the engine (lazy imports stay where they are) so this package
never imports pack internals at module load -- upstream refactors of the
packs can't break this import.
"""
import logging
from typing import Callable, List, Tuple

from . import config
from .client import LayaUnavailableError, find_all as laya_find_all

log = logging.getLogger(__name__)

DetectorFn = Callable[[str], List[Tuple[str, str]]]


def get_mode() -> str:
    return config.get_mode()


def find_all(text: str, pack_id: str, ner_find_all: DetectorFn) -> List[Tuple[str, str]]:
    """Route by DECISION_MODE. Cascade = Laya hits FIRST, then NER (union)."""
    mode = config.get_mode()
    if mode == "ner":
        return ner_find_all(text)
    if mode == "laya":
        try:
            return laya_find_all(text, pack_id)
        except LayaUnavailableError as exc:
            if not config.laya_fail_open():
                raise
            log.warning("laya unavailable, falling back to ner: %s", exc)
            return ner_find_all(text)
    # cascade: both, worst wins. Laya-first ordering so a coarse full-text
    # redact lands before precise NER spans (engine applies in list order).
    try:
        laya_hits = laya_find_all(text, pack_id)
    except LayaUnavailableError as exc:
        if not config.laya_fail_open():
            raise
        log.warning("laya unavailable in cascade, ner only: %s", exc)
        return ner_find_all(text)
    return laya_hits + ner_find_all(text)
