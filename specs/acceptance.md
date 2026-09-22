# G2 acceptance baseline — proposed

Status: `PROPOSED_NOT_APPROVED`; all scenarios below are acceptance expectations, not executed product tests. The G2 decision must be bound later by the Owner to the accurate records page. No Issue number, URL, decision commit, or Human decision is created in this draft.

The oracle is independent of a future implementation. It compares canonical input, exact Decimal/fixed-point results, one machine-readable rejection code where rejection is expected, and the before/after persistence state. A valid response is not enough if an invalid batch leaves partial state.

The complete error mapping and multi-error priority are in `specs/error-catalog.json`; the role matrix and no-login limitation are in `specs/permissions.json`.

The reusable read-only checker `checks/g2_spec_oracle_check.py` validates these links and invariants without implementing the product. Its current deterministic result is saved at `checks/G2-spec-oracle-result.json` with `status=PASS`; this is material consistency evidence, not product execution.

## Scenarios

| ID | Input / actor | Expected result | Required state effect |
|---|---|---|---|
| G2-AC-01 | `fixtures/G2-valid.csv`, dataset `g2-sample-2026-01-02` | Accept; totals `300.000` and `370.000`; only `2026-02/A` anomalous | Commit complete dataset and derived result as one unit |
| G2-AC-02 | Invalid month fixture | Reject `INVALID_MONTH` | No state mutation |
| G2-AC-03 | `fixtures/G2-negative.csv` | Reject `NEGATIVE_KWH` | Valid rows in the batch do not persist |
| G2-AC-04 | `fixtures/G2-duplicate.csv` | Reject `DUPLICATE_MONTH_BUILDING` | No partial row or derived result persists |
| G2-AC-05 | Exact replay variant only: `fixtures/G2-replay.json#exact_replay` | Reject exactly `DUPLICATE_DATASET_REPLAY` | Original dataset/history unchanged |
| G2-AC-06 | Changed replay variant only: `fixtures/G2-replay.json#changed_replay` | Reject exactly `DATASET_ID_REUSE_CONFLICT` | Original dataset/history unchanged |
| G2-AC-07 | Dataset with no immediately preceding month | Accept `NO_PRIOR_MONTH`, null percentage, no anomaly | Store explicit comparison state; do not impute 0% |
| G2-AC-08 | Dataset with a zero preceding kWh | Accept `ZERO_BASELINE`, null percentage, no anomaly | Store explicit comparison state; never divide by zero |
| G2-AC-09 | Exact Decimal rows `0.1` and `0.2` | Totals include exact `0.300`; no binary-float artifact | Commit exact fixed-point result |
| G2-AC-10 | Exact 30.000% increase | Accept; `anomaly=false` | Compare the quantized value with strict `>` |
| G2-AC-11 | 30.001% increase | Accept; `anomaly=true` for that building/month | Do not flag unrelated rows |
| G2-AC-13 | Valid row followed by negative row | Reject `NEGATIVE_KWH` | No valid prefix/suffix persists |
| G2-AC-14 | Reordered replay variant only: `fixtures/G2-replay.json#reordered_replay` | Reject exactly `DUPLICATE_DATASET_REPLAY` | Row order cannot create a new dataset |
| G2-AC-16 | `ANALYST` action matrix | New import/read allowed; replay attempt rejected; direct mutation denied; identity isolation `NOT_PROVEN` | No denied-action mutation |
| G2-AC-17 | `REVIEWER` action matrix | Read results/history allowed; import/replay denied; mutation denied; identity isolation `NOT_PROVEN` | No denied-action mutation |
| G2-AC-18 | `fixtures/G2-near-threshold.json` (`333.333 → 433.333`) | Exact fraction `10000000/333333` quantizes to display `30.000`; `anomaly=false` | Quantize with `ROUND_HALF_EVEN`, then compare the quantized value |
| G2-AC-19 | `fixtures/G2-quoted-fields.json` | Ordinary quoted fields are accepted; same result as AC-01 | Commit the same canonical result |

### Split invalid-input scenarios formerly covered by AC-12

Each row below is one input variant and has exactly one expected error. No row aggregates multiple invalid forms.

| ID | Fixture fragment | Expected error |
|---|---|---|
| G2-AC-12A | `G2-invalid-input-cases.json#G2-AC-12A` exponent kWh | `INVALID_KWH_FORMAT` |
| G2-AC-12B | `G2-invalid-input-cases.json#G2-AC-12B` plus-signed kWh | `INVALID_KWH_FORMAT` |
| G2-AC-12C | `G2-invalid-input-cases.json#G2-AC-12C` scale over three decimals | `KWH_SCALE_EXCEEDED` |
| G2-AC-12D | `G2-invalid-input-cases.json#G2-AC-12D` extra field | `INVALID_ROW_SHAPE` |
| G2-AC-12E | `G2-invalid-input-cases.json#G2-AC-12E` empty kWh | `INVALID_KWH_FORMAT` |
| G2-AC-12F | `G2-invalid-input-cases.json#G2-AC-12F` whitespace-padded kWh | `INVALID_KWH_FORMAT` |
| G2-AC-12G | `G2-invalid-input-cases.json#G2-AC-12G` disallowed building character | `INVALID_BUILDING` |
| G2-AC-12H | `G2-invalid-input-cases.json#G2-AC-12H` building over 64 characters | `INVALID_BUILDING` |
| G2-AC-12I | `G2-invalid-input-cases.json#G2-AC-12I` building control character | `INVALID_BUILDING` |
| G2-AC-12J | `G2-invalid-input-cases.json#G2-AC-12J` invalid UTF-8 bytes | `INVALID_UTF8` |
| G2-AC-12K | `G2-invalid-input-cases.json#G2-AC-12K` mixed LF/CRLF | `INVALID_CSV_LINE_ENDING` |
| G2-AC-12L | `G2-invalid-input-cases.json#G2-AC-12L` malformed quote | `INVALID_ROW_SHAPE` |
| G2-AC-12M | `G2-invalid-input-cases.json#G2-AC-12M` blank record | `INVALID_ROW_SHAPE` |
| G2-AC-12N | `G2-invalid-input-cases.json#G2-AC-12N` wrong header | `INVALID_HEADER` |
| G2-AC-12O | `G2-invalid-input-cases.json#G2-AC-12O` header-only input | `EMPTY_DATASET` |
| G2-AC-12P | `G2-invalid-input-cases.json#G2-AC-12P` BOM in the payload | `INVALID_CSV_BOM` |
| G2-AC-12Q | `G2-invalid-input-cases.json#G2-AC-12Q` quoted embedded newline | `INVALID_ROW_SHAPE` |
| G2-AC-12R | `G2-invalid-input-cases.json#G2-AC-12R` invalid dataset ID | `INVALID_DATASET_ID` |

All rejection scenarios, including invalid rows mixed with valid rows, are atomic and leave the pre-import state unchanged.

## Canonical result for the primary sample

The independent oracle in `fixtures/G2-expected-results.json` is authoritative for AC-01:

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

Displayed percentages use a 50-significant-digit Decimal context and `ROUND_HALF_EVEN` at `0.001`. Threshold comparison uses the quantized value, so AC-18 is deliberately not anomalous even though its unquantized ratio is slightly above 30%.

## Future 30→70 gate

`G2-AC-15` is deliberately outside the current acceptance decision. It is the separate future gate in `tasks/G2-THRESHOLD-CHANGE-70.json`: with the same accepted input, evaluate a new `G2-70PCT-R1` criterion and expect no anomaly in the primary sample. This future case has `human_decision_required=true`, `decision=null`, `issue_id=null`, and `status=NOT_CURRENT_APPROVAL`. It must not be represented as a current G2 PASS or approval.

## Evidence boundary

A later implementation review must distinguish product acceptance from technical execution, Human decision, Control records, identity enforcement, and deployment. The fixture files are synthetic public inputs and expected values only. They are not proof that a prototype ran, that a service was deployed, or that the G2 gate was approved.
