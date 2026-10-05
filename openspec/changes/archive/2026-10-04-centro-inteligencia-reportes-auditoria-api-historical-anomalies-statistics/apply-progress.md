# Apply Progress: Historical Plate History, Anomalies, and Statistics API

```yaml
schema: gentle-ai.sdd-apply-progress/v1
change: centro-inteligencia-reportes-auditoria-api-historical-anomalies-statistics
project: estacionamiento-central-api
artifact_store: hybrid
phase: apply
slice: audit-inventory-remediation
mode: Standard
strict_tdd: false
status: passed
attempt_token: sha256:0cbabb86205b163d273ee50eb399829e48282483f236656da42d976089f40539
remediates_evidence_revision: sha256:491733510783b1fb284e0e908012dacaf9e10c0e038a9ecdba3fd3d62d5abdd9
previous_attempt_token: sha256:38b20e1de6e6e733f70941b8850b550d2638284129fd206c5d22d131c1ab5279
```

## Scope

Implemented slice 1, slice 2, and final apply cleanup cumulatively:

- [x] 1.1 RED read-model tests
- [x] 1.2 RED endpoint validation tests
- [x] 2.1 GREEN plate-history read-model builders
- [x] 2.2 GREEN route-level validation helpers
- [x] 2.3 GREEN focused verification command
- [x] 3.1 RED endpoint delegation tests
- [x] 3.2 RED repository coverage tests
- [x] 4.1 GREEN repository source queries
- [x] 4.2 GREEN final endpoint delegation and error mapping
- [x] 4.3 GREEN focused verification command
- [x] 5.1 REFACTOR duplicated source/coverage constants
- [x] 5.2 Full regression verification command

All assigned apply tasks are complete. Full regression passed in this final cleanup slice.

## RED Evidence

| Task | Command | Observed result |
|---|---|---|
| 1.1, 1.2 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | Failed as expected before slice 1 implementation: `FAILED (errors=9)`. Missing `build_plate_history_response`, `get_plate_history`, and `get_persisted_plate_history` scaffolding. |
| 3.1, 3.2 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | Failed as expected before slice 2 implementation: `Ran 31 tests in 0.040s`, `FAILED (failures=1, errors=3)`. Missing repository `get_plate_history`, endpoint still returned `501 PLATE_HISTORY_REPOSITORY_NOT_IMPLEMENTED`, and repository `ValueError` mapping was not wired. |

## GREEN Evidence

| Task | Command | Observed result |
|---|---|---|
| 2.1, 2.2, 2.3 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | Passed after slice 1: `Ran 27 tests in 0.008s` / `OK`. |
| 4.1, 4.2, 4.3 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | Passed after slice 2: `Ran 31 tests in 0.010s` / `OK`. |
| 5.1 | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` | Passed after final refactor: `Ran 31 tests in 0.009s` / `OK`. |
| 5.2 | `python -m unittest discover tests` | Passed after final cleanup: `Ran 498 tests in 0.604s` / `OK`. Observed existing warnings/log output from SQLAlchemy/sqlite ResourceWarnings, HTTP 422 deprecation warning, print-agent mocked error logs, argparse error-path test output, slowlog warning, and optional-table skip messages; no failures or errors. |

## Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints` → exit code 0, `Ran 31 tests in 0.009s`, `OK`. |
| Runtime harness command/scenario and exact result | `GET /api/v1/reporting/plates/{plate}/history?start=2026-01-01T00:00:00&end=2026-01-02T00:00:00&limit=25` with admin dependency verified by route metadata and repository boundary patched in endpoint tests → `test_plate_history_delegates_normalized_plate_parsed_bounds_and_limit` passed in the focused command. No live ASGI server or remote database was started. |
| Rollback boundary | Revert plate-history changes in `app/repositories/reporting_repo.py`, `app/repositories/reporting_read_models.py`, `app/api/v1/endpoints/reporting.py`, `tests/test_reporting_read_models.py`, `tests/test_reporting_endpoints.py`, this `apply-progress.md`, and the completed checkboxes in `tasks.md`. Preserve unrelated `printer_agent/run_agent_task.cmd` local changes. |

## Implementation Notes

- Slice 1 added `build_plate_history_response` read-model assembly with deterministic timeline ordering, source coverage, anomaly summary, statistics, and weakest historical completeness.
- Slice 1 added route-level validation scaffolding for `GET /api/v1/reporting/plates/{plate}/history` using shared plate normalization, required ISO bounds, a 366-day window cap, and `limit` range `1..500`.
- Slice 2 replaced the temporary `501` scaffold with endpoint delegation to `reporting_repo.get_plate_history(...)` and maps repository `ValueError` to HTTP 422.
- Slice 2 added bounded source queries for parking, solo-wash, monthly-payment, night-charge, closure, and logical-deletion sources. Each source is queried independently; query failures mark only that source `unavailable` and do not fabricate rows.
- Repository tests use a patched `db_conn` boundary to prove available sources can return rows, empty sources do not fabricate evidence, and unavailable optional sources are surfaced in `historical_completeness`.
- Final cleanup refactored shared source and coverage constants into `reporting_read_models` and reused them from `reporting_repo`, keeping the change inside the reporting repository/read-model boundary.
- Final regression passed with the required repository-wide unittest discovery command.

## Remaining Tasks

- [x] None. All apply tasks are complete.

## Risks

- The repository marks a source as `unavailable` when its bounded query raises, including legacy schemas that lack optional source tables or expected columns. This is intentional for source-backed completeness, but verify should still review against production schema inventory expectations.
- `printer_agent/run_agent_task.cmd` remains an unrelated local modification and was not touched.
- Full regression emits pre-existing warning and mocked-error log noise, but exits successfully with `OK`.

## Remediation Evidence: Audit Inventory Plate-History Source Coverage

```yaml
remediation_status: passed
remediation_attempt_token: sha256:0cbabb86205b163d273ee50eb399829e48282483f236656da42d976089f40539
remediates_evidence_revision: sha256:491733510783b1fb284e0e908012dacaf9e10c0e038a9ecdba3fd3d62d5abdd9
```

### Scope

- [x] Added focused read-model tests proving audit inventory exposes required plate-history source names: `parking`, `solo_wash`, `monthly_payment`, `night_charge`, `closure`, and `logical_deletion`.
- [x] Added focused tests proving plate-history source coverage can be `available`, `partial`, or `unavailable` and that affected unavailable sources are identified.
- [x] Added a focused test proving persisted anomaly records, event-sourced history, and transversal audit logs remain unsupported/out of scope.
- [x] Added repository coverage proving audit inventory maps required plate-history source names to existing table coverage states without touching the historical endpoint scope.
- [x] Implemented the smallest production change: audit inventory now includes plate-history source coverage and explicit unsupported audit behaviors while retaining existing source coverage states.

### RED / GREEN Evidence

| Step | Command | Observed result |
|---|---|---|
| RED | `python -m unittest tests.test_reporting_closed_reports` | Failed as expected before production change: `Ran 7 tests in 1.154s`, `FAILED (failures=1, errors=1)`. Missing `parking`/plate-history source coverage and missing `unsupported_behaviors`. |
| GREEN focused read-model/endpoint | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_read_models` | Passed after remediation: `Ran 34 tests in 0.043s`, `OK`. |
| GREEN repository audit inventory | `python -m unittest tests.test_reporting_closed_reports` | Passed after remediation: `Ran 5 tests in 1.175s`, `OK`. |
| Regression | `python -m unittest discover tests` | Passed after remediation: `Ran 502 tests in 1.497s`, `OK`. Observed existing warning/log noise from SQLAlchemy/sqlite ResourceWarnings, HTTP 422 deprecation warning, print-agent mocked error logs, argparse error-path output, slowlog warning, and optional-table skip messages. |

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_read_models` → exit code 0, `Ran 34 tests in 0.043s`, `OK`; `python -m unittest tests.test_reporting_closed_reports` → exit code 0, `Ran 5 tests in 1.175s`, `OK`. |
| Runtime harness command/scenario and exact result | Existing endpoint boundary for `GET /api/v1/reporting/audit-inventory?period_id=closure:18` remains repository-backed and admin-only via `tests.test_reporting_endpoints`; remediation is a read-model/repository coverage shape change, so no live ASGI server or remote database was started. |
| Rollback boundary | Revert remediation changes in `app/repositories/reporting_read_models.py`, `app/repositories/reporting_repo.py`, `tests/test_reporting_read_models.py`, `tests/test_reporting_closed_reports.py`, this `apply-progress.md`, and the remediation note in `tasks.md`. Preserve unrelated `printer_agent/run_agent_task.cmd` local changes. |

### Notes

- The audit inventory now identifies plate-history source coverage separately from generic reporting source names.
- Persisted anomaly records, event-sourced history, and transversal audit logs remain explicitly unsupported; no persistence, endpoint expansion, migration, remote probing, or historical endpoint broadening was added.
