# 0007. Automated tests + CI as a readiness gate before handoff

Status: Accepted
Date: 2026-09-28

## Context

The team lead won't be actively monitoring the 4 developers during the 2-day build. Four people editing shared files (`shared/models.py`, `shared/schemas.py`, `governance_api/authority/policy_gates.py`'s signature change, etc.) concurrently, with no automated check, means a breaking change can sit unnoticed until the demo — exactly the "hiccup" a self-managing handoff needs to avoid. Before this, the only test coverage was `detectors/tests/` (6 tests); `governance_api`'s authority engine, receipts, compliance engine, access control, and routes had none.

## Decision

Added `governance_api/tests/` (unit tests for `authority/engine.py`'s monotonic reduction and delegation capping, `receipts/writer.py`'s hash-chain integrity and tamper detection, `compliance/engine.py`'s action branching and the redact-by-default override gate, `access_control/overrides.py`'s restrictive-by-default rule, and route-level tests via FastAPI's `TestClient` that catch cross-role signature breakage). Added `.github/workflows/tests.yml` running `pytest` on every push/PR to `main`. Root `pytest.ini` + `requirements-dev.txt` so `pytest` from the repo root runs everything with one command.

One test (`test_api_routes.py::test_compliance_check_actually_catches_phi_once_detectors_are_wired`) is deliberately marked `xfail(strict=True)` against the known gap that `compliance/engine.py`'s `_run_detectors` isn't wired to `detectors/hipaa/identifiers.py` yet (see [docs/MOCKED_VS_PRODUCTION.md](../MOCKED_VS_PRODUCTION.md)). `strict=True` means it will fail CI (XPASS) the moment that gap closes, as a forcing function to remove the marker and check the item off in `docs/PROGRESS.md`.

## Consequences

A broken shared-file change now fails a GitHub Actions check on the PR instead of surfacing at demo time. This isn't full coverage — most of the placeholder logic listed in `docs/MOCKED_VS_PRODUCTION.md` still needs its own tests as it gets built out for real (the `dev-next-steps` skill's "confirm it's verified" step is where that should happen, not as a one-time batch). The `xfail(strict=True)` pattern used for the detector-wiring gap is worth reusing for the other "day 2 close-the-loop" items called out in `docs/PROGRESS.md` (e.g. per-agent score rollup, token-usage ingestion) as those get built.
