# G3 static prototype — candidate, not Gate approval

This G3 candidate is a **simulated, offline fixture walkthrough** of the exact G2 contract approved at `33f85f2656a561534f875ee5e690a4233d95aec6`. It does not grant G3 approval or authorize G4–G6, deployment, real business, or Control adoption. Historical PROPOSED/NOT_EXECUTED labels in frozen source files remain unchanged.

## Experience and sources

Open `app/static/index.html` directly in a modern browser. No installation, network, server, login, or external asset is required. With JavaScript disabled, a clear message explains that interactive scenarios are unavailable; the contract and limitations remain readable.

All controls select **fixed examples** and reveal their expected oracle. They do not parse user files, compute arbitrary inputs, import, save, or modify a dataset. Each scenario displays its exact source reference, dataset identity, input and expected result. Embedded originals retain their byte SHA-256 and are independently checked against the approved commit by `checks/g3_prototype_check.py`.

1. **有效样例**: reveal the approved four-row sample. January is 300.000 kWh; February is 370.000 kWh. A is 60.000% / anomaly; B is 5.000% / normal. Both January rows have NO_PRIOR_MONTH, null percentage, no anomaly.
2. **整批拒绝**: choose negative kWh, duplicate `(dataset_id,month,building)`, invalid month, or invalid numeric text from approved fixtures; reveal the exact error and no-mutation contract. A valid prefix does not survive. No raw row, dataset ID, total, comparison, flag, criterion, or history entry is partially committed.
3. **重放与边界**: inspect exact, changed and reordered replay; exact 30.000%, near-threshold 333.333 → 433.333, 30.001%, missing prior month, zero baseline, and exact decimal totals. Replay cases explicitly assume the canonical dataset already exists; selecting a case does not create that dataset. A rejected replay leaves that hypothetical original unchanged.

## Fixed semantics

Fields are `month,building,kwh`. Criterion is `G2-30PCT-R1`. The contract uses exact Decimal/fixed-point values, a 50-significant-digit Decimal percentage context, ROUND_HALF_EVEN to 0.001, then strict `>30.000`. This prototype displays approved oracle strings; it does **not** claim to implement or test Decimal arithmetic. Exact 30.000 and the near-threshold case are normal; NO_PRIOR_MONTH and ZERO_BASELINE have null percent and are never shown as 0%.

The role matrix is informational: ANALYST may attempt a new import, REVIEWER may only read; denied import/replay is ROLE_NOT_PERMITTED. Both may read synthetic history, neither may edit/delete/recompute accepted data or change the criterion. There is no login, role selector, or identity enforcement (NOT_PROVEN).

`G2-THRESHOLD-CHANGE-70` is future, unapproved and unavailable. There is no threshold switch and no 70% result.

## Design and interaction contract

The single-screen subject is a facilities analyst's energy reconciliation desk, in Chinese with exact English machine codes. Visual tokens live only in the HTML: slate ink #162d3d, blue accent #1559a5, cool paper #f1f5f8, white surface #ffffff, restrained warning #8d301e. System sans-serif handles prose; system monospace aligns inputs and machine codes. The distinctive element is the side-by-side January/February ledger with the exact per-building evidence underneath. No decorative charts imply extra measurement precision.

Native buttons and a labelled native select provide keyboard operation. Focus has a visible outline, result changes are announced through a short live status, selected paths use aria-pressed, and the result itself remains available as ordinary document content. Choosing any new path/case clears the previous outcome, so an old result cannot be mistaken for the new selection. Tables scroll within their own labelled region on narrow screens; the surrounding document reflows. No animation, modal, asynchronous request, persistence, destructive action, editable input or permission claim is present.

## Verification and proof boundary

Run `python3 checks/g3_prototype_check.py`. It checks the approved source bytes/digests, embedded fixtures, expected values, scenario coverage, native control/label structure, forbidden external effects and frozen-file preservation. The saved result records the actual checks performed. Structural checks are not browser rendering, accessibility certification, product engine acceptance, persistence, authentication, or an independent review. G3 Human approval remains pending.

### Builder verification limitation

The browser tool rejected opening this local `file://` page under its URL security policy. No alternate browser or URL was used to bypass that restriction. Actual browser rendering, narrow-viewport layout, and native keyboard interaction remain **NOT_RUN**. The checker additionally exercises all 15 scenario transitions with an in-memory DOM stub, including stale-result clearing; this is not a browser test.

During self-check, the checker initially searched the HTML source for a literal greater-than sign instead of the correctly escaped `&gt;` entity. The check was corrected; product comparison semantics did not change. Objective cause: a source-versus-rendered-text mismatch in the test assertion. Human-facing root cause: test-author oversight, not a demonstrated model capability or tool capacity limit. Control: distinguish HTML-source checks from DOM text checks, and bind scenario results to original fixtures instead of duplicate expectations.

### Supplemental UI pattern audit

The generic premium UI audit ran in strict mode and returned five findings: one unrecognized native-select ownership declaration and four supposedly actionless buttons. The native operating-system select popup is deliberately accepted for this fixed scenario picker; no authored popup is required. All four buttons have explicit `addEventListener` handlers, and the 15 DOM-stub scenarios call those registered handlers. These are static pattern-detection limitations against this vanilla HTML implementation, not a claim that the generic audit passed. Independent review should still inspect the actual controls; real browser interaction remains unverified.

The final committed-diff check also caught one trailing space in the initial CSS block, which the unstaged check had missed while the files were untracked. It was removed, and the checker now tests whitespace directly. Process control: run the final comparison against the parent commit, including newly added files.
