# Delta for Reporting Audit Inventory

## ADDED Requirements

### Requirement: Existing-source anomaly and statistics coverage

Audit inventory for historical plate reporting MUST describe anomaly and statistics coverage from existing sources only, including parking, solo-wash, monthly-payment, night-charge, closure, and logical-deletion sources when available.

#### Scenario: Coverage is available for existing sources

- GIVEN existing sources can support bounded anomaly or statistics evidence
- WHEN audit inventory coverage is returned
- THEN those sources MUST be identified as contributing coverage
- AND the response MUST NOT claim transversal audit-log guarantees.

#### Scenario: Coverage source is unavailable

- GIVEN an expected existing source cannot provide historical evidence
- WHEN audit inventory coverage is returned
- THEN that source MUST be marked `partial` or `unavailable`
- AND the affected scope MUST be identified.

### Requirement: Excluded audit behaviors remain out of scope

This derivative MUST NOT add anomaly persistence, event sourcing, before/after transversal audit logs, Desktop/Mobile UI behavior, installer or release hardening, or production probing.

#### Scenario: Consumer expects persisted anomaly evidence

- GIVEN a consumer requests persisted anomaly records or event-sourced history
- WHEN this derivative defines audit inventory behavior
- THEN the API MUST expose only existing-source coverage states
- AND the unsupported behavior MUST remain out of scope.
