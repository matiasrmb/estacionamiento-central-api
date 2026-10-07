# Delta for Canonical Reporting API

## ADDED Requirements

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

## MODIFIED Requirements

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
