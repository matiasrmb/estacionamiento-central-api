# Design: Reporting Financial Operational API

## Technical Approach

Keep the existing FastAPI endpoint -> repository -> read-model shape. The change normalizes reporting names and validation at the API/read-model boundary while preserving the SQL accounting semantics already in `reporting_repo.py`, `accounting_contracts.py`, and `cierres_repo.py`. It implements the delta specs for canonical metrics, safe input failures, existing-source audit metadata, and non-blocking exports without adding storage, migrations, ledger behavior, or event sourcing.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Metric mapping and aliases | Centralize canonical names, legacy aliases, and catalog entries in `app/repositories/reporting_read_models.py`; repositories return canonical keys plus feasible aliases. | Rename SQL-only fields in `reporting_repo.py`; add endpoint-only remapping. | Read models already own catalog/response shape; one mapping prevents alias drift across dashboard, closed reports, and exports. |
| Accounting preservation | Keep collected-source SQL and closure linkage rules in `reporting_repo.py`/`cierres_repo.py`; keep charged solo lavado rules in `accounting_contracts.py`. | Recompute with new accounting storage. | Current code already includes bathroom, parking, paid night charges, charged solo lavado, monthly payments linked by `id_cierre`, expenses, and excludes active washes. |
| Input validation | Add reporting-period parsing helpers in `app/api/v1/endpoints/reporting.py`; reject malformed `period_id`, unknown `closure_id`, and unsupported filters before repository reads where possible. | Let repository return empty defaults. | Specs require no fabricated reports; endpoint tests can prove repository functions are not called on invalid inputs. |
| Capacity | Replace scattered literal `50` with read-model capacity helpers that accept configured total defaulting to `50`; represent historical gaps through `historical_completeness.unavailable_inputs` including `historical-capacity-limited`. | Database migration for capacity history. | Keeps the derivative API-only and truthfully labels missing historical evidence. |
| Audit/anomaly metadata | Continue deriving audit inventory from `_source_state` over existing tables only; unsupported behaviors remain explicit. | Persist anomaly records or audit logs. | Matches non-goals and keeps output deterministic from source availability. |
| Exports | Leave PDF/XLSX roadmap-compatible but non-blocking; keep CSV marked `legacy-only` and not canonical. | Make export delivery block canonical API. | Spec says API fields are the source of truth and export work must not delay this derivative. |

## Data Flow

    reporting.py validates identifiers/filters
        -> reporting_repo.py reads closure/current existing sources
        -> reporting_read_models.py maps canonical metrics, aliases, capacity, audit/export metadata
        -> API returns canonical fields with temporary legacy aliases

Net revenue remains: `collected_sources_total + monthly_payments_collected_total - operational_expense_total`. Monthly payments use closure collection timing (`pagos_mensuales.id_cierre`). Charged solo lavado uses `estado = 'FINALIZADO_COBRADO'` and solo rows (`id_ingreso_generado IS NULL` where applicable); active/unpaid washes stay excluded.

## File Changes

| File | Action | Description |
|---|---|---|
| `app/api/v1/endpoints/reporting.py` | Modify | Period/closure/filter validation and 422/404 translation. |
| `app/repositories/reporting_read_models.py` | Modify | Canonical metric constants, legacy aliases, capacity helper/default, historical capacity label, export metadata names. |
| `app/repositories/reporting_repo.py` | Modify | Return canonical totals while preserving SQL source rules and active monthly lookup. |
| `app/repositories/accounting_contracts.py` | Modify | Add/keep regression-protected canonical naming helpers if needed; preserve charged solo lavado semantics. |
| `tests/test_reporting_*.py`, `tests/test_accounting_report_contracts.py` | Modify | Unit/integration regression coverage. |

## Interfaces / Contracts

Canonical `metrics` and `closure_reference.metrics` include `collected_sources_total`, `operational_expense_total`, `net_revenue_total`, `monthly_payments_collected_total`, and `vehicle_movement_count`. Temporary aliases remain: `operational_income_total`, `operational_net_total`, `mensualidad_sales_total`. Capacity includes `total_spaces`, `reserved_monthly_spaces`, `effective_transient_capacity`, `source_state`, and historical `unavailable_inputs` may contain `historical-capacity-limited`.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Metric alias equality, capacity default/config, historical-capacity-limited, deterministic audit metadata, export compatibility. | Extend `test_reporting_read_models.py` and `test_reporting_exports.py`. |
| Integration | Closed-report totals, mensualidad closure timing, charged solo lavado inclusion, active wash exclusion, unknown closure. | Extend `test_reporting_closed_reports.py` with mocked DB rows. |
| Endpoint | Unsupported filters and malformed period IDs fail before repository reads. | Extend `test_reporting_endpoints.py` with mocked repositories. |
| E2E | Not available in this repo. | Use `python -m unittest discover tests`. |

## Threat Matrix

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | N/A: no executable-file classification. | None. | None. |
| Git repository selection | N/A: no VCS automation. | None. | None. |
| Commit state | N/A: no commit automation. | None. | None. |
| Push state | N/A: no push automation. | None. | None. |
| PR commands | N/A: no PR automation. | None. | None. |

## Migration / Rollout

No migration required. Deliver as review slices under 400 changed lines: (1) read-model canonical names/capacity/export metadata, (2) endpoint/repository validation and totals, (3) regression tests and spec traceability cleanup if needed.

## Open Questions

None.
