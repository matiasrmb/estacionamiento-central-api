# Delta for Reproducible Reporting Exports

## MODIFIED Requirements

### Requirement: Closed-report export formats

PDF and XLSX exports for closed reports SHOULD remain roadmap-compatible and non-blocking for this derivative. When retained or implemented, they MUST use the same canonical report identity, period, totals, and completeness metadata as the API report.
(Previously: The API was required to support roadmap-required PDF and XLSX exports for closed reports.)

#### Scenario: Export closed report

- GIVEN a closed reporting period exists and PDF or XLSX export support is available
- WHEN an export is requested
- THEN the export MUST be tied to the same canonical report identity and period
- AND metadata MUST include format, generation timestamp, report period, totals, and completeness

#### Scenario: PDF or XLSX is not ready

- GIVEN canonical API reporting is ready but PDF or XLSX export work is not
- WHEN this derivative is delivered
- THEN canonical reporting MUST NOT be blocked by missing PDF or XLSX work

### Requirement: CSV compatibility decision gate

CSV exports MAY be retained only as legacy compatibility output and MUST NOT be treated as the canonical reporting contract. Canonical consumers MUST use API report fields instead of CSV-only names or formatting.
(Previously: CSV behavior was a pending implementation decision that blocked apply until accepted, rejected, or scoped.)

#### Scenario: CSV retained as legacy

- GIVEN CSV export behavior is retained for compatibility
- WHEN a client consumes reporting data
- THEN CSV MUST be identified as legacy-only or non-canonical
- AND canonical API fields MUST remain the source of truth

#### Scenario: CSV omitted from canonical delivery

- GIVEN implementation excludes CSV changes from this derivative
- WHEN canonical API reporting is delivered
- THEN delivery MUST remain valid without CSV becoming a required canonical format
