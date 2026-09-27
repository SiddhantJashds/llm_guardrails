"""The four configurable compliance actions (docs/HACKATHON_PLAN.md objective #2)."""
import hashlib


def redact(text: str, span: str, mask: str = "[REDACTED]") -> str:
    return text.replace(span, mask)


def block(_text: str) -> str:
    return ""


def hash_value(text: str, span: str) -> str:
    digest = hashlib.sha256(span.encode()).hexdigest()[:12]
    return text.replace(span, f"[HASH:{digest}]")


def log_only(text: str) -> str:
    return text
