# G2 acceptance baseline — proposed

Status: `PROPOSED_NOT_APPROVED`; all scenarios below are acceptance expectations, not executed test results. The G2 decision must be bound later by the Owner to the accurate records page. No Issue number, URL, decision commit, or Human decision is created in this draft.

The acceptance oracle is independent of any future implementation. It compares canonical input, exact Decimal outputs, rejection code, and the before/after persistence state. A valid response is not enough if an invalid batch leaves any partial state.

## Scenarios

| ID | Input | Expected result | Required state effect |
|---|---|---|---|
| G2-AC-01 | `fixtures/G2-valid.csv`, dataset `g2-sample-2026-01-02` | Accept; totals `300.000` and `370.000`; only `2026-02/A` is anomalous | Commit the complete dataset and derived result as one unit |
| G2-AC-02 | A row with `2026-1` or `2026-13` | Reject `INVALID_MONTH` | No rows, totals, comparisons, flags, criterion, or history entry are committed |
| G2-AC-03 | `fixtures/G2-negative.csv` | Reject `NEGATIVE_KWH` | The valid rows in the same batch are not committed |
| G2-AC-04 | `fixtures/G2-duplicate.csv` | Reject `DUPLICATE_MONTH_BUILDING` | No partial row or derived result is committed |
| G2-AC-05 | Re-import the exact canonical rows of AC-01, including in a different input order, with the same dataset ID | Reject `DUPLICATE_DATASET_REPLAY` | The original accepted dataset remains unchanged; no second history entry |
| G2-AC-06 | Re-import changed canonical rows with the AC-01 dataset ID | Reject `DATASET_ID_REUSE_CONFLICT` | The original accepted dataset remains unchanged; no overwrite |
| G2-AC-07 | A valid dataset with no immediately preceding month for a building | Accept with `NO_PRIOR_MONTH`, null percentage, no anomaly | Store the explicit comparison state; do not impute 0% |
| G2-AC-08 | A valid dataset whose preceding kWh is zero | Accept with `ZERO_BASELINE`, null percentage, no anomaly | Store the explicit comparison state; never divide by zero or report 0% |
| G2-AC-09 | Decimal rows such as `0.1` and `0.2` | Accept exact fixed-point totals and comparisons | `0.1 + 0.2` is exactly `0.300`; no binary float artifact |
| G2-AC-10 | A comparison exactly at 30.000% | Accept; `anomaly=false` | Use a strict `>` threshold |
| G2-AC-11 | A comparison above 30.000% | Accept; `anomaly=true` for that building/month only | Do not flag other buildings whose change is at or below threshold |
| G2-AC-12 | Non-decimal token, exponent, plus sign, extra field, blank field, or whitespace-padded value | Reject the corresponding validation error | Entire batch remains unchanged |
| G2-AC-13 | Any one invalid row mixed with otherwise valid rows | Reject the entire batch | Atomic failure: no valid prefix or suffix is persisted |
| G2-AC-14 | Re-run the accepted dataset through the same replay identity | Reject as duplicate even when the payload bytes are identical | Replay never silently overwrites or creates a second result |

## Canonical result for the primary sample

The independent oracle in `fixtures/G2-expected-results.json` is authoritative for AC-01's expected values:

```text
2026-01 total: 300.000 kWh
2026-02 total: 370.000 kWh
2026-01/A: NO_PRIOR_MONTH, percent=null, anomaly=false
2026-01/B: NO_PRIOR_MONTH, percent=null, anomaly=false
2026-02/A: COMPARED, percent=60.000, anomaly=true
2026-02/B: COMPARED, percent=5.000, anomaly=false
anomalies: ["2026-02/A"]
criterion: G2-30PCT-R1
```

## Future 30→70 gate

`G2-AC-15` is deliberately outside the current acceptance decision. It is the separate future gate in `tasks/G2-THRESHOLD-CHANGE-70.json`: with the same accepted input, evaluate a new `G2-70PCT-R1` criterion and expect no anomaly in the primary sample. This future case has `human_decision_required=true`, `decision=null`, `issue_id=null`, and `status=NOT_CURRENT_APPROVAL`. It must not be represented as a current G2 PASS or approval.

## Evidence boundary

A later implementation review must distinguish product acceptance from technical execution, Human decision, Control records, and deployment. The fixture files are synthetic public inputs and expected values only. They are not proof that a prototype ran, that a service was deployed, or that the G2 gate was approved.
