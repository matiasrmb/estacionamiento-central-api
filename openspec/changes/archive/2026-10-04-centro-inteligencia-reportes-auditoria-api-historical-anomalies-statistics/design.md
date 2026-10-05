# Design: Historical Plate History, Anomalies, and Statistics API

## Technical Approach

Add one admin-only reporting route: `GET /api/v1/reporting/plates/{plate}/history?start=<iso>&end=<iso>&limit=500`. The endpoint validates role, plate, and bounds before repository access, then delegates to `reporting_repo.get_plate_history(...)`. The repository reads existing sources only and passes normalized rows to `reporting_read_models` builders for deterministic timeline, anomaly summary, statistics, source coverage, and `historical_completeness`.

## Architecture Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|
| Endpoint contract | One plate-scoped history endpoint that returns timeline plus derived summaries/statistics. | Separate anomaly/statistics endpoints. | The specs require bounded per-plate history and summaries; a single bounded read avoids extra route surface and keeps all derived claims tied to the same source coverage. |
| Authorization and validation boundary | Keep `Depends(require_role("admin"))`; call `require_valid_plate(plate)` and reject missing/invalid `start`, `end`, or excessive windows before repository calls. | Validate in repository only. | Existing reporting routes are endpoint-gated; pre-query rejection proves invalid or unbounded requests do not scan historical tables. |
| Bounds | Require `start < end`, cap window to 366 days, and cap returned timeline rows with `limit` in `1..500`. | Permit closure-only period IDs or unlimited history. | Date bounds are explicit, portable for clients, and prevent broad free-text or unbounded table scans. |
| Source completeness | Use per-source coverage states: `available`, `partial`, `unavailable`; derive overall completeness as weakest state mapped to `complete`, `partial`, `unavailable`. | Hide unavailable sources or infer completeness from rows only. | Specs require unsupported conclusions to remain visible rather than fabricated as facts. |

## Data Flow

```text
FastAPI route ──validate auth/plate/bounds──→ reporting_repo.get_plate_history
     │                                                   │
     │                                      bounded SELECTs by normalized plate
     │                                                   │
     └──────────── reporting_read_models.build_plate_history_response ← rows/coverage
```

## File Changes

| File | Action | Description |
|---|---|---|
| `app/api/v1/endpoints/reporting.py` | Modify | Add route, query validation, `ValueError` to 422 mapping, and repository delegation. |
| `app/repositories/reporting_repo.py` | Modify | Add bounded source queries for `ingresos`/`vehiculos`, `operaciones_servicio`, `pagos_mensuales`, `cobros_noches`, `cierres_diarios`, and `ingresos_eliminados`; tolerate missing optional tables as `unavailable`. |
| `app/repositories/reporting_read_models.py` | Modify | Add builders for timeline rows, anomaly summaries, statistics, source coverage, and completeness. |
| `tests/test_reporting_endpoints.py` | Modify | Add admin-only, invalid plate, missing bounds, excessive window, and repository delegation tests. |
| `tests/test_reporting_read_models.py` | Modify | Add deterministic ordering, completeness, summaries, statistics, and coverage tests. |

## Interfaces / Contracts

Response shape:

```json
{
  "plate": "AB123CD",
  "bounds": {"start": "...", "end": "...", "limit": 500},
  "timeline": [{"source": "parking", "occurred_at": "...", "period": null, "amount": 1000, "closure_id": 18}],
  "anomaly_summary": [{"code": "source_unavailable", "sources": ["night_charges"], "severity": "info"}],
  "statistics": {"timeline_row_count": 1, "total_amount": 1000, "sources_with_rows": ["parking"]},
  "source_coverage": [{"source": "parking", "state": "available"}],
  "historical_completeness": {"status": "partial", "missing_ranges": [], "unavailable_inputs": []}
}
```

Timeline `source` values: `parking`, `solo_wash`, `monthly_payment`, `night_charge`, `closure`, `logical_deletion`. Sort by business time ascending, then source, then stable id.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Read-model ordering, coverage, completeness, anomaly/statistic derivation. | `python -m unittest tests.test_reporting_read_models` |
| Endpoint | Admin dependency, validation-before-repository, error mapping, delegation args. | `python -m unittest tests.test_reporting_endpoints` with patched repository. |
| Regression | Existing reporting contracts remain stable. | `python -m unittest discover tests` when implementation is complete. |

## Threat Matrix

| Boundary | Applicability | Design response | Planned RED tests |
|---|---|---|---|
| Documentation-like paths | N/A: no executable-file classification. | No behavior added. | None. |
| Git repository selection | N/A: no VCS command execution. | No behavior added. | None. |
| Commit state | N/A: no commit automation. | No behavior added. | None. |
| Push state | N/A: no push automation. | No behavior added. | None. |
| PR commands | N/A: no PR automation. | No behavior added. | None. |

## Migration / Rollout

No migration required. This is additive, read-only API behavior. If implementation forecasts over 400 changed lines, split into PR 1 read-model/validation tests and helpers, PR 2 repository/endpoint wiring.

## Rollback Boundary

Remove the route, repository method, read-model builders, and focused tests. No persisted data or schema rollback is required.

## Open Questions

- [ ] None blocking.
