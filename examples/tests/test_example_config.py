import importlib

import example_config
from example_config import DEFAULT_MODEL, read_dotenv, resolve

NORMAL = "http://localhost:8000/v1/chat/completions"
BENCH = "http://localhost:8002/v1/chat/completions"


def test_defaults_to_normal_port_with_nothing_set():
    assert resolve({}, {})["PROXY_URL"] == NORMAL


def test_bench_mode_from_dotenv_moves_proxy_port():
    assert resolve({}, {"WITH_BRIDGE": "1"})["PROXY_URL"] == BENCH


def test_bridge_off_in_dotenv_stays_on_normal_port():
    assert resolve({}, {"WITH_BRIDGE": "0"})["PROXY_URL"] == NORMAL


def test_process_env_beats_dotenv():
    assert resolve({"WITH_BRIDGE": "0"}, {"WITH_BRIDGE": "1"})["PROXY_URL"] == NORMAL


def test_explicit_proxy_url_beats_bridge_mode():
    got = resolve({}, {"PROXY_URL": "http://h:9/v1/chat/completions", "WITH_BRIDGE": "1"})
    assert got["PROXY_URL"] == "http://h:9/v1/chat/completions"


def test_process_proxy_url_beats_dotenv_proxy_url():
    got = resolve({"PROXY_URL": "http://b/y"}, {"PROXY_URL": "http://a/x"})
    assert got["PROXY_URL"] == "http://b/y"


def test_empty_value_counts_as_unset():
    assert resolve({}, {"PROXY_URL": "", "WITH_BRIDGE": "1"})["PROXY_URL"] == BENCH


def test_model_default_and_override():
    assert resolve({}, {})["MODEL"] == DEFAULT_MODEL
    assert resolve({}, {"CHAT_MODEL": "my-model"})["MODEL"] == "my-model"


def test_read_dotenv_skips_comments_blanks_and_strips_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# WITH_BRIDGE=1\n\nPROXY_URL="http://h:9/x"\nCHAT_MODEL=\'m\'\nnot a pair\n')
    assert read_dotenv(env) == {"PROXY_URL": "http://h:9/x", "CHAT_MODEL": "m"}


def test_read_dotenv_last_duplicate_wins(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WITH_BRIDGE=1\nWITH_BRIDGE=0\n")
    assert read_dotenv(env) == {"WITH_BRIDGE": "0"}


def test_read_dotenv_missing_file_is_empty(tmp_path):
    assert read_dotenv(tmp_path / "nope.env") == {}


def test_module_constants_follow_process_env(monkeypatch):
    # Process env always wins, so this holds whatever the real repo .env says.
    monkeypatch.setenv("WITH_BRIDGE", "0")
    monkeypatch.delenv("PROXY_URL", raising=False)
    try:
        importlib.reload(example_config)
        assert example_config.PROXY_URL == NORMAL
        monkeypatch.setenv("PROXY_URL", "http://x:1/v1/chat/completions")
        importlib.reload(example_config)
        assert example_config.PROXY_URL == "http://x:1/v1/chat/completions"
    finally:
        monkeypatch.undo()
        importlib.reload(example_config)
