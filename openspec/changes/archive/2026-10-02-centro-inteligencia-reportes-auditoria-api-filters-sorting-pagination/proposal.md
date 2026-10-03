# Proposal: Reporting API Filters, Sorting, and Pagination

## Intent

Add API-only backend support for canonical reporting drill-down/list endpoints so clients can request operation rows by reporting period without client-side filtering. This continues the archived `centro-inteligencia-reportes-auditoria-api` slice and anchors on the existing closed-report drill-down href: `/api/v1/reporting/reports/operations?period_id=closure:{id}`.

## Scope

### In Scope
- Add canonical operations drill-down/list semantics for closed reporting periods.
- Define allowed filters, deterministic sorting, pagination bounds, and response metadata.
- Keep validation, admin guard behavior, repository reads, and read-model response shape API-only.

### Out of Scope
- Desktop, Mobile, Installer, and packaging changes.
- Legacy `/reportes/movimientos` retrofit except compatibility awareness.
- Open/live mutable-period pagination unless later specs prove stable semantics.
- New audit-event storage, export UI, financial UI, anomalies, or historical plate views.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `canonical-reporting-api`: Add requirements for period-scoped operation drill-down rows, filter/sort allow-lists, stable pagination metadata, and unsupported query rejection.

## Approach

Add `/api/v1/reporting/reports/operations` as a thin FastAPI adapter backed by repository allow-lists. Default to `period_id=closure:{id}`, deterministic `occurred_at asc, id asc` ordering, bounded `limit`/`offset`, and metadata such as `total`, `has_more`, and `next_offset`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/api/v1/endpoints/reporting.py` | Modified | Admin-only endpoint and query validation. |
| `app/repositories/reporting_repo.py` | Modified | Period-scoped operation reads and count query. |
| `app/repositories/reporting_read_models.py` | Modified | Canonical filter, sort, pagination metadata helpers. |
| `tests/test_reporting_*.py` | Modified | Endpoint, repository, and read-model coverage. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Unsafe dynamic SQL | Medium | Use strict filter/sort allow-lists; never interpolate raw fields. |
| Unstable pagination | Medium | Require deterministic tie-breaker ordering. |
| Legacy date semantics leak in | Low | Keep `/reportes/movimientos` out of scope. |

## Rollback Plan

Revert the API endpoint, repository/read-model helpers, delta specs, and tests for this change. Existing dashboard, closed reports, exports, and audit inventory remain from the archived API slice.

## Dependencies

- Archived `centro-inteligencia-reportes-auditoria-api` derivative and promoted API specs.

## Success Criteria

- [ ] Unsupported filters/sorts/pages are rejected consistently.
- [ ] Closed-period operation rows page deterministically with complete metadata.
- [ ] No Desktop, Mobile, Installer, or remote-operation work is introduced.
