# Delta for Canonical Reporting API

## ADDED Requirements

### Requirement: Closed-period operation rows

The API MUST expose operation drill-down rows scoped by closed reporting period through `/api/v1/reporting/reports/operations?period_id=closure:{id}`. Rows MUST represent only operations inside the selected closed period and MUST preserve the canonical reporting contract as API-only behavior.

#### Scenario: Operations are scoped to a closed period

- GIVEN a closed period identified by `closure:42`
- WHEN an admin requests `/api/v1/reporting/reports/operations?period_id=closure:42`
- THEN the response MUST contain only operation rows within that closed period
- AND it MUST NOT require Desktop, Mobile, or Installer changes

#### Scenario: Non-closure period scope is rejected

- GIVEN an unsupported period scope value
- WHEN the operations endpoint is requested
- THEN the API MUST reject the request with a validation error

### Requirement: Operation filter allow-list

The operations endpoint MUST accept only documented filters from a strict allow-list. Unsupported filter keys or invalid filter values MUST be rejected instead of ignored.

#### Scenario: Supported filter is applied

- GIVEN a request with an allowed operation filter
- WHEN the operations endpoint processes the query
- THEN every returned row MUST satisfy that filter

#### Scenario: Unsupported filter is rejected

- GIVEN a request containing an unknown query filter
- WHEN the operations endpoint validates the query
- THEN the API MUST reject the request with an explicit validation error

### Requirement: Operation sort allow-list

The operations endpoint MUST accept only documented sort fields and directions from a strict allow-list. Sorting MUST include a deterministic tie-breaker so equal primary values page consistently.

#### Scenario: Allowed sort is deterministic

- GIVEN multiple operations share the same primary sort value
- WHEN the client requests an allowed sort
- THEN rows MUST be ordered by the requested sort and a stable row identifier tie-breaker

#### Scenario: Unsupported sort is rejected

- GIVEN a request with an unsupported sort field or direction
- WHEN the operations endpoint validates sorting
- THEN the API MUST reject the request with an explicit validation error

### Requirement: Deterministic offset pagination

The operations endpoint MUST support bounded `limit` and `offset` pagination. Responses MUST include pagination metadata containing `total`, `limit`, `offset`, `has_more`, and `next_offset` or an equivalent next-page indicator.

#### Scenario: Page includes metadata

- GIVEN a closed period with more rows than the requested limit
- WHEN the first page is requested with a valid limit and offset
- THEN the response MUST include the requested rows and total row count
- AND `has_more` MUST be true with the next offset indicated

#### Scenario: Final page is explicit

- GIVEN the requested page reaches the end of the result set
- WHEN the operations endpoint returns the page
- THEN `has_more` MUST be false
- AND the next offset MUST be absent, null, or otherwise marked unavailable

### Requirement: Admin-only operation drill-down access

The operations drill-down endpoint MUST preserve existing reporting authorization semantics and remain accessible only to authenticated administrators.

#### Scenario: Non-admin access is denied

- GIVEN an authenticated non-admin or unauthenticated caller
- WHEN the caller requests operation rows
- THEN the API MUST deny access before returning reporting data
