"""Live NER-vs-Laya scoreboard (manual, NOT part of pytest).

Hits your real Laya tunnel + the real local NER path and prints a
per-text comparison table. Nondeterministic (decision-model probs vary run
to run) -- for the deterministic CI version see
detectors/tests/test_decision_compare.py.

Run from repo root:
  LAYA_ENDPOINT=https://... LAYA_API_KEY=sk-... uv run python detectors/decision/eval_compare.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DECISION_MODE", "ner")  # keep router out; we call both legs directly

from detectors.hipaa.identifiers import find_all as ner_find_all
from detectors.scoring.signals import SIGNAL_PENALTIES, phi_signal
from detectors.decision import client as laya_client
from detectors.decision import config

CORPUS = [
    "My SSN is 123-45-6789",
    "Please call 555-123-4567 to confirm.",
    "John Smith lives in Austin.",
    "The weather is nice today.",
    "My nine-digit social ends in 6789, don't share it.",
]


def _penalty(violations):
    signal = phi_signal([name for name, _ in violations])
    return signal, (SIGNAL_PENALTIES[signal] if signal else 0.0)


def main():
    if not config.laya_configured():
        print("Set LAYA_ENDPOINT and LAYA_API_KEY first.")
        sys.exit(1)
    print(f"model={config.laya_model()} threshold={config.laya_threshold()}")
    print(f"{'text':45} | {'NER violations':30} | {'pen':5} | {'ms':>7} | {'Laya violations':30} | {'pen':5} | {'ms':>7}")
    for text in CORPUS:
        t0 = time.perf_counter()
        ner = ner_find_all(text)
        ner_ms = (time.perf_counter() - t0) * 1000
        try:
            t0 = time.perf_counter()
            probs = laya_client.query(text, "hipaa")
            laya_ms = (time.perf_counter() - t0) * 1000
            laya_names = sorted(f"laya_{k}({p:.2f})" for k, p in probs.items() if p >= config.laya_threshold())
        except Exception as exc:  # tunnel down etc -- show fallback, don't crash
            laya_ms = (time.perf_counter() - t0) * 1000
            laya_names = [f"<laya error, ner fallback would serve: {exc}>"]
        _, ner_pen = _penalty(ner)
        _, laya_pen = _penalty([(n.split("(")[0], text) for n in laya_names if n.startswith("laya_")])
        print(f"{text[:44]:45} | {','.join(n for n, _ in ner)[:29]:30} | {ner_pen:4.0f} | {ner_ms:7.0f} | {','.join(laya_names)[:29]:30} | {laya_pen:4.0f} | {laya_ms:7.0f}")


if __name__ == "__main__":
    main()
