# Design: Reporting API Filters, Sorting, and Pagination

## Technical Approach

Add `GET /api/v1/reporting/reports/operations` to the existing FastAPI reporting adapter. The endpoint remains admin-only, validates `period_id` as `closure:{id}`, rejects unknown query keys, and delegates to repository helpers that return a closed-period page plus pagination metadata. Repository SQL uses fixed allow-list mappings for filters and sort expressions; user input is bound as parameters only.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Endpoint boundary | Extend `app/api/v1/endpoints/reporting.py` with one admin-only handler. | New router/module. | Existing reporting endpoints already mount under `/api/v1/reporting` and enforce `require_role("admin")`. |
| Period scope | Accept only `period_id=closure:{id}` and load `cierres_diarios` for start/end. | Support `open:*` or legacy date ranges. | The spec limits this slice to closed-period drill-down and avoids unstable live-period pagination. |
| Query validation | Validate exact query-key, filter, sort, limit, and offset allow-lists before repository calls. | Let FastAPI ignore unknown query params. | The spec requires unsupported filters/sorts/pages to be rejected, not ignored. |
| SQL construction | Build SQL from constant fragments keyed by allow-list names; bind all values. | Interpolate raw column/filter names. | Prevents unsafe dynamic SQL while still supporting controlled sort/filter variants. |

## Data Flow

Client ──→ `reporting.get_operations_report()` ──→ query validator ──→ `reporting_repo.list_operation_rows()`
  └─ auth: `require_role("admin")`                    └─ read-model pagination envelope

Repository flow: load closure window, select normalized operation rows from operational tables, apply allowed filters, count total, apply deterministic order, then limit/offset.

## File Changes

| File | Action | Description |
|---|---|---|
| `app/api/v1/endpoints/reporting.py` | Modify | Add operations endpoint, strict unknown query-key check via `Request`, period parsing, and HTTP error mapping. |
| `app/repositories/reporting_repo.py` | Modify | Add `list_operation_rows()` and closure-window helper using safe SQL fragments and bound params. |
| `app/repositories/reporting_read_models.py` | Modify | Add allow-list constants, pagination metadata builder, row serialization, and input validation helpers. |
| `tests/test_reporting_endpoints.py` | Modify | Cover admin guard, period validation, unknown filters, sort validation, and repository delegation. |
| `tests/test_reporting_read_models.py` | Modify | Cover pagination metadata, bounded limits/offsets, filter/sort validation helpers, and stable row serialization. |
| `tests/test_reporting_closed_reports.py` | Modify | Cover repository SQL behavior with mocked connections for closure lookup, count, ordering, and final page metadata. |

## Interfaces / Contracts

Endpoint query contract:

- Required: `period_id=closure:{id}`.
- Filters: `category`, `operator`, `plate` only.
- Sorting: `sort=occurred_at|amount|category`, `direction=asc|desc`; default `occurred_at asc`.
- Pagination: `limit` default `100`, max `200`; `offset` default `0`; both non-negative except `limit >= 1`.
- Response: `{period_id, filters, sort, pagination: {total, limit, offset, has_more, next_offset}, items}`.
- Row identity: `operation_id` is a stable string such as `vehicle_movement:123`; deterministic tie-breaker is always `operation_id ASC`.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Validators, metadata, row serialization | `unittest` direct helper tests in `tests/test_reporting_read_models.py`. |
| Endpoint | Admin-only access, strict query rejection, HTTP error mapping | Direct function tests with `unittest.mock.patch`, matching existing endpoint tests. |
| Repository | Closure scoping, safe params, deterministic order, count/page metadata | Mock `db_conn()` and SQLAlchemy result objects; assert parameterized calls and result envelopes. |
| E2E | Not planned | No existing E2E harness for this API slice. |

## Threat Matrix

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | N/A: no executable-file classification. | No file execution boundary. | None. |
| Git repository selection | N/A: no Git automation. | No repository/cwd authority change. | None. |
| Commit state | N/A: no commit automation. | No index/worktree semantics. | None. |
| Push state | N/A: no push automation. | No destination/ref resolution. | None. |
| PR commands | N/A: no PR automation. | No command composition. | None. |

## Migration / Rollout

No migration required. The change is API-only and does not modify Desktop, Mobile, Installer, packaging, or `printer_agent/run_agent_task.cmd`.

## Open Questions

- [ ] None.
