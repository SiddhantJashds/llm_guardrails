"""Shared constants for the reference agents in this directory.

One place for where the proxy lives, which model to ask for, and the default
user, so the examples can't drift apart from each other or from run.sh.

Each value resolves as: process env > repo-root `.env` > default. The default
proxy port follows `WITH_BRIDGE` exactly like run.sh does (`:8002` in bench
mode, `:8000` otherwise), so the examples track whichever mode run.sh started.
Set `PROXY_URL` (shell or `.env`) to point somewhere else entirely.
"""
import os
from collections.abc import Mapping
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

DEFAULT_MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"
DEFAULT_USER_ID = "demo_user"


def read_dotenv(path: Path) -> dict:
    """Parse KEY=VALUE lines from a .env file (last duplicate wins)."""
    values: dict = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def resolve(environ: Mapping, dotenv: Mapping) -> dict:
    """Resolve the example settings: environ > dotenv > default (empty = unset)."""

    def get(key: str, default: str) -> str:
        return environ.get(key) or dotenv.get(key) or default

    # run.sh moves the proxy off :8000 in bench mode (the bench server needs it).
    proxy_port = "8002" if get("WITH_BRIDGE", "0") == "1" else "8000"
    return {
        "PROXY_URL": get("PROXY_URL", f"http://localhost:{proxy_port}/v1/chat/completions"),
        "MODEL": get("CHAT_MODEL", DEFAULT_MODEL),
    }


_settings = resolve(os.environ, read_dotenv(_ENV_PATH))
PROXY_URL = _settings["PROXY_URL"]
MODEL = _settings["MODEL"]
