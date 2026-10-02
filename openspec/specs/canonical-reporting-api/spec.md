# Canonical Reporting API Specification

## Purpose

Define API-only canonical reporting semantics for reusable operational, financial, and audit read models. This spec MUST NOT require Desktop, Mobile, or Installer implementation.

## Requirements

### Requirement: API-only reporting contract

The API MUST expose canonical reporting read models without requiring client-side recomputation of business semantics.

#### Scenario: Clients consume canonical totals

- GIVEN a reporting client requests a closed report
- WHEN the API returns reporting data
- THEN operational totals, capacity, periods, and completeness MUST be present in API-owned fields
- AND clients MUST NOT need Desktop or Mobile-specific calculations

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

Operational net MUST equal cash collected in the operational journey, including journey-collected mensualidades, minus operational expenses.

#### Scenario: Net includes mensualidades and expenses

- GIVEN a closed journey has transient cash, collected mensualidades, and expenses
- WHEN operational net is computed
- THEN the API MUST return transient cash plus mensualidades minus expenses

### Requirement: Capacity semantics

The API MUST expose total spaces as 50 and effective transient capacity as `50 - active_monthly_customers` once the authoritative active monthly source is resolved.

#### Scenario: Capacity source unresolved

- GIVEN the authoritative active monthly source is unresolved
- WHEN capacity is requested
- THEN the API MUST expose total spaces as 50
- AND effective transient capacity MUST be marked unavailable or blocked by dependency

### Requirement: Historical completeness

Historical report data MUST include completeness as `complete`, `partial`, or `unavailable`; the API MUST NOT present incomplete historical data as complete.

#### Scenario: Partial history is explicit

- GIVEN requested history has known data gaps
- WHEN the API returns the report
- THEN completeness MUST be `partial`
- AND missing ranges or unavailable inputs MUST be identified
