# Historical Plate Reporting Specification

## Purpose

Define additive, admin-only API behavior for bounded per-plate history, anomaly summaries, and statistics derived from existing sources only.

## Requirements

### Requirement: Admin-only bounded plate history

The API MUST expose `GET /api/v1/reporting/plates/{plate}/history` only to administrators, MUST validate and normalize `{plate}`, and MUST require bounded query inputs that prevent broad search or unbounded scans.

#### Scenario: Administrator requests valid bounded history

- GIVEN an administrator supplies a valid plate and bounded period inputs
- WHEN the history route is requested
- THEN the API MUST return history for the normalized plate only
- AND the response MUST include the accepted bounds.

#### Scenario: Invalid or unbounded request is rejected

- GIVEN a request has an invalid plate or omits required bounds
- WHEN the history route is requested
- THEN the API MUST reject it without scanning historical tables.

#### Scenario: Non-admin request is forbidden

- GIVEN a non-admin user is authenticated
- WHEN the history route is requested
- THEN the API MUST return an authorization failure.

### Requirement: Source-labeled timeline rows

History responses MUST return timeline rows from existing parking, solo-wash, monthly-payment, night-charge, closure, and logical-deletion sources where available; each row MUST identify its source, timestamp or period, normalized plate, and relevant amount or closure reference when known.

#### Scenario: Multiple existing sources contribute rows

- GIVEN bounded data exists for the same plate in multiple sources
- WHEN history is returned
- THEN each row MUST state the source that produced it
- AND rows MUST be ordered deterministically by business time.

#### Scenario: Source has no evidence for the plate

- GIVEN one existing source has no bounded evidence for the plate
- WHEN history is returned
- THEN that source MUST NOT fabricate rows.

### Requirement: Existing-source anomaly and statistics summaries

The API MUST derive anomaly and statistics summaries only from existing sources, MUST label supporting sources, and MUST NOT create anomaly persistence, event sourcing, transversal audit logs, Desktop/Mobile UI, installer/release hardening, or production probing behavior.

#### Scenario: Summary includes source support

- GIVEN bounded existing records support statistics or anomalies
- WHEN summaries are returned
- THEN each summary MUST identify the source coverage used
- AND unsupported conclusions MUST NOT be presented as facts.

#### Scenario: Historical evidence is incomplete

- GIVEN one or more expected sources are partial or unavailable
- WHEN history or summaries are returned
- THEN `historical_completeness` MUST be `partial` or `unavailable`
- AND affected sources MUST be identified.
