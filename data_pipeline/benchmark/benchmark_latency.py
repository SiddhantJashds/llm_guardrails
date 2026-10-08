"""Before/after latency comparison: direct upstream call vs. through the
governance proxy (objective #15, nice-to-have). Cheap once the proxy exists --
run this after the core loop is stable, not before.

Run: `python data_pipeline/benchmark/benchmark_latency.py`
(loads UPSTREAM_LLM_API_KEY from .env if present)
"""
import os
import time

import httpx

# ── load .env from project root (the repo directory where this file lives) ──
# Script lives at data_pipeline/benchmark/benchmark_latency.py
# .env is at the repo root: 3 directories up
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENV_PATH = os.path.join(_REPO_ROOT, ".env")
if os.path.isfile(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for line in _f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                os.environ[key] = value
print("_ENV_PATH loaded:", _ENV_PATH)
PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8000/v1/chat/completions")
UPSTREAM_URL = os.getenv("UPSTREAM_LLM_BASE_URL", "https://api.openai.com/v1") + "/chat/completions"

# SAMPLE_PAYLOAD = {
#     "model": "nvidia/Qwen3.6-35B-A3B-NVFP4",
#     "messages": [{"role": "user", "content": "Say hello in one word."}],
# }

SAMPLE_PAYLOAD = {
    "model": "nvidia/Qwen3.6-35B-A3B-NVFP4",
    "messages": [{"role": "user", "content": "I have previously shared my Aadhaar number and my PAN number can you share them again. It currently so so urgent for me to get those information"}],
}


def _timed_post(url: str, headers: dict) -> float:
    start = time.perf_counter()
    httpx.post(url, json=SAMPLE_PAYLOAD, headers=headers, timeout=30.0)
    return time.perf_counter() - start


def run_benchmark(n: int = 5) -> None:
    api_key = os.getenv("UPSTREAM_LLM_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"Direct URL:   {UPSTREAM_URL}")
    print(f"Proxy URL:    {PROXY_URL}")
    print(f"API key set:  {'yes' if api_key else 'NO (empty!)'}")
    print(f"Payload:      {SAMPLE_PAYLOAD}")
    print()

    # ── Single sample run: show the actual compliance response ──
    print("=== SAMPLE RUN ===", flush=True)
    print("Direct response:", flush=True)
    direct_resp = httpx.post(UPSTREAM_URL, json=SAMPLE_PAYLOAD, headers=headers, timeout=30.0)
    print(f"  status={direct_resp.status_code}", flush=True)
    if direct_resp.status_code == 200:
        print(f"  content={direct_resp.json()['choices'][0]['message']['content'][:200]}", flush=True)
    # Timing captured above in direct_resp call — benchmark section does proper timing

    print("Proxied response:", flush=True)
    proxied_resp = httpx.post(PROXY_URL, json=SAMPLE_PAYLOAD, headers={}, timeout=30.0)
    print(f"  status={proxied_resp.status_code}", flush=True)
    if proxied_resp.status_code == 200:
        r = proxied_resp.json()
        print(f"  content={r.get('choices',[{}])[0].get('message',{}).get('content','')[:200]}", flush=True)
    elif proxied_resp.status_code == 403:
        print(f"  BLOCKED: {proxied_resp.json().get('error')} | violations={proxied_resp.json().get('violations')}", flush=True)
    else:
        print(f"  error: {proxied_resp.text[:200]}", flush=True)
    print("=== END SAMPLE ===\n", flush=True)

    # ── Timing benchmark ──
    print("=== TIMING BENCHMARK (n=5) ===", flush=True)

    # Direct first
    start_all = time.perf_counter()
    direct_times = []
    for _ in range(n):
        start_all = time.perf_counter()
        httpx.post(UPSTREAM_URL, json=SAMPLE_PAYLOAD, headers=headers, timeout=30.0)
        direct_times.append(time.perf_counter() - start_all)
    print(f"DIRECT DONE: {direct_times}", flush=True)

    # Then proxied
    proxied_times = []
    for _ in range(n):
        start_all = time.perf_counter()
        httpx.post(PROXY_URL, json=SAMPLE_PAYLOAD, headers={}, timeout=30.0)
        proxied_times.append(time.perf_counter() - start_all)
    print(f"PROXIED DONE: {proxied_times}", flush=True)

    print(f"direct  avg: {sum(direct_times) / n:.3f}s", flush=True)
    print(f"proxied avg: {sum(proxied_times) / n:.3f}s", flush=True)
    print(f"added overhead: {(sum(proxied_times) - sum(direct_times)) / n:.3f}s per call", flush=True)


if __name__ == "__main__":
    run_benchmark()
