# Archive Report: reporting-financial-operational-api

## Status

Archived successfully on 2026-10-06.

## Final State

- Tasks complete: 13/13.
- Verification verdict: PASS.
- Requirements complete: 8/8.
- Scenarios compliant: 16/16.
- Scope preserved: API-only reporting behavior; no Desktop, Mobile, Installer, production, database migration, ledger, event-sourcing, or remote work was introduced.
- Known unrelated local path override: `printer_agent/run_agent_task.cmd` remained out of scope and was not touched by this archive.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| `canonical-reporting-api` | Updated | Applied ADDED safe input failures and MODIFIED canonical contract, operational net, and capacity semantics. |
| `reporting-audit-inventory` | Updated | Applied MODIFIED existing-source audit coverage and explicit excluded audit behaviors. |
| `reproducible-reporting-exports` | Updated | Applied MODIFIED non-blocking PDF/XLSX export behavior and CSV legacy compatibility gate. |

## Source of Truth Updated

- `openspec/specs/canonical-reporting-api/spec.md`
- `openspec/specs/reporting-audit-inventory/spec.md`
- `openspec/specs/reproducible-reporting-exports/spec.md`

## Archive Location

- `openspec/changes/archive/2026-10-06-reporting-financial-operational-api/`

## Archive Contents

- `proposal.md`
- `design.md`
- `tasks.md`
- `verify-report.md`
- `exploration.md`
- `specs/canonical-reporting-api/spec.md`
- `specs/reporting-audit-inventory/spec.md`
- `specs/reproducible-reporting-exports/spec.md`

## Evidence Referenced

- Focused verification: `python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports tests.test_reporting_exports tests.test_accounting_report_contracts` passed with 57 tests.
- Full verification: `python -m unittest discover tests` passed with 511 tests.
- Parent spot-check after verify: focused command passed again with 57 tests.
- Verify report: `openspec/changes/archive/2026-10-06-reporting-financial-operational-api/verify-report.md`.

## Archive Commands

```text
gentle-ai sdd-archive-compose --canonical "openspec/specs/canonical-reporting-api/spec.md" --delta "openspec/changes/reporting-financial-operational-api/specs/canonical-reporting-api/spec.md" --output "openspec/specs/canonical-reporting-api/spec.md.compose-tmp"
gentle-ai sdd-archive-compose --canonical "openspec/specs/reporting-audit-inventory/spec.md" --delta "openspec/changes/reporting-financial-operational-api/specs/reporting-audit-inventory/spec.md" --output "openspec/specs/reporting-audit-inventory/spec.md.compose-tmp"
gentle-ai sdd-archive-compose --canonical "openspec/specs/reproducible-reporting-exports/spec.md" --delta "openspec/changes/reporting-financial-operational-api/specs/reproducible-reporting-exports/spec.md" --output "openspec/specs/reproducible-reporting-exports/spec.md.compose-tmp"
git mv "openspec/changes/reporting-financial-operational-api" "openspec/changes/archive/2026-10-06-reporting-financial-operational-api" || verified fallback mv
diff -r <pre-move snapshot> "openspec/changes/archive/2026-10-06-reporting-financial-operational-api"
```

## Mechanical Readback

The archive move used a recursive pre-move snapshot and `diff -r` readback. The source directory was absent after the move.

Verbatim `diff -r` output:

```text
```

The empty output above is the passing byte-identity evidence for the moved archive tree. The `archive-report.md` file was added after the move as the terminal archive record and is not part of the source/destination identity comparison.

## Engram Traceability

- Artifact locators in native status resolved to filesystem paths for this hybrid run.
- Engram artifact observation IDs read directly during archive: none.
- Archive report persisted to Engram topic key: `sdd/reporting-financial-operational-api/archive-report`.

## Risks

- None for archive closure.
- Existing unittest warning/log noise remains unrelated and non-failing.
- `printer_agent/run_agent_task.cmd` remains a known unrelated local path override outside this change.
