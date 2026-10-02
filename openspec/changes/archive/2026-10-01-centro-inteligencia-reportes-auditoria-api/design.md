# Design: Centro Inteligencia Reportes Auditoria API

## Technical Approach

Keep canonical reporting semantics inside the API read-model layer. `reporting.py` remains a thin FastAPI adapter, `reporting_repo.py` owns database reads and closure windows, and `reporting_read_models.py` owns response shapes, completeness, export metadata, and audit inventory composition. Desktop, Mobile, and Installer remain downstream/read-only consumers for this derivative.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Read-model ownership | API owns canonical totals, periods, capacity, completeness, and audit inventory fields. | Client recomputation; closure-table-only totals. | Specs require clients not to duplicate business semantics, while existing code already centralizes reporting adapters in `reporting_repo.py` and `reporting_read_models.py`. |
| Closure period semantics | Use closure-to-closure periods: previous `cierres_diarios.fecha_cierre` exclusive/later closure inclusive for closed reports, latest closure to now for open reports. | Calendar-day grouping; operator-session boundaries. | Current `build_operational_periods()` and `get_open_dashboard()` already model closure boundaries and support after-midnight operations. |
| Operational net | Compute `operational_net_total = transient operational income + journey-collected mensualidades - operational expenses`; expose component totals separately. | Keep mensualidades outside net; rely only on `cierres_diarios.total_neto`. | The spec requires journey-collected mensualidades in net; `cierres_repo.py` links `pagos_mensuales` to `id_cierre`, making closure-scoped monthly payments auditable. |
| Capacity | Always return `total_spaces: 50`; return effective transient capacity only after active monthly source is resolved. | Infer from current payments; add config table. | Existing monthly customer candidates are `vehiculos.tipo_cliente='mensual' AND activo=1`; this remains an open question, so no migration is planned now. |
| Exports | Add PDF and XLSX as canonical closed-report export formats with shared metadata; CSV policy is a pre-apply gate. | Keep CSV as canonical; reject CSV now. | Existing exports support CSV/PDF and tests currently reject XLSX; changing CSV behavior needs an explicit compatibility decision before apply. |
| Audit inventory | Build readiness from existing closure, operational, payment, expense, user/session, and print-job sources only. | Add transversal before/after event log. | Event log storage is explicitly deferred to 1.3.x. |

## Data Flow

```text
FastAPI /reporting/*
  -> reporting_repo.py SQL reads: cierres_diarios, ingresos, usos_bano,
     operaciones_servicio, cobros_noches, gastos_operacion, pagos_mensuales
  -> reporting_read_models.py canonical response/export/audit builders
  -> clients receive API-owned semantics without recomputation
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/api/v1/endpoints/reporting.py` | Modify | Keep admin-only endpoints thin; route closed reports, exports, and audit inventory to repo/read-model builders. |
| `app/repositories/reporting_repo.py` | Modify | Add closure-to-closure SQL helpers, monthly-payment-inclusive totals, capacity source handling, and existing-source audit reads. |
| `app/repositories/reporting_read_models.py` | Modify | Define canonical response fields, completeness enum, capacity block, export metadata, PDF/XLSX render contract, and CSV compatibility behavior after policy decision. |
| `tests/test_reporting_read_models.py` | Modify | Cover canonical net, capacity unavailable/resolved states, completeness, and closure-to-closure periods. |
| `tests/test_reporting_exports.py` | Modify | Replace XLSX rejection with PDF/XLSX contract tests after dependency decision; add CSV policy regression once decided. |
| `tests/test_reporting_endpoints.py` | Modify | Cover endpoint status codes and admin-only access for new/changed reporting contracts. |
| `tests/test_reporting_closed_reports.py` | Modify | Cover persisted closed-report semantics, closure references, monthly payments, and audit inventory states. |

## Interfaces / Contracts

Closed-report responses should include: `report_id`, `period`, `catalog_version`, `closure_reference`, `operation_totals`, `capacity`, `historical_completeness`, `operation_drill_down`, `discrepancy`, and `source_state`. `historical_completeness.status` is `complete`, `partial`, or `unavailable`; missing inputs must be named. Export metadata includes format, generation timestamp, report identity, period, closure reference, totals, completeness, catalog/template version, and source state.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Read-model math and enums | Existing unittest style with in-memory rows. |
| Repository | Closure SQL source composition | Mock `db_conn()` result mappings; avoid real DB/DDL. |
| Endpoint | Admin-only contract and errors | Direct endpoint calls with patched repo/builders. |
| Export | PDF/XLSX metadata stability and CSV decision | Deterministic builder tests; block apply while CSV policy is unresolved. |

## Threat Matrix

N/A — this design uses normal FastAPI endpoints and SQL reads only; it introduces no shell commands, subprocesses, VCS/PR automation, executable-file classification, or external process-integration boundary.

## Migration / Rollout

No schema migration planned. Add one only if the active monthly capacity source cannot be derived from existing `vehiculos` rows or if export metadata must be persisted instead of generated. No Installer work is in scope unless a later API dependency/version change is introduced.

## Open Questions

- [ ] Authoritative active monthly customer source: likely `vehiculos.tipo_cliente='mensual' AND activo=1`, but this must be confirmed before effective transient capacity is marked available.
- [ ] CSV compatibility policy after XLSX support: accept, reject, or legacy-only before apply starts.
