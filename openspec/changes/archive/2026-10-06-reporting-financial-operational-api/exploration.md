# Exploration: reporting-financial-operational-api

## Current State

The API already has an admin-only reporting surface under `app/api/v1/endpoints/reporting.py` for metric catalog, dashboard, closed reports, audit inventory, plate history, and PDF/XLSX/legacy CSV exports. The current reporting implementation is additive and read-only: endpoint functions delegate to `reporting_repo.py`, while `reporting_read_models.py` shapes canonical-ish responses, capacity metadata, historical completeness, audit inventory, and export payloads.

The existing implementation is close to the requested financial/operational behavior, but it still uses earlier metric names (`operational_income_total`, `operational_net_total`, `mensualidad_sales_total`) instead of the downstream handoff names (`collected_sources_total`, `net_revenue_total`, `monthly_payments_collected_total`). Closed reports already aggregate parking, bathroom, charged solo-wash, paid night charges, monthly payments linked to the closure, and expenses; net is computed as collected sources plus monthly payments minus expenses. Solo washes are counted only when `estado = 'FINALIZADO_COBRADO'` and not generated from a parking stay; active/uncharged washes are excluded.

Capacity is currently hardcoded to 50 and resolved from active monthly vehicles, not configurable. Historical completeness exists, but historical capacity gaps are not labeled as `historical-capacity-limited`. Audit inventory and plate-history coverage are deterministic and derived from existing sources only; there is no event sourcing, no persisted anomaly table, and no formal accounting ledger behavior.

## Affected Areas

- `app/api/v1/endpoints/reporting.py` — admin-only route guards are already present; future financial/operational routes or filters should keep unsupported filters as 422 and validate period identifiers before repository reads.
- `app/repositories/reporting_read_models.py` — owns metric catalog names, response fields, capacity/completeness labels, deterministic anomaly summaries, and export metadata.
- `app/repositories/reporting_repo.py` — owns closure reads, collected-source SQL, monthly-payment closure attribution, expenses, active monthly capacity count, and audit source coverage.
- `app/repositories/accounting_contracts.py` — centralizes closure/report accounting rules for collected sources, charged solo washes, monthly payments, expenses, and net totals.
- `app/repositories/cierres_repo.py` — links monthly payments, expenses, bathroom uses, night charges, and charged solo washes to closures; important for collected-in-journey semantics.
- `tests/test_reporting_read_models.py` — current metric catalog, capacity, completeness, audit, and plate-history read-model coverage; should receive canonical-name and historical-capacity assertions.
- `tests/test_reporting_closed_reports.py` — current closed-report repository coverage; should receive canonical net/collected-source and bad closure/period identifier tests.
- `tests/test_reporting_endpoints.py` — current route guard and 422/404 coverage; should receive unsupported filter and period-id validation coverage for any new reporting routes.
- `tests/test_reporting_exports.py` — current PDF/XLSX/legacy CSV coverage; should remain non-blocking for this 1.3.0 derivative unless export metadata names change.
- `tests/test_accounting_report_contracts.py` — already protects charged solo-wash and net accounting semantics.
- `openspec/specs/canonical-reporting-api/spec.md` — existing source-of-truth reporting semantics; needs delta coverage for renamed financial/operational metrics and safe identifier handling.
- `openspec/specs/reproducible-reporting-exports/spec.md` — existing export source of truth; likely only needs a note that PDF/XLSX are non-blocking for this derivative if retained out of scope.
- `openspec/specs/reporting-audit-inventory/spec.md` — existing audit inventory source of truth; needs financial/operational deterministic anomaly/audit slice wording if this change owns it.

## Approaches

1. **Canonical-name compatibility layer** — Add/rename response fields and metric catalog entries to the downstream handoff names while keeping current repository accounting semantics.
   - Pros: Smallest API derivative; preserves current tested SQL/accounting behavior; directly unblocks Desktop/Mobile/Installer contracts.
   - Cons: Needs a compatibility decision for old metric names in existing responses; may require temporary aliases to avoid breaking current consumers.
   - Effort: Medium

2. **Full financial/operational report endpoint set** — Add dedicated financial/operational endpoints with canonical fields, strict filter validation, period validation, capacity status labels, and deterministic audit/anomaly slice.
   - Pros: Clean API contract for downstream clients; avoids overloading historical plate endpoints; allows explicit 422 behavior for unsupported filters and malformed period identifiers.
   - Cons: Larger implementation and review footprint; must be split carefully under the 400-line review policy.
   - Effort: Medium/High

3. **Accounting/event-sourcing subsystem** — Introduce persisted financial snapshots, formal accounting concepts, or event-sourced anomaly records.
   - Pros: Strongest audit trail and reproducibility.
   - Cons: Explicitly outside the handoff; high migration risk; conflicts with the current existing-source-only reporting direction.
   - Effort: High

## Recommendation

Use Approach 2, implemented as small review slices, while explicitly preserving Approach 1 compatibility where current response fields already exist. The proposal should define API-owned financial and operational reporting behavior around canonical metric names, existing-source calculations, safe filter/period validation, configurable capacity with current default 50, and deterministic audit/anomaly metadata. Do not introduce formal accounting, event sourcing, persisted anomaly records, or blocking PDF/XLSX implementation work in this derivative.

Suggested proposal scope:

- Add or normalize canonical metric names: `collected_sources_total`, `operational_expense_total`, `net_revenue_total`, `monthly_payments_collected_total`, and `vehicle_movement_count`.
- Define `net_revenue_total` as all collected sources minus operational expenses, including monthly payments collected in the closure/journey where `fecha_pago` was linked/collected.
- Keep charged solo-wash revenue in collected sources and exclude uncharged active washes.
- Require unsupported reporting filters to fail with 422 across new financial/operational routes.
- Require bad closure IDs and bad period identifiers to fail safely without fabricated reports.
- Make capacity configurable with current default 50 and label historical capacity gaps as `historical-capacity-limited`.
- Keep anomaly/audit output deterministic from existing sources only; exclude event sourcing and formal accounting.
- Treat PDF/XLSX exports as non-blocking for this derivative; keep CSV legacy-only if retained.

## Risks

- Current API fields use earlier metric names, so changing names without aliases may break existing reporting clients or tests.
- Capacity is hardcoded today; making it configurable may touch settings/config paths outside reporting and increase review size.
- `get_audit_inventory(period_id)` currently accepts arbitrary period strings, so safe period validation must be designed before downstream clients depend on it.
- Historical capacity labeling is absent today; proposal/spec must define when `historical-capacity-limited` applies without implying missing data is complete.
- The requested canonical behavior can exceed the 400 changed-line review policy if endpoints, repository SQL, read models, tests, and specs are implemented in one slice.

## Ready for Proposal

Yes. Proceed to `sdd-propose` for an API-only financial/operational reporting derivative that canonicalizes metrics and validation behavior on top of the existing reporting read-model/repository architecture.

## Files Read

- `app/api/v1/endpoints/reporting.py`
- `app/repositories/reporting_read_models.py`
- `app/repositories/reporting_repo.py`
- `app/repositories/accounting_contracts.py`
- `app/repositories/cierres_repo.py`
- `tests/test_reporting_read_models.py`
- `tests/test_reporting_closed_reports.py`
- `tests/test_reporting_endpoints.py`
- `tests/test_reporting_exports.py`
- `tests/test_accounting_report_contracts.py`
- `openspec/config.yaml`
- `openspec/specs/canonical-reporting-api/spec.md`
- `openspec/specs/reproducible-reporting-exports/spec.md`
- `openspec/specs/reporting-audit-inventory/spec.md`
- `openspec/changes/archive/2026-10-01-centro-inteligencia-reportes-auditoria-api/archive-report.md`
- `openspec/changes/archive/2026-10-04-centro-inteligencia-reportes-auditoria-api-historical-anomalies-statistics/exploration.md`

## Key Findings

- Admin reporting route guards already use `require_role("admin")` on reporting endpoints.
- Dashboard unsupported filters already return 422, but this pattern is not generalized across future financial/operational filters.
- Closed reports return 404 for unknown closure IDs; arbitrary audit `period_id` strings are not validated today.
- Existing accounting includes charged solo washes, monthly payments, bathroom uses, night charges, and expenses; active washes are excluded from collected totals.
- Current metric names do not match the downstream handoff names and should be canonicalized in the proposal/spec.
