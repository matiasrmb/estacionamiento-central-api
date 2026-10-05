# Tasks: Historical Plate History, Anomalies, and Statistics API

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 360-520 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 read-model/validation -> PR 2 repository/endpoint |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Read-model builders and endpoint validation contract | PR 1 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | N/A: patched endpoint/unit boundary only | Revert read-model helpers and validation tests in `app/repositories/reporting_read_models.py`, `tests/test_reporting_read_models.py`, `tests/test_reporting_endpoints.py` |
| 2 | Repository source queries and route delegation | PR 2 | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_read_models` | `GET /api/v1/reporting/plates/{plate}/history?start=...&end=...&limit=500` with admin auth in existing API harness | Remove route, repository method, and focused tests in `app/api/v1/endpoints/reporting.py`, `app/repositories/reporting_repo.py`, `tests/test_reporting_endpoints.py` |

## Phase 1: RED - Read Models and Validation

- [x] 1.1 Add failing tests in `tests/test_reporting_read_models.py` for deterministic timeline ordering, source labels, statistics totals, coverage states, and weakest `historical_completeness`.
- [x] 1.2 Add failing tests in `tests/test_reporting_endpoints.py` proving admin-only access, invalid plate rejection, missing/invalid bounds rejection, >366-day rejection, and limit `1..500` before repository calls.

## Phase 2: GREEN - Read Model and Validation

- [x] 2.1 Add plate-history builders in `app/repositories/reporting_read_models.py` for timeline rows, anomaly summary, statistics, source coverage, and completeness.
- [x] 2.2 Add route-level validation helpers in `app/api/v1/endpoints/reporting.py` using `app/core/plates.py` normalization, ISO bounds, 366-day cap, and limit cap.
- [x] 2.3 Run `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` and keep failures limited to repository delegation until Phase 3 RED.

## Phase 3: RED - Repository and Endpoint Wiring

- [x] 3.1 Add failing endpoint delegation tests in `tests/test_reporting_endpoints.py` for normalized plate, parsed bounds, limit, 422 `ValueError` mapping, and no repository call on invalid input.
- [x] 3.2 Add failing repository tests in `tests/test_reporting_read_models.py` or a focused reporting repository test file for available/partial/unavailable source coverage without fabricated rows.

## Phase 4: GREEN - Repository and Endpoint Wiring

- [x] 4.1 Add `get_plate_history(...)` in `app/repositories/reporting_repo.py` with bounded SELECTs for parking, solo-wash, monthly-payment, night-charge, closure, and logical-deletion sources; tolerate optional missing tables as `unavailable`.
- [x] 4.2 Add `GET /api/v1/reporting/plates/{plate}/history` in `app/api/v1/endpoints/reporting.py` with `Depends(require_role("admin"))`, repository delegation, and 422 error mapping.
- [x] 4.3 Run `python -m unittest tests.test_reporting_endpoints tests.test_reporting_read_models`.

## Phase 5: REFACTOR and Regression

- [x] 5.1 Refactor duplicated source/coverage constants inside reporting repository/read-model boundaries only.
- [x] 5.2 Run `python -m unittest discover tests`; do not touch `printer_agent/run_agent_task.cmd`.

## Remediation: Audit Inventory Source Coverage

- [x] R1 Add focused audit-inventory tests for plate-history source names, partial/unavailable states, and out-of-scope persisted anomaly/event-sourcing behavior.
- [x] R2 Add audit-inventory source coverage for `parking`, `solo_wash`, `monthly_payment`, `night_charge`, `closure`, and `logical_deletion` without broadening the historical endpoint scope.
- [x] R3 Run focused remediation tests and full `python -m unittest discover tests`; do not touch `printer_agent/run_agent_task.cmd`.
