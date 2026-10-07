```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:a6ce57162a68d6893637232724f2e6589c4df3dde68aedbe32523628811ec659
verdict: pass
blockers: 0
critical_findings: 0
requirements: 8/8
scenarios: 16/16
test_command: python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports tests.test_reporting_exports tests.test_accounting_report_contracts
test_exit_code: 0
test_output_hash: sha256:2e71bc2d00be382281b4bb5c0c4e85df50e37324b157b1a539d6f74395129dbd
build_command: python -m unittest discover tests
build_exit_code: 0
build_output_hash: sha256:ee67854c638d1680ceb8f1b59ade56518d24c89bd05915140ccf6889b0b5c082
```

## Verification Report

**Change**: reporting-financial-operational-api
**Version**: N/A
**Mode**: Standard

### Completeness
| Metric | Value |
|--------|-------|
| Tasks total | 13 |
| Tasks complete | 13 |
| Tasks incomplete | 0 |
| Requirements complete | 8/8 |
| Scenarios compliant | 16/16 |

### Build & Tests Execution
**Build**: ➖ Not configured; full repository regression used as build-equivalent verification.
```text
python -m unittest discover tests
Exit code: 0
Ran 511 tests in 0.592s
OK
Output hash: sha256:ee67854c638d1680ceb8f1b59ade56518d24c89bd05915140ccf6889b0b5c082
```

**Tests**: ✅ Passed
```text
python -m unittest tests.test_reporting_read_models tests.test_reporting_endpoints tests.test_reporting_closed_reports tests.test_reporting_exports tests.test_accounting_report_contracts
Exit code: 0
Ran 57 tests in 0.024s
OK
Output hash: sha256:2e71bc2d00be382281b4bb5c0c4e85df50e37324b157b1a539d6f74395129dbd
```

**Coverage**: ➖ Not available / threshold: 0

### Spec Compliance Matrix
| Requirement | Scenario | Test | Result |
|-------------|----------|------|--------|
| Safe reporting input failures | Bad period or closure identifier | tests.test_reporting_endpoints, tests.test_reporting_closed_reports | ✅ COMPLIANT |
| Safe reporting input failures | Unsupported filter | tests.test_reporting_endpoints | ✅ COMPLIANT |
| API-only reporting contract | Clients consume canonical totals | tests.test_reporting_read_models, tests.test_reporting_closed_reports | ✅ COMPLIANT |
| API-only reporting contract | Legacy aliases remain compatible | tests.test_reporting_read_models | ✅ COMPLIANT |
| Operational net definition | Net includes collected mensualidades and expenses | tests.test_reporting_closed_reports, tests.test_accounting_report_contracts | ✅ COMPLIANT |
| Operational net definition | Charged and active washes are classified | tests.test_reporting_closed_reports, tests.test_accounting_report_contracts | ✅ COMPLIANT |
| Capacity semantics | Capacity source unresolved | tests.test_reporting_read_models | ✅ COMPLIANT |
| Capacity semantics | Historical capacity is limited | tests.test_reporting_read_models, tests.test_reporting_closed_reports | ✅ COMPLIANT |
| Existing-source anomaly and statistics coverage | Coverage is available for existing sources | tests.test_reporting_read_models, tests.test_reporting_closed_reports | ✅ COMPLIANT |
| Existing-source anomaly and statistics coverage | Coverage source is unavailable | tests.test_reporting_read_models, tests.test_reporting_closed_reports | ✅ COMPLIANT |
| Existing-source anomaly and statistics coverage | Metadata is deterministic | tests.test_reporting_read_models | ✅ COMPLIANT |
| Excluded audit behaviors remain out of scope | Consumer expects persisted anomaly evidence | tests.test_reporting_read_models | ✅ COMPLIANT |
| Closed-report export formats | Export closed report | tests.test_reporting_exports, tests.test_reporting_endpoints | ✅ COMPLIANT |
| Closed-report export formats | PDF or XLSX is not ready | tests.test_reporting_exports | ✅ COMPLIANT |
| CSV compatibility decision gate | CSV retained as legacy | tests.test_reporting_exports | ✅ COMPLIANT |
| CSV compatibility decision gate | CSV omitted from canonical delivery | tests.test_reporting_exports | ✅ COMPLIANT |

**Compliance summary**: 16/16 scenarios compliant

### Correctness (Static Evidence)
| Requirement | Status | Notes |
|------------|--------|-------|
| Canonical metrics and aliases | ✅ Implemented | Canonical constants, catalog aliases, response aliasing, and repository totals are present. |
| Capacity default and metadata | ✅ Implemented | Default 50, configured total helper, unresolved source state, and historical-capacity-limited metadata are present. |
| Safe endpoint validation | ✅ Implemented | Unsupported dashboard filters and malformed audit period IDs fail before repository calls; missing closures return 404. |
| Closure/mensualidad/solo-lavado totals | ✅ Implemented | SQL and accounting contract preserve collected sources, id_cierre monthly timing, charged solo lavado inclusion, and active wash exclusion. |
| Audit/export metadata | ✅ Implemented | Audit source coverage is sorted/deterministic; exports carry identity, period, totals, completeness, compatibility, and non-blocking flags. |
| printer_agent/run_agent_task.cmd | ⚠️ Preexisting local modification | File is modified in the working tree, but the diff is the known local path override from memory; verification made no edits. |

### Coherence (Design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| Centralize metric mapping in read models | ✅ Yes | reporting_read_models.py owns constants, aliases, catalog, capacity, audit, and export metadata. |
| Preserve accounting SQL/source rules | ✅ Yes | reporting_repo.py and accounting_contracts.py preserve closure-linked mensualidades and charged solo lavado rules. |
| Reject invalid identifiers/filters safely | ✅ Yes | Endpoint tests prove invalid inputs avoid repository calculation. |
| Avoid new storage/migrations/ledger/event sourcing | ✅ Yes | No storage or migration behavior added for this derivative. |
| Keep PDF/XLSX non-blocking and CSV legacy-only | ✅ Yes | Export metadata marks delivery_blocking false and csv legacy-only. |

### Issues Found
**CRITICAL**: None.
**WARNING**: printer_agent/run_agent_task.cmd is dirty in the working tree, although evidence and prior project memory identify it as an unrelated local path override that this verification did not edit.
**SUGGESTION**: Consider normalizing noisy unittest warnings separately; they did not fail verification.

### Verdict
PASS
All tasks are complete, all 8 requirements and 16 scenarios have passing runtime coverage, and the required focused and full unittest commands passed.
