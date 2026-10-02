# Tasks: Centro Inteligencia Reportes Auditoria API

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 340-390 API-only authored lines |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single API PR with three reviewable work units; stop if scope materially exceeds forecast |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

Pre-apply decisions resolved:
- Capacity source: `vehiculos.tipo_cliente='mensual' AND activo=1`, after verifying active mensalista records and avoiding duplicate cup counting.
- Capacity model: `total_spaces = 50`, `reserved_monthly_spaces = active_monthly_customers`, `effective_transient_capacity = 50 - active_monthly_customers`; do not use physically parked monthly vehicles for transient capacity.
- CSV policy: `legacy-only`; PDF/XLSX are canonical reporting formats.
- Scope guard: 400 changed lines is a review/scope control, not a reason to compress code, remove tests, or degrade design.
- Out of scope: pre-existing `printer_agent/run_agent_task.cmd` change must not be modified, restored, committed, or included in PR.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Canonical read-model contract | PR 1 | `pytest tests/test_reporting_read_models.py tests/test_reporting_closed_reports.py` | Direct closed-report builder/repo tests; no real DB/DDL | Revert `app/repositories/reporting_read_models.py`, `app/repositories/reporting_repo.py`, related tests |
| 2 | Export metadata and PDF/XLSX behavior | PR 1 | `pytest tests/test_reporting_exports.py` | Deterministic export builder scenario | Revert export code/tests in read models and export tests |
| 3 | Endpoint wiring and audit inventory | PR 1 | `pytest tests/test_reporting_endpoints.py tests/test_reporting_closed_reports.py` | Patched FastAPI endpoint calls | Revert `app/api/v1/endpoints/reporting.py`, repo audit helpers, endpoint tests |

## Phase 1: Pre-apply Gates and RED Tests

- [x] 1.1 Verify `vehiculos.tipo_cliente='mensual' AND activo=1` represents active monthly reserved spaces without duplicate cup counting in `app/repositories/reporting_repo.py` tests.
- [x] 1.2 Encode CSV as `legacy-only` in `app/repositories/reporting_read_models.py` and endpoint expectations; keep PDF/XLSX canonical.
- [x] 1.3 Add failing tests in `tests/test_reporting_read_models.py` for canonical totals, capacity unavailable/resolved, completeness enum, and closure-to-closure periods.
- [x] 1.4 Add failing tests in `tests/test_reporting_exports.py` for PDF/XLSX metadata stability, partial completeness visibility, and decided CSV behavior.
- [x] 1.5 Add failing tests in `tests/test_reporting_closed_reports.py` for mensualidades in net, closure references, after-midnight period membership, and audit coverage states.
- [x] 1.6 Add failing tests in `tests/test_reporting_endpoints.py` for admin-only closed report, export, and audit inventory contracts.

## Phase 2: Read Models and Repository Semantics

- [x] 2.1 Update `app/repositories/reporting_read_models.py` with canonical response fields, completeness/source-state blocks, capacity blocks, and export metadata builders.
- [x] 2.2 Update `app/repositories/reporting_repo.py` with closure-to-closure helpers, monthly-payment-inclusive net inputs, expense subtraction, and active-monthly source handling.
- [x] 2.3 Update `app/repositories/reporting_repo.py` with existing-source audit inventory reads for closure, operation, payment, expense, user/session, and print-job coverage.
- [x] 2.4 Verify Phase 2 with `pytest tests/test_reporting_read_models.py tests/test_reporting_closed_reports.py`.

## Phase 3: Export and Endpoint Wiring

- [x] 3.1 Implement PDF/XLSX closed-report export behavior in `app/repositories/reporting_read_models.py` using shared canonical identity and metadata.
- [x] 3.2 Apply the decided CSV policy in `app/repositories/reporting_read_models.py` and `app/api/v1/endpoints/reporting.py`.
- [x] 3.3 Wire `app/api/v1/endpoints/reporting.py` as a thin admin-only adapter for closed reports, exports, and audit inventory.
- [x] 3.4 Verify Phase 3 with `pytest tests/test_reporting_exports.py tests/test_reporting_endpoints.py`.

## Phase 4: Final Verification

- [x] 4.1 Run `pytest tests/test_reporting_read_models.py tests/test_reporting_exports.py tests/test_reporting_endpoints.py tests/test_reporting_closed_reports.py`.
- [x] 4.2 Review the diff to keep API-only scope and stay under the 400 changed-line guard before apply completion.
