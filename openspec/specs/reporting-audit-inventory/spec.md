# Reporting Audit Inventory Specification

## Purpose

Define API-only audit-readiness inventory derived from existing API data sources. Full transversal before/after audit event logging is deferred to 1.3.x and MUST NOT be implemented by this derivative.

## Requirements

### Requirement: Existing-source audit inventory

The API MUST expose audit inventory using existing reporting, closure, expense, payment, and operational sources, without requiring new transversal audit-event storage.

#### Scenario: Inventory from available sources

- GIVEN existing API sources contain closure, payment, expense, and operational records
- WHEN audit inventory is requested
- THEN the API MUST report available audit coverage by source
- AND it MUST identify sources that are unavailable

### Requirement: Coverage states

Each audit inventory area MUST expose coverage as available, partial, or unavailable, and MUST NOT present unknown coverage as available.

#### Scenario: Missing source coverage

- GIVEN one inventory source cannot provide historical evidence
- WHEN inventory coverage is returned
- THEN that area MUST be marked `unavailable` or `partial`
- AND the response MUST identify the affected scope

### Requirement: Closure-based audit periods

Audit inventory MUST use closure-to-closure periods for operational audit reporting, including after-midnight operations before closure in the previous journey.

#### Scenario: Audit period crosses midnight

- GIVEN an operation occurs after midnight before closure
- WHEN audit inventory is calculated for the open journey
- THEN the operation MUST belong to the journey started the previous calendar day

### Requirement: Deferred transversal audit log

The API MUST NOT implement full before/after transversal audit event logs in this 1.3.0 derivative.

#### Scenario: Consumer requests event-log guarantees

- GIVEN a consumer requests before/after audit event history
- WHEN this derivative defines audit behavior
- THEN the API MUST expose only existing-source inventory coverage
- AND full event-log guarantees MUST remain deferred to 1.3.x
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
