# Tasks: Reporting API Filters, Sorting, and Pagination

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 500-750 authored lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 read-model/validators -> PR 2 endpoint/repository wiring |
| Delivery strategy | ask-on-risk |
| Chain strategy | Feature Branch Chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: Feature Branch Chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Read-model validation, serialization, and pagination metadata | PR 1 | `python -m unittest tests.test_reporting_read_models` | N/A: helper-only unit slice | Revert read-model helpers and their tests |
| 2 | Admin endpoint and repository closed-period operations page | PR 2 | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_closed_reports` | N/A: no E2E harness for this API slice | Revert endpoint/repository methods and their tests |

## Verification Commands

- Focused: `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports`
- Full test sweep: `python -m unittest discover tests`
- Compile/build: `python -m compileall app tests`

## Phase 1: RED Read-model Tests

- [x] 1.1 Add failing pagination metadata, final-page, and bounds tests in `tests/test_reporting_read_models.py`.
- [x] 1.2 Add failing filter allow-list, sort allow-list, invalid value, and stable row serialization tests in `tests/test_reporting_read_models.py`.

## Phase 2: GREEN Read-model Helpers

- [x] 2.1 Add allowed filter/sort constants, validation helpers, and pagination metadata builder in `app/repositories/reporting_read_models.py`.
- [x] 2.2 Add operation row serialization with stable `operation_id` identity in `app/repositories/reporting_read_models.py`.

## Phase 3: RED Endpoint and Repository Tests

- [x] 3.1 Add failing admin-only, `period_id=closure:{id}`, non-closure rejection, unknown query-key, and bad sort tests in `tests/test_reporting_endpoints.py`.
- [x] 3.2 Add failing repository tests for closure window lookup, supported filters, deterministic ordering, bound params, count metadata, and final-page metadata in `tests/test_reporting_closed_reports.py`.

## Phase 4: GREEN Endpoint and Repository Implementation

- [x] 4.1 Add `GET /api/v1/reporting/reports/operations` to `app/api/v1/endpoints/reporting.py` with strict query validation and admin guard preservation.
- [x] 4.2 Add `list_operation_rows()` and closure-window helper to `app/repositories/reporting_repo.py` using constant SQL fragments and bound params only.
- [x] 4.3 Wire endpoint response shape `{period_id, filters, sort, pagination, items}` from repository results in `app/api/v1/endpoints/reporting.py`.

## Phase 5: Verification and Cleanup

- [x] 5.1 Run focused, full test sweep, and compile commands from Verification Commands.
- [x] 5.2 Confirm no Desktop, Mobile, Installer, packaging, remote-operation, or `printer_agent/run_agent_task.cmd` changes are present.
