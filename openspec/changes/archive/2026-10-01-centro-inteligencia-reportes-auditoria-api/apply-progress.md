# Apply Progress: Centro Inteligencia Reportes Auditoria API

## Mode

Standard mode. `openspec/config.yaml` is not present in this repository, so strict TDD mode was not enabled.

## Completed Tasks

- [x] 1.1 Verify active monthly reserved spaces from `vehiculos.tipo_cliente='mensual' AND activo=1` without duplicate cup counting.
- [x] 1.2 Encode CSV as `legacy-only`; keep PDF/XLSX canonical.
- [x] 1.3 Cover canonical totals, capacity states, completeness enum, and closure-to-closure periods.
- [x] 1.4 Cover PDF/XLSX metadata stability, partial completeness visibility, and CSV policy.
- [x] 1.5 Cover mensualidades in net, closure references, after-midnight period membership, and audit coverage states.
- [x] 1.6 Cover admin-only closed report, export, and audit inventory contracts.
- [x] 2.1 Add canonical response fields, completeness/source-state blocks, capacity blocks, and export metadata builders.
- [x] 2.2 Add monthly-payment-inclusive net inputs, expense subtraction, and active-monthly source handling.
- [x] 2.3 Add existing-source audit inventory reads.
- [x] 2.4 Verify Phase 2 scope with focused tests.
- [x] 3.1 Implement PDF/XLSX closed-report export behavior with shared identity and metadata.
- [x] 3.2 Apply CSV `legacy-only` policy.
- [x] 3.3 Wire admin-only endpoint adapters for closed reports, exports, and audit inventory.
- [x] 3.4 Verify Phase 3 scope with focused tests.
- [x] 4.1 Run final verification command or bounded substitute where the requested runner is unavailable.
- [x] 4.2 Review API-only diff and 400-line guard.

## Work Unit Evidence

| Work Unit | Focused test command and exact result | Runtime harness command/scenario and exact result | Rollback boundary |
|---|---|---|---|
| 1. Canonical read-model contract | `python -m unittest tests.test_reporting_read_models tests.test_reporting_closed_reports` as part of combined run: 28 tests passed in 0.029s. | Direct closed-report builder and mocked repository tests; no real DB/DDL. Result: passed. | Revert `app/repositories/reporting_read_models.py`, `app/repositories/reporting_repo.py`, `tests/test_reporting_read_models.py`, `tests/test_reporting_closed_reports.py`. |
| 2. Export metadata and PDF/XLSX behavior | `python -m unittest tests.test_reporting_exports` as part of combined run: 28 tests passed in 0.029s. | Deterministic export builder scenarios for CSV/PDF/XLSX. Result: passed. | Revert export code in `app/repositories/reporting_read_models.py` and `tests/test_reporting_exports.py`. |
| 3. Endpoint wiring and audit inventory | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_closed_reports` as part of combined run: 28 tests passed in 0.029s. | Patched FastAPI endpoint function calls and mocked DB inventory/report reads. Result: passed. | Revert `app/api/v1/endpoints/reporting.py`, audit helpers in `app/repositories/reporting_repo.py`, and endpoint/closed-report tests. |

## Verification Notes

- Requested command `pytest tests/test_reporting_read_models.py tests/test_reporting_exports.py tests/test_reporting_endpoints.py tests/test_reporting_closed_reports.py` was attempted and failed because `pytest` is not installed or on PATH.
- Fallback command `python -m pytest tests/test_reporting_read_models.py tests/test_reporting_exports.py tests/test_reporting_endpoints.py tests/test_reporting_closed_reports.py` also failed because the active Python has no `pytest` module.
- Equivalent standard-library command `python -m unittest tests.test_reporting_read_models tests.test_reporting_exports tests.test_reporting_endpoints tests.test_reporting_closed_reports` passed: 28 tests in 0.029s.

## Scope and Budget

- API-only files were modified.
- `printer_agent/run_agent_task.cmd` was not modified by this apply work and remains an unrelated pre-existing local change.
- Authored API/test/OpenSpec changes are within the 400-line review guard based on diff review; no code or tests were compressed to fit the budget.
