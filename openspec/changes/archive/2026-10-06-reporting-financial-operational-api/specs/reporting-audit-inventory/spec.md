# Delta for Reporting Audit Inventory

## MODIFIED Requirements

### Requirement: Existing-source anomaly and statistics coverage

Audit inventory for financial/operational reporting MUST describe anomaly and statistics coverage deterministically from existing sources only, including parking, solo lavado, monthly payment, night charge, closure, expense, and logical-deletion sources when available. The API MUST NOT add event sourcing, persisted anomaly tables, or transversal audit-log guarantees for this derivative.
(Previously: Coverage focused on historical plate reporting sources and excluded transversal audit-log guarantees.)

#### Scenario: Coverage is available for existing sources

- GIVEN existing financial and operational sources can support bounded anomaly or statistics evidence
- WHEN audit inventory coverage is returned
- THEN those sources MUST be identified as contributing coverage
- AND the response MUST NOT claim transversal audit-log guarantees

#### Scenario: Coverage source is unavailable

- GIVEN an expected existing source cannot provide historical evidence
- WHEN audit inventory coverage is returned
- THEN that source MUST be marked `partial` or `unavailable`
- AND the affected scope MUST be identified

#### Scenario: Metadata is deterministic

- GIVEN the same existing source data is evaluated twice
- WHEN anomaly or audit metadata is produced
- THEN source labels, coverage states, and unsupported-behavior markers MUST match

### Requirement: Excluded audit behaviors remain out of scope

This derivative MUST NOT add anomaly persistence, event sourcing, before/after transversal audit logs, Desktop/Mobile UI behavior, installer or release hardening, production probing, or formal accounting-ledger storage.
(Previously: Exclusions did not explicitly name formal accounting-ledger storage.)

#### Scenario: Consumer expects persisted anomaly evidence

- GIVEN a consumer requests persisted anomaly records or event-sourced history
- WHEN this derivative defines audit inventory behavior
- THEN the API MUST expose only existing-source coverage states
- AND the unsupported behavior MUST remain out of scope
