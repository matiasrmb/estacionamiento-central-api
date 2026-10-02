# Proposal: Centro Inteligencia Reportes Auditoria API

## Intent

Define the API-only canonical reporting contract for roadmap 1.3.0 so Desktop/Mobile can consume consistent read models, exports, and audit-readiness signals without duplicating reporting logic.

## Scope

### In Scope
- Canonical reporting read models for operational net, capacity, closure periods, and historical completeness.
- PDF and XLSX export contract for reproducible report delivery.
- Audit inventory/readiness endpoint derived from existing sources.

### Out of Scope
- Desktop, Mobile, Installer, or cross-repository implementation.
- New audit event log storage; deferred to 1.3.x.
- Application code, migrations, dependency/version changes, branches, commits, or PRs in this proposal phase.

## Capabilities

### New Capabilities
- `canonical-reporting-api`: API contract for reusable reporting read models and endpoint behavior.
- `reproducible-reporting-exports`: PDF/XLSX export behavior and compatibility rules.
- `reporting-audit-inventory`: Audit-readiness inventory from existing API data sources.

### Modified Capabilities
- None; no existing OpenSpec capabilities were present in this API repo.

## Approach

Specify API-owned reporting semantics first, then implement later in repository-level read models and endpoint adapters. Operational net must include journey-collected mensualidades and subtract expenses. Closure-to-closure is the primary business-day semantic, including after-midnight operations before closure in the previous operational journey. Capacity is capped at 50 total spaces; effective transient capacity subtracts active monthly customers. Historical completeness must be `complete`, `partial`, or `unavailable` and must never imply incomplete history is complete.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/repositories/reporting_read_models.py` | Modified | Canonical report projections and completeness metadata. |
| `app/repositories/reporting_repo.py` | Modified | Data access for closure windows, money totals, capacity, exports, and audit inventory. |
| `app/api/v1/endpoints/reporting.py` | Modified | API contract surface for read models, exports, and audit readiness. |
| `tests/test_reporting_*.py` | Modified | Contract and regression coverage for API semantics. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Active monthly customer source is ambiguous. | Med | Treat as dependency before spec/design freeze. |
| CSV compatibility conflicts with XLSX roadmap requirement. | Med | Decide whether CSV remains compatibility-only or is rejected. |
| Historical data gaps are overstated as complete. | High | Require explicit completeness enum and scenarios. |

## Rollback Plan

Revert later API contract/spec implementation and keep existing reporting endpoints unchanged. Since this phase writes only proposal artifacts, rollback is deleting this change folder and Engram proposal topic.

## Dependencies

- Decision on authoritative active monthly customer source.
- Decision on CSV compatibility after XLSX support.
- Umbrella roadmap context: `centro-inteligencia-reportes-auditoria-13-roadmap`.

## Success Criteria

- [ ] Specs can be generated for the three listed capabilities without Desktop/Mobile implementation scope.
- [ ] API semantics cover operational net, closure journeys, capacity, completeness, exports, and audit readiness.
- [ ] Open risks are explicit before design and implementation.
