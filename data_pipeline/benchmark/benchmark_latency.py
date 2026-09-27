"""Before/after latency comparison: direct upstream call vs. through the
governance proxy (objective #15, nice-to-have). Cheap once the proxy exists --
run this after the core loop is stable, not before.

Run: `python data_pipeline/benchmark/benchmark_latency.py`
"""
import os
import time

import httpx

PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8000/v1/chat/completions")
UPSTREAM_URL = os.getenv("UPSTREAM_LLM_BASE_URL", "https://api.openai.com/v1") + "/chat/completions"

SAMPLE_PAYLOAD = {
    "model": "gpt-4o-mini",  # TODO: swap for whatever model the demo actually targets
    "messages": [{"role": "user", "content": "Say hello in one word."}],
}


def _timed_post(url: str, headers: dict) -> float:
    start = time.perf_counter()
    httpx.post(url, json=SAMPLE_PAYLOAD, headers=headers, timeout=30.0)
    return time.perf_counter() - start


def run_benchmark(n: int = 5) -> None:
    api_key = os.getenv("UPSTREAM_LLM_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"}

    direct_times = [_timed_post(UPSTREAM_URL, headers) for _ in range(n)]
    proxied_times = [_timed_post(PROXY_URL, {}) for _ in range(n)]

    print(f"direct  avg: {sum(direct_times) / n:.3f}s  ({direct_times})")
    print(f"proxied avg: {sum(proxied_times) / n:.3f}s  ({proxied_times})")
    print(f"added overhead: {(sum(proxied_times) - sum(direct_times)) / n:.3f}s per call")


if __name__ == "__main__":
    run_benchmark()
