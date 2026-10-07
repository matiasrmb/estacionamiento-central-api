# Tasks: Reporting Financial Operational API

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 430-620 authored lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 read models -> PR 2 validation/totals -> PR 3 audit/export regression |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Canonical read-model fields, aliases, capacity labels | PR 1 | `python -m unittest tests.test_reporting_read_models` | N/A: read-model unit scope | Revert `app/repositories/reporting_read_models.py` and its tests |
| 2 | Safe endpoint/repository validation and canonical totals | PR 2 | `python -m unittest tests.test_reporting_endpoints tests.test_reporting_closed_reports tests.test_accounting_report_contracts` | `python -m unittest tests.test_reporting_closed_reports` | Revert `app/api/v1/endpoints/reporting.py`, `app/repositories/reporting_repo.py`, `app/repositories/accounting_contracts.py`, and paired tests |
| 3 | Deterministic audit/export metadata and full regression | PR 3 | `python -m unittest tests.test_reporting_exports tests.test_reporting_read_models` | `python -m unittest discover tests` | Revert export/audit metadata changes and paired tests |

## Phase 1: Read Models and Contract Shape

- [x] 1.1 RED: extend `tests/test_reporting_read_models.py` for canonical metrics, legacy alias equality, default capacity `50`, and `historical-capacity-limited`.
- [x] 1.2 GREEN: update `app/repositories/reporting_read_models.py` with canonical constants, alias mapping, capacity helpers, and historical limitation metadata.
- [x] 1.3 REFACTOR: keep API/Mobile/Desktop/Installer boundaries explicit; do not edit `printer_agent/run_agent_task.cmd`.

## Phase 2: Validation and Accounting Totals

- [x] 2.1 RED: extend `tests/test_reporting_endpoints.py` so malformed `period_id` and unsupported filters fail before repository calculation.
- [x] 2.2 RED: extend `tests/test_reporting_closed_reports.py` and `tests/test_accounting_report_contracts.py` for unknown closures, mensualidad closure timing, charged solo lavado inclusion, and active wash exclusion.
- [x] 2.3 GREEN: update `app/api/v1/endpoints/reporting.py` with period, closure, and filter validation returning safe error responses.
- [x] 2.4 GREEN: update `app/repositories/reporting_repo.py` and `app/repositories/accounting_contracts.py` to return canonical totals while preserving current SQL source rules.
- [x] 2.5 REFACTOR: remove duplicate metric-name logic without changing storage, migrations, ledgers, or event sourcing.

## Phase 3: Audit, Export, and Verification

- [x] 3.1 RED: extend `tests/test_reporting_read_models.py` for deterministic existing-source audit coverage, partial/unavailable states, and unsupported persisted anomaly/event-sourcing markers.
- [x] 3.2 RED: extend `tests/test_reporting_exports.py` for PDF/XLSX non-blocking metadata and CSV `legacy-only`/non-canonical labeling.
- [x] 3.3 GREEN: update `app/repositories/reporting_read_models.py` export and audit metadata builders to satisfy the scenarios.
- [x] 3.4 VERIFY: run `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports tests.test_reporting_exports tests.test_accounting_report_contracts`.
- [x] 3.5 VERIFY: run `python -m unittest discover tests` before handoff.
