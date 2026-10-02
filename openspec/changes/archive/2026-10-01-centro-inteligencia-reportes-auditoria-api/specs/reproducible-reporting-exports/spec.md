# Reproducible Reporting Exports Specification

## Purpose

Define API-only export behavior for reproducible closed reports. This spec MUST NOT require Desktop, Mobile, or Installer implementation.

## Requirements

### Requirement: Closed-report export formats

The API MUST support roadmap-required PDF and XLSX exports for closed reports, with stable report identity and metadata sufficient for later reproduction.

#### Scenario: Export closed report

- GIVEN a closed reporting period exists
- WHEN a PDF or XLSX export is requested
- THEN the API MUST return an export tied to the same canonical report identity and period
- AND metadata MUST include format, generation timestamp, report period, and completeness

### Requirement: Reproducible metadata

Exports MUST include enough metadata to compare two exports of the same closed report without relying on client UI state.

#### Scenario: Repeat export of same closure

- GIVEN canonical source data for a closed report has not changed
- WHEN the same PDF or XLSX export is generated again
- THEN report identity, closure period, totals, and completeness metadata MUST match

### Requirement: Completeness visibility in exports

Exports MUST carry `complete`, `partial`, or `unavailable` historical completeness and MUST NOT imply partial data is complete.

#### Scenario: Partial report export

- GIVEN a report has partial historical completeness
- WHEN an export is generated
- THEN the export metadata MUST state `partial`
- AND unavailable inputs MUST remain visible to consumers

### Requirement: CSV compatibility decision gate

CSV behavior is a pending implementation decision. The API MUST NOT guess CSV support, rejection, or compatibility semantics before apply.

#### Scenario: CSV decision unresolved before apply

- GIVEN implementation planning starts and CSV policy is unresolved
- WHEN apply readiness is evaluated
- THEN implementation MUST be blocked until CSV compatibility is explicitly accepted, rejected, or scoped as legacy-only
