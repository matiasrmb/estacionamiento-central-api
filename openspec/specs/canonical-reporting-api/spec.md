# Canonical Reporting API Specification

## Purpose

Define API-only canonical reporting semantics for reusable operational, financial, and audit read models. This spec MUST NOT require Desktop, Mobile, or Installer implementation.

## Requirements

### Requirement: API-only reporting contract

The API MUST expose canonical reporting read models without requiring client-side recomputation. Canonical fields MUST include `collected_sources_total`, `operational_expense_total`, `net_revenue_total`, `monthly_payments_collected_total`, and `vehicle_movement_count`. Legacy names `operational_income_total`, `operational_net_total`, and `mensualidad_sales_total` SHOULD remain temporary aliases where feasible, but new clients MUST use canonical names.
(Previously: The contract required API-owned totals, capacity, periods, and completeness without naming canonical metric fields or alias behavior.)

#### Scenario: Clients consume canonical totals

- GIVEN a reporting client requests a closed report
- WHEN the API returns reporting data
- THEN canonical totals, capacity, periods, and completeness MUST be present in API-owned fields
- AND clients MUST NOT need Desktop or Mobile-specific calculations

#### Scenario: Legacy aliases remain compatible

- GIVEN a current client reads an old metric name that has a feasible alias
- WHEN canonical report data is returned
- THEN the alias SHOULD match the canonical field value
- AND the canonical name MUST remain the preferred contract

### Requirement: Closure-to-closure operational day

The API MUST use closure-to-closure as the primary business-day boundary for operational, financial, and audit reporting.

#### Scenario: After-midnight operation belongs to previous journey

- GIVEN an operational journey started on the previous calendar day and is not closed
- WHEN an operation occurs after midnight before closure
- THEN the operation MUST belong to that open journey

#### Scenario: Closed period boundary

- GIVEN two consecutive closures exist
- WHEN a report is requested for the later closed period
- THEN the period MUST include operations after the previous closure through the selected closure

### Requirement: Operational net definition

`net_revenue_total` MUST equal collected sources plus mensualidades collected in the selected closure journey minus `operational_expense_total`. Collected sources MUST include charged solo lavado revenue and MUST exclude uncharged active washes.
(Previously: Operational net equaled transient cash plus journey-collected mensualidades minus expenses, without canonical names or explicit solo lavado exclusion rules.)

#### Scenario: Net includes collected mensualidades and expenses

- GIVEN a closed journey has collected sources, mensualidades linked as collected in that journey, and expenses
- WHEN net revenue is computed
- THEN the API MUST return collected sources plus those mensualidades minus expenses

#### Scenario: Charged and active washes are classified

- GIVEN charged solo lavado and active uncharged wash records exist
- WHEN collected sources are calculated
- THEN charged solo lavado revenue MUST be included
- AND active uncharged washes MUST be excluded

### Requirement: Capacity semantics

The API MUST expose configured total spaces with default `50` and effective transient capacity as `configured_total - active_monthly_customers` when source data is available. Historical responses without authoritative capacity evidence MUST be labeled `historical-capacity-limited`.
(Previously: Total spaces were fixed at 50 and effective capacity depended on resolving the active monthly source, without configurable capacity or historical limitation labels.)

#### Scenario: Capacity source unresolved

- GIVEN the authoritative active monthly source is unresolved
- WHEN capacity is requested
- THEN the API MUST expose configured total spaces defaulting to 50
- AND effective transient capacity MUST be marked unavailable or blocked by dependency

#### Scenario: Historical capacity is limited

- GIVEN historical active-monthly capacity evidence is unavailable
- WHEN historical reporting capacity is returned
- THEN the response MUST include `historical-capacity-limited`
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
### Requirement: Safe reporting input failures

The API MUST reject invalid reporting identifiers and unsupported financial/operational filters without fabricating reports.

#### Scenario: Bad period or closure identifier

- GIVEN a client sends an unknown closure ID or malformed period ID
- WHEN the reporting API validates the request
- THEN it MUST fail safely with an error response
- AND it MUST NOT return default or fabricated report data

#### Scenario: Unsupported filter

- GIVEN a client sends a filter outside the supported reporting contract
- WHEN validation is applied
- THEN the API MUST reject the request before report calculation

