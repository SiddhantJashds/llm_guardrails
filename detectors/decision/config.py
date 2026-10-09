"""Env-driven config for the decision-model path. All `os.getenv` with safe
defaults: unset means classic `ner` behavior, so existing deployments and
tests never notice this package."""
import os


def get_mode() -> str:
    """ner | laya | cascade. Unknown values fall back to ner (fail-safe)."""
    mode = os.getenv("DECISION_MODE", "ner").strip().lower()
    return mode if mode in ("ner", "laya", "cascade") else "ner"


def laya_endpoint() -> str:
    return os.getenv("LAYA_ENDPOINT", "").rstrip("/")


def laya_api_key() -> str:
    return os.getenv("LAYA_API_KEY", "")


def laya_model() -> str:
    return os.getenv("LAYA_MODEL", "laya-multilingual")


def laya_timeout_s() -> float:
    try:
        return float(os.getenv("LAYA_TIMEOUT_S", "10"))
    except ValueError:
        return 10.0


def laya_threshold() -> float:
    try:
        return float(os.getenv("LAYA_THRESHOLD", "0.5"))
    except ValueError:
        return 0.5


def laya_fail_open() -> bool:
    """1 (default): Laya error -> fall back to ner, never break the request.
    0: propagate LayaUnavailableError (fail-closed, CI strictness)."""
    return os.getenv("LAYA_FAIL_OPEN", "1") != "0"


def laya_configured() -> bool:
    return bool(laya_endpoint() and laya_api_key())
