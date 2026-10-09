# 0016. DPDP coverage audit: reuse `web_url`/`ip_address` from HIPAA, rest stays out of scope

Status: Accepted
Date: 2026-10-09

## Context

A conversation walked a published HIPAA Safe Harbor identifier list and a DPDP (India) personal-data-identifier list against the actual detector code (`detectors/hipaa/identifiers.py`, `detectors/dpdp/identifiers.py`, `data_pipeline/config/overlap_map.yaml`, `governance_api/compliance/engine.py`). HIPAA's pack covers all 18 identifiers (16 by regex, 2 by NER, per [docs/MOCKED_VS_PRODUCTION.md](../MOCKED_VS_PRODUCTION.md)). DPDP's pack, selected via `_get_detector("dpdp")`, calls *only* `detectors/dpdp/identifiers.py::find_all` — it does not fall back to HIPAA's detectors at all, so anything not explicitly re-exported into DPDP's `PATTERNS` or `find_all` is simply absent when the DPDP pack is active.

That audit found `web_url` and `ip_address` were implemented (in HIPAA's module) but never added to `overlap_map.yaml`'s `shared` list, so a DPDP request leaked URLs and IPs unredacted even though both identifiers are explicitly listed in the DPDP personal-data definition and neither pattern has anything HIPAA-specific about it — unlike, say, `medical_record_number` or `date_except_year`, which are healthcare-framed and correctly marked `pack_specific: hipaa`.

The same audit surfaced a much longer list of DPDP items with no detector at all: passport/voter ID/driving licence numbers, bank account numbers, credit/debit card numbers, UPI IDs, customer/membership/policy/employee/student numbers, medical record numbers, health-plan identifiers, device identifiers (IMEI/MAC/advertising ID), date of birth and other individual-linked dates, age, gender, usernames/handles, GPS/geolocation, browser/network identifiers, and employment/education/financial information (income, transactions, loans).

## Decision

**Reuse `web_url` and `ip_address` under DPDP now; leave the rest as a documented gap, not a silent one.**

- `detectors/dpdp/identifiers.py`'s `PATTERNS` now includes `web_url` and `ip_address`, pulled from `HIPAA_PATTERNS` the same way `phone_number`/`email_address` already were.
- `overlap_map.yaml`'s `shared` list gained both entries, with a comment explaining why (neither is healthcare-specific).
- `data_pipeline/config/dpdp_pack.yaml` gained explicit `redact` rows for both (matching HIPAA's defaults) so the admin dashboard shows them, not just the engine's silent "redact" fallback for an unconfigured identifier.
- The rest of the gap list is **not** closed here. Several of these (DOB, age, gender, employment/education/financial info) aren't crisp regex targets the way an SSN or Aadhaar number is — a bare "32" or "female" isn't PII on its own, only in context tied to an identified person, which is closer to the kind of judgment call [0008](0008-ner-low-confidence-tier.md) already flagged as out of reach for regex. Others (credit/debit cards, UPI IDs, passport/voter ID numbers, bank accounts, device/IMEI/MAC identifiers, medical record numbers, health-plan identifiers, GPS coordinates, usernames) are plausible regex targets but weren't built, and reusing HIPAA's healthcare-framed patterns (`medical_record_number`, `account_number`, `certificate_license_number`, `device_identifier`) for DPDP's generic framing would need new patterns, not just a new `shared` entry — a bigger lift than this pass covers.

## Consequences

- A DPDP-pack request now redacts URLs and IP addresses it previously let through unredacted — closes a real leak for a one-line reuse, at the cost the existing shared identifiers already pay (no new regex risk introduced).
- `docs/MOCKED_VS_PRODUCTION.md`'s DPDP row should be read alongside this ADR for the full remaining-gap list; a future pass adding DPDP-specific detectors (bank account, card, UPI, passport/voter ID, device ID, medical record number, health-plan ID, GPS) should start there rather than re-deriving the list.
- `scripts/init_db.py` was re-run against the existing `governance.db` so the new config rows exist immediately, not just on a fresh init; `seed_pack` is additive/idempotent, so this didn't disturb any admin-edited thresholds elsewhere in the table.
