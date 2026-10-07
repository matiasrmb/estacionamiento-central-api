# Proposal: Reporting Financial Operational API

## Intent

Establish the API as the canonical backend contract for financial/operational reports so downstream apps consume stable metrics, validation, capacity semantics, and deterministic audit/anomaly metadata.

## Problem

Current reporting is close, but names predate the handoff, capacity lacks historical labels, and period/filter validation is inconsistent.

## Goals

- Canonicalize metric names and responses.
- Preserve old names as compatibility aliases where feasible.
- Add configurable capacity with default `50` and `historical-capacity-limited` labeling.
- Reject bad period IDs, closure IDs, and unsupported filters without fabricated reports.
- Keep audit/anomaly output deterministic from existing sources.

## Non-goals

- No accounting ledger, event sourcing, persisted anomaly table, or transversal audit log.
- No Desktop, Mobile, Installer, production, database, or remote work.
- PDF/XLSX is non-blocking; CSV remains legacy-only/non-canonical if retained.

## Scope

- `app/api/v1/endpoints/reporting.py`: admin inputs and 422 unsupported filters.
- `app/repositories/reporting_read_models.py`: metric catalog, aliases, capacity labels.
- `app/repositories/reporting_repo.py`: calculations, period validation, capacity lookup.
- `app/repositories/accounting_contracts.py`: preserve net/collected-source rules.

## Compatibility / Alias Strategy

Canonical fields: `collected_sources_total`, `operational_expense_total`, `net_revenue_total`, `monthly_payments_collected_total`, `vehicle_movement_count`. Existing names (`operational_income_total`, `operational_net_total`, `mensualidad_sales_total`) SHOULD remain temporary aliases where feasible; new clients use canonical names only.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `canonical-reporting-api`: names, aliases, capacity, historical limitation, identifier/filter validation.
- `reporting-audit-inventory`: deterministic audit/anomaly coverage.
- `reproducible-reporting-exports`: PDF/XLSX non-blocking; CSV legacy-only/non-canonical if retained.

## Approach

Use existing endpoint/read-model/repository architecture. Add names and validation before repository changes. Do not add accounting storage.

## Suggested Split / Review Boundary

1. Spec/contract, aliases, capacity labels.
2. Endpoint/repository validation.
3. Regression tests and export metadata clarification.

Each slice should stay under 400 changed lines.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/api/v1/endpoints/reporting.py` | Modified | Validation and admin contract. |
| `app/repositories/reporting_read_models.py` | Modified | Names, aliases, capacity labels. |
| `app/repositories/reporting_repo.py` | Modified | Calculations and period handling. |
| `tests/test_reporting_*.py` | Modified | Regression coverage. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Alias drift | Medium | Test aliases and canonical fields together. |
| Capacity config spread | Medium | Keep default `50`; isolate config read. |
| Over 400 lines | Medium | Use the split above. |

## Open Questions

- No product decisions remain unresolved.

## Rollback Plan

Revert proposal/specs and implementation slices; aliases let consumers keep prior names if canonical fields are delayed.

## Dependencies

- Reporting repositories, closure linkage, unittest coverage.

## Success Criteria

- [ ] Canonical fields are documented and returned without client recomputation.
- [ ] Old metric aliases remain compatible where feasible.
- [ ] Bad period IDs/unsupported filters fail safely.
- [ ] Capacity default/configuration and `historical-capacity-limited` are covered.
