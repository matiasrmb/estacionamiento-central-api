# Delta for Canonical Reporting API

## ADDED Requirements

### Requirement: Bounded plate-history reporting route

The reporting API MUST provide an admin-only, read-only plate-history contract that validates and normalizes plate input, requires explicit bounded query inputs, and rejects broad free-text search or unbounded historical scans.

#### Scenario: Valid bounded plate-history request

- GIVEN an administrator requests history for a valid plate with accepted bounds
- WHEN the reporting API handles the request
- THEN the response MUST be scoped to the normalized plate and requested bounds
- AND it MUST NOT require Desktop or Mobile recomputation.

#### Scenario: Broad or unbounded request

- GIVEN a plate-history request is invalid, broad, or unbounded
- WHEN validation is applied
- THEN the API MUST reject the request before historical table scans occur.

### Requirement: Source-backed historical summaries

The reporting API MUST expose plate anomaly and statistics summaries only when they are derived from existing source data, with source labels and explicit completeness markers.

#### Scenario: Summary is supported by existing sources

- GIVEN bounded existing data supports a summary
- WHEN the API returns anomaly or statistics data
- THEN the response MUST identify the supporting sources
- AND it MUST NOT imply unsupported event-sourcing or anomaly persistence.

#### Scenario: Summary source is unavailable

- GIVEN a required historical source is unavailable or partial
- WHEN summaries are returned
- THEN completeness MUST be `partial` or `unavailable`
- AND unavailable source coverage MUST be visible.

## MODIFIED Requirements

### Requirement: Historical completeness

Historical report data MUST include completeness as `complete`, `partial`, or `unavailable`; the API MUST NOT present incomplete historical data as complete. Plate history, anomaly summaries, and statistics MUST carry source coverage markers when historical inputs are partial or unavailable.
(Previously: Completeness states were required for historical reports, without explicitly covering plate history and derived anomaly/statistics summaries.)

#### Scenario: Partial history is explicit

- GIVEN requested history has known data gaps
- WHEN the API returns the report
- THEN completeness MUST be `partial`
- AND missing ranges or unavailable inputs MUST be identified

#### Scenario: Plate-derived summaries expose incomplete support

- GIVEN bounded plate history uses sources with partial or unavailable evidence
- WHEN the API returns anomaly or statistics summaries
- THEN `historical_completeness` MUST reflect the weakest required source state
- AND affected sources MUST be identified.
