# Proposal: Historical Plate History, Anomalies, and Statistics API

## Intent

Provide additive, admin-only reporting contracts for canonical plate history and source-backed anomaly/statistics summaries, without new persistence or client UI work.

## Scope

### In Scope
- Add `GET /api/v1/reporting/plates/{plate}/history` using shared plate validation/normalization.
- Derive plate timeline rows from existing parking, solo-wash, monthly-payment, night-charge, closure, and logical-deletion sources where available.
- Add source-backed anomaly/statistics summaries from existing tables only, with explicit `historical_completeness` and source coverage markers.
- Keep contracts read-only and additive for future Desktop/Mobile consumption.

### Out of Scope
- New anomaly persistence tables, event sourcing, or transversal audit logs.
- Desktop/Mobile UI, installer/release hardening, remote/prod data probing.
- Broad free-text plate search or unbounded historical scans.

## Capabilities

### New Capabilities
- `historical-plate-reporting`: Canonical admin-only per-plate history and derived anomaly/statistics reporting contracts.

### Modified Capabilities
- `canonical-reporting-api`: Add bounded plate-history/statistics behavior to the existing API-only reporting contract and historical completeness rules.
- `reporting-audit-inventory`: Clarify existing-source anomaly/statistics coverage without transversal audit-log guarantees.

## Approach

Use the existing `reporting` API boundary. Validate `{plate}` through `app/core/plates.py`, reject invalid plates, and require bounded period/date inputs for summary routes. Implement read-model builders that label each row/statistic with source, timestamp/period, amount when relevant, closure reference when known, and completeness (`complete`, `partial`, `unavailable`).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/api/v1/endpoints/reporting.py` | Modified | Add admin-only read routes. |
| `app/repositories/reporting_repo.py` | Modified | Query existing sources only. |
| `app/repositories/reporting_read_models.py` | Modified | Shape stable timeline, anomaly, statistics payloads. |
| `app/core/plates.py` | Reused | Shared validation/normalization gate. |
| `tests/test_reporting_endpoints.py` | Modified | Auth, validation, contract tests. |
| `tests/test_reporting_read_models.py` | Modified | Completeness and payload-shape tests. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Historical gaps overstated as complete | Med | Require completeness/source coverage markers. |
| Query scope grows too large | Med | Reject invalid plates and unbounded scans. |
| Review exceeds 400 changed lines | Med | Split read-model/validation from endpoint/repository work later. |

## Rollback Plan

Remove the new routes, repository methods, read-model builders, and tests. No schema migration or data rollback is needed.

## Dependencies

- Existing reporting, closure, plate, payment, wash, night-charge, and deletion tables.
- No external service, remote database, or new library dependency.

## Success Criteria

- [ ] Admin-only plate-history route returns normalized, source-labeled, bounded history.
- [ ] Anomaly/statistics summaries are derived only from existing sources.
- [ ] Responses expose historical completeness and unavailable/partial inputs.
- [ ] Desktop/Mobile can consume contracts later without API-breaking changes.
