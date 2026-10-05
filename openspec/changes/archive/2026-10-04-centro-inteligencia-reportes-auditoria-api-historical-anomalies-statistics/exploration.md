# Exploration: centro-inteligencia-reportes-auditoria-api-historical-anomalies-statistics

## Current State

The API already has a canonical reporting surface under `GET /api/v1/reporting/*` with admin-only access, closed-report identity, closure-to-closure periods, capacity metadata, historical completeness markers, existing-source audit inventory, and export metadata. In the inspected local `master` tree, `app/api/v1/endpoints/reporting.py` exposes metric catalog, dashboard, closed report, audit inventory, and exports; it does not expose a concrete `GET /reporting/reports/operations` endpoint even though closed reports return a drill-down href for that route.

Legacy reporting remains available under `GET /api/v1/reportes/movimientos`, backed by `app/repositories/reportes_repo.py`. That endpoint supports date-range and exact plate filtering and already joins parking exits, solo washes, monthly payments, night charges, bathroom uses, and expenses into a mixed movement list. It is calendar-date based, not closure-period based, and does not provide a canonical per-plate history contract or anomaly/statistics read model.

Plate normalization/validation exists in `app/core/plates.py` and is already used by write paths. Reporting code currently uppercases the plate filter directly in `reportes_repo.py`; a canonical plate-history API should reuse the shared plate validator to avoid broad or ambiguous historical queries.

Historical/anomaly/statistics capabilities are partial only. Existing code can derive plate movement history from `ingresos`, solo washes from `operaciones_servicio`, monthly payments from `pagos_mensuales`, night charges from `cobros_noches`, logical deletion state from `ingresos_eliminados`, and closure windows from `cierres_diarios`. There is no durable anomaly table, no full event-sourcing audit log, and no current API contract for anomaly classification, recurrent-plate statistics, dwell-time outliers, missing closure linkage, or dashboard-grade historical statistics.

The local working tree has one unrelated modification: `printer_agent/run_agent_task.cmd`. This exploration did not read, edit, stage, restore, or include that file.

## Affected Areas

- `app/api/v1/endpoints/reporting.py` — likely home for new admin-only API-first routes such as plate history and reporting statistics/anomalies.
- `app/repositories/reporting_repo.py` — owns persisted reporting reads and should derive closure-scoped rows/statistics from database sources.
- `app/repositories/reporting_read_models.py` — owns canonical response shaping and should define stable plate-history, anomaly, and statistics read models.
- `app/repositories/reportes_repo.py` — existing legacy calendar-date movement report; useful source pattern but should not be expanded as the canonical API-first surface.
- `app/core/plates.py` — existing plate normalization/validation that should gate plate-history requests.
- `app/repositories/cierres_repo.py` — closure-to-closure period source and cierre linkage behavior for reports/statistics.
- `app/repositories/ingresos_repo.py` — current parking entry/active-row source and plate/vehicle relationship behavior.
- `app/repositories/mensuales_repo.py` — monthly-customer/payment source for per-plate commercial history and capacity context.
- `app/db/migrations/002_operaciones_servicio_state.sql` — solo-wash historical source indexed by plate.
- `app/db/migrations/005_monthly_payments.sql` — monthly payment historical source linked to vehicles.
- `app/db/migrations/006_cobros_noches.sql` — night-charge historical source linked to ingresos.
- `app/db/migrations/014_gastos_operacion_auditoria.sql` — existing narrow audit table; confirms full transversal event log is not present.
- `tests/test_reporting_read_models.py` — current read-model contract tests and natural home for new read-model tests.
- `tests/test_reporting_endpoints.py` — current endpoint contract/auth tests and natural home for new reporting route tests.
- `tests/test_reporting_closed_reports.py` — current repository/read-model reporting tests and useful pattern for closure-aware assertions.
- `tests/test_monthly_payments.py` — verifies legacy plate-filtered reports include monthly payments and totals.

## Approaches

1. **Bounded API contract + derived read models** — Add canonical admin-only contracts for plate history and aggregate anomaly/statistics derived from existing tables only.
   - Pros: Fits the current API-first reporting architecture; avoids new persistence; keeps Mobile/Desktop integration-ready through stable contracts; review scope can be split under 400 changed lines.
   - Cons: Anomalies are derived heuristics, not audited events; completeness must remain explicit where history is missing or calendar-based sources are reused.
   - Effort: Medium

2. **Legacy report expansion** — Extend `GET /reportes/movimientos` with more filters, statistics, and anomaly flags.
   - Pros: Reuses an existing endpoint and query path; fastest implementation path.
   - Cons: Couples new API-first consumers to a legacy calendar-date contract; does not align with closure-to-closure reporting semantics; risks large mixed-query changes.
   - Effort: Medium

3. **New anomaly/audit persistence layer** — Introduce durable anomaly snapshots or event/audit tables and expose reporting APIs from those tables.
   - Pros: Stronger auditability and repeatability for anomaly investigations.
   - Cons: Larger schema/migration and backfill problem; out of line with the first derivative scope and the archived decision to defer transversal audit logs.
   - Effort: High

## Recommendation

Use Approach 1 for the first API derivative. Scope the proposal to API-owned contracts and derived read models, not a new persistence subsystem. Recommended first derivative scope:

- Add a canonical plate-history route under the reporting API, for example `GET /api/v1/reporting/plates/{plate}/history`, admin-only, using shared plate normalization/validation.
- Return a stable timeline that can include parking stays, solo washes, monthly payments, and night charges where available, with source labels, timestamps, amounts, closure references when known, and `historical_completeness`.
- Add aggregate statistics/anomaly route(s), for example `GET /api/v1/reporting/anomalies` and/or `GET /api/v1/reporting/statistics`, derived from existing reporting sources.
- Keep anomaly categories intentionally small for the first derivative: closure discrepancy already exposed by closed reports, missing/unlinked closure source state, unusually long stay duration, repeated plate activity, and incomplete-history flags.
- Reuse closure-to-closure period semantics where `period_id=closure:{id}` is supplied; allow carefully bounded date ranges only when explicitly marked as calendar-based or partial.
- Keep Mobile independently usable by designing additive, read-only API contracts. Do not require Mobile/Desktop implementation in this derivative.

Recommended out of scope for the first derivative:

- New anomaly persistence tables or event-sourcing/audit-log guarantees.
- Desktop/Mobile UI implementation.
- Installer/release hardening.
- Remote operations, database service execution, or production data probing.
- Broad free-text plate search or unbounded historical scans.
- Financial ledger/tax/payment-method accounting semantics already excluded from the metric catalog.

## Likely Test Commands

- Full repository test command: `python -m unittest discover tests`.
- Focused likely commands for later phases:
  - `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports`
  - Add a new focused repository test module if the implementation introduces query-heavy history/statistics logic.

## Risks

- The inspected local `master` tree does not contain the completed filters/sorting/pagination operations endpoint referenced by prior session memory, so proposal/design should verify whether the current working tree is intentionally behind before depending on that endpoint.
- Query size can exceed the 400 changed-line review policy if plate history, anomaly statistics, endpoint wiring, and repository SQL are implemented together; split into read-model/validation and endpoint/repository slices if needed.
- Historical completeness must not be overstated because legacy reports are calendar-date based and some sources only become closure-linked after daily close.
- Anomaly definitions can drift into product policy; proposal should name only mechanical, source-backed anomalies and defer business thresholds unless accepted.
- Plate-history endpoints must reject invalid/unbounded requests to avoid expensive scans and accidental broad data exposure.

## Ready for Proposal

Yes. The orchestrator should proceed to `sdd-propose` with a bounded API-first derivative centered on canonical plate history plus source-backed anomaly/statistics summaries, explicitly excluding new anomaly persistence, full transversal audit logs, and client UI work.
