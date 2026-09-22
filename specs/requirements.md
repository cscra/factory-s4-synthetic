# G2 product requirements — proposed

Status: `PROPOSED_NOT_APPROVED`. This document prepares the G2 Human decision after the recorded G1 approval. It is a synthetic product contract; it does not authorize a prototype, implementation, deployment, production use, or Control adoption.

Project: `S4-P-001`
Submission draft: `SUB-S4-G2-001`
Current task: `G2-PRODUCT` revision `R1`

Prior-gate provenance is recorded only as context: Human published `批准 SUB-S4-G1-001 @d22e8c591309b5a555d04474e5e172159b008afc`. That G1 result permits preparation of G2 material. It does not approve any G2 field, calculation, threshold, implementation, or future threshold change.

## 1. Product boundary

The product is a synthetic monthly building-energy analysis demonstration for a facilities analyst and an independent reviewer. The input is a bounded dataset supplied as a CSV import. The demonstration has no meter, sensor, customer, account, credential, billing, control, or production connection. G2 fixes the data and calculation semantics so a later prototype can be judged against one deterministic contract.

The current material contains requirements, fixtures, and acceptance oracles only. It contains no application code and no prototype decision.

## 1.1 Roles and access boundary

G2 fixes an action boundary for the later synthetic workflow. It does not add authentication. The current material has `identity_model=NO_LOGIN_IN_G2` and `identity_enforcement=NOT_PROVEN`; a role selector, hidden button, or same-process caller is not user isolation. A later prototype must report this limitation instead of claiming analyst/reviewer security. The machine-readable matrix is `specs/permissions.json`.

| Actor | Import | View results | View history | Replay | Modify accepted data/results/criterion |
|---|---|---|---|---|---|
| `ANALYST` | May import a new `dataset_id` after full validation | May read synthetic results | May read synthetic history | May attempt a replay; dataset identity must reject it | Denied direct edit, delete, overwrite, or recompute |
| `REVIEWER` | Denied with `ROLE_NOT_PERMITTED` | May read synthetic results | May read synthetic history | Denied with `ROLE_NOT_PERMITTED` | Denied with `MUTATION_NOT_PERMITTED` / `IMMUTABLE_HISTORY` |

Neither role may change the 30% criterion. A 30→70 criterion change is a separate Human gate. Both roles receive fail-closed action errors and no state mutation on a denied action.

## 2. Import contract

One import is one immutable dataset envelope with a caller-supplied `dataset_id` and an ordered CSV payload. The CSV header must be exactly:

```text
month,building,kwh
```

Each data row must contain exactly those three fields. Extra columns, missing columns, blank records, or malformed records reject the entire import.

### 2.1 Strict month

`month` is a calendar month in the exact lexical form `YYYY-MM`: four decimal year digits, a hyphen, and two decimal month digits. The month must be in `01` through `12`; timestamps, day values, `2026-1`, `2026/01`, whitespace-padded values, and other spellings are invalid. The value is interpreted as a calendar month, not as a timestamp or locale string.

### 2.2 Building

`building` is a non-empty exact ASCII identifier matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` (1–64 characters). Unicode letters, spaces, slashes, quotes, whitespace padding, C0 controls, DEL, and embedded LF/CR are invalid. No trimming or case folding may silently turn two input identifiers into one. The duplicate key is `(dataset_id, month, building)`.

### 2.3 Strict kWh value

`kwh` is an ASCII decimal token matching:

```text
(0|[1-9][0-9]*)(\.[0-9]{1,3})?
```

The token represents a non-negative value in kWh with at most three fractional digits. A token with a leading minus and otherwise decimal digits is classified as `NEGATIVE_KWH`; other malformed signed tokens are invalid format. A leading plus, exponent notation, `NaN`, infinity, empty text, binary JSON numbers, and whitespace-padded values are rejected. JSON fixtures therefore carry kWh as strings; CSV tokens are parsed as text.

All arithmetic uses exact `Decimal` or an equivalent fixed-point integer scale of 1,000. No binary floating-point parse, sum, comparison, or serialization is permitted. Values are canonicalized to three fractional digits for expected output (for example, `100` becomes `100.000`). More than three fractional digits is a validation error; no rounding is implicit.

Percentage calculation has two explicitly separate representations:

- The unquantized ratio is computed with a Decimal context of 50 significant digits. The displayed `percent_change` is then quantized to `0.001` using `ROUND_HALF_EVEN`.
- The anomaly comparison uses that three-decimal quantized value with strict `percent_change > 30.000`; the unquantized value never decides the flag. The near-threshold fixture has prior `333.333` and current `433.333`: its exact fraction is `10000000/333333`, its quantized display is `30.000`, and its unique expected anomaly result is `false`.

## 2.4 CSV wire contract

The input is strict UTF-8 bytes with no BOM. A BOM at byte offset zero or anywhere else is `INVALID_CSV_BOM`; invalid byte sequences are `INVALID_UTF8`.

Parsing follows the selected RFC 4180 subset: comma delimiter, ordinary double-quote field quoting, doubled double-quote escape, and quoted commas are accepted. Backslash is not an escape. Embedded LF/CRLF inside a quoted field is rejected as `INVALID_ROW_SHAPE`; it is never silently normalized.

LF and CRLF record endings are both accepted. Mixed LF/CRLF and bare CR are `INVALID_CSV_LINE_ENDING`. One terminal record separator is allowed. A blank record anywhere is `INVALID_ROW_SHAPE`; a header with no data records is `EMPTY_DATASET`. The exact error code mapping, priority, and no-mutation rule are in `specs/error-catalog.json`.

## 3. Identity, duplicates, replay, and atomicity

`dataset_id` is required, immutable, and unique. It must be a non-empty lower-case identifier matching `[a-z0-9][a-z0-9._-]{0,63}`. The same dataset ID may never be silently overwritten.

The import rejects all of the following:

- two rows in one batch with the same `(month, building)`, whether their kWh values are equal or different;
- a second import with the same dataset ID and the same canonical rows (`DUPLICATE_DATASET_REPLAY`);
- a second import with the same dataset ID and different canonical rows (`DATASET_ID_REUSE_CONFLICT`).

A different dataset ID is a different dataset and does not overwrite an earlier dataset. The canonical replay identity is the dataset ID plus the canonical rows sorted by `(month, building)` and carrying canonical kWh text; input row order does not create a new dataset. The original row order may be preserved for audit, but it is not a replay identity. The identity is not inferred from a mutable display label.

Validation, duplicate detection, replay detection, totals, comparisons, and anomaly derivation happen before persistence. If any row or identity check fails, the whole batch is rejected and none of these are persisted: raw rows, dataset ID, monthly totals, comparison results, anomaly flags, criterion version, or history entry. A rejection must leave the pre-import state byte-for-byte equivalent for the purposes of this contract.

## 4. Derived results

### 4.1 Monthly totals

For each month represented in the accepted batch, `monthly_total_kwh` is the exact Decimal sum of all accepted building rows for that month. The result is keyed by the strict `YYYY-MM` value and serialized with three fractional digits.

### 4.2 Per-building month-over-month comparison

For each accepted `(month, building)` row, compare with the same building in the immediately preceding calendar month (`month - 1`), not merely the previous observed row.

- If no row exists for that building in the immediately preceding month, return `comparison_status=NO_PRIOR_MONTH`, `percent_change=null`, and `anomaly=false`.
- If the prior kWh is exactly zero, return `comparison_status=ZERO_BASELINE`, `percent_change=null`, and `anomaly=false`, regardless of the current positive value. It is never reported as `0%` and never divides by zero.
- If the prior kWh is positive, calculate `percent_change = ((current - prior) / prior) * 100` using the 50-significant-digit Decimal context, quantize it to three fractional digits with `ROUND_HALF_EVEN`, and compare the quantized value to 30.000. The exact unquantized ratio may be retained for audit but cannot change the flag.

A missing month and a zero baseline are explicit states in the result. They are not imputed as zero growth and do not create an anomaly.

### 4.3 Current anomaly criterion

The current G2 criterion version is `G2-30PCT-R1`. A compared row is anomalous exactly when the quantized `percent_change > 30.000`. An increase quantized to exactly 30.000% is not anomalous, even when its unquantized ratio is slightly above 30%. Decreases and increases up to the threshold are not anomalous.

The canonical sample in `fixtures/G2-valid.csv` must produce:

- `2026-01` total `300.000` kWh and `2026-02` total `370.000` kWh;
- `2026-01/A` and `2026-01/B` with `NO_PRIOR_MONTH`;
- `2026-02/A` at `60.000%`, anomalous;
- `2026-02/B` at `5.000%`, not anomalous;
- exactly one anomaly: `2026-02/A`.

## 5. Later persistence expectation

A later G5 implementation, if separately authorized, must preserve `dataset_id`, the original rows, the canonical input identity, the computed totals and comparisons, the anomaly list, and `criterion_version` across process exit and restart. G2 acceptance of these requirements does not authorize that implementation or claim that persistence has been tested.

## 6. Current gate and independent future gate

The current G2 decision covers only the contract in this document and the current 30% criterion. The planned threshold revision from 30% to 70% is a separate future G2 change gate in `tasks/G2-THRESHOLD-CHANGE-70.json`. It is explicitly excluded from the current G2 approval request, has no decision, and has no Issue binding. If that future gate is approved, the anomaly result must be re-evaluated under a new criterion version; the current 30% result does not silently become a 70% result, and a re-approval does not erase the old result.

## 7. Source basis

This draft carries forward the exact synthetic sample and boundary from:

- S4 `S4-Implementation-and-Acceptance-Plan-v0.1.md`, §5 S4-5, §10, and the G2 rows at the plan's product gate table (source SHA-256 `0920f0492b5b3cbf4d4cae706c1aa2e0b67a19e5767e52bb43f6cfad2ac8b089`);
- v0.7 `Factory-vNext-Integrated-Operating-Design-v0.7.md`, §10.1 (source SHA-256 `b6545ed62f45c2cfeb260827fae2abe20405f2bf41f9b67a24093db659b5bc26`);
- the synthetic source fixture `energy-demo.csv` (source SHA-256 `6605d0214b3d656f0e16a1352ceec1d9498052f64c3df8f158b483dd5690791a`) and its proposed result oracle (source SHA-256 `eea7a38b4be3511db8248bddb56d3604f28dc8ddc751e12aa310a1614630f541`);
- the supplied D3/D4 semantic originals, which require accurate object identity, preserved history, explicit verification, and no self-created Human decision. The source package is retained outside this public material repository.

The source documents define preparation and evidence boundaries; they do not make this product proposal approved.
