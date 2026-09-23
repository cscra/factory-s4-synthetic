# G5 independent technical review

Status: `PASS_ZERO_OPEN_P0_P1_P2_P3`

Reviewed source candidate: `0f4547851c267c2094d1716ff0f1e14fc2e40bcc`

Reviewed tree: `e0c8675bb10dd9016377d9491a7252ed9d491a0d`

Reviewed observation: `OBS-S4-G4-FIRST-SLICE-004`

Reviewer role: independent technical reviewer; did not participate in implementation

Requested execution configuration: `gpt-6-sol`, `high`, Fast

The reviewer independently matched local `HEAD`, `origin/main`, and a fresh remote ref read to the fixed source candidate. The eight source, fixture, and test files in the source identity were recomputed from Git bytes. An independent full run passed 28 of 28 tests.

The negative path was checked from fresh state: both history reads were empty, the expected request returned only `422 / NEGATIVE_KWH`, and the SQLite file stayed at 45,056 bytes with the same SHA-256 and zero rows in all four tables. The accepted path produced exact stored totals `300000` and `370000`, API totals `300.000` and `370.000`, and the expected `1/4/2/4` table row counts.

Chrome 153 evidence showed the fixed validation pattern, no unexpected target-page console errors, visible monthly totals, a 650px document without page-level horizontal overflow, a labelled focusable table region, visible focus, and keyboard scroll `0 -> 108 -> 0`. Process A and Process B used distinct process identities and the same database; after restart, the database bytes, API result, canonical result, record identity, and browser result remained equal. The app listeners and isolated Chrome process were stopped.

The 67-file private evidence inventory was recomputed with no missing, extra, or mismatched accepted-evidence file. Its manifest SHA-256 is `805fb25735727046f7c5e9975623e56dc59a3a17a3c5dc2f2bb247f6f15eb89c`. Earlier observations remain unchanged: OBS-002 is a historical failure and OBS-003 is not eligible as final completion evidence.

The objective cause of the earlier failures was incomplete test derivation from the frozen G3/G4 contract: the first implementation omitted visible monthly totals and keyboard semantics, while OBS-003 used stale negative-state evidence and an incomplete evidence inventory. Those were inherited from the earlier G4 implementation and OBS-003 evidence design; this candidate and OBS-004 introduced no new P0-P3 defect.

The Human-facing root cause was process discipline rather than unavailable tools: the implementation and evidence checklists were not generated line by line from the frozen contract before the first run. Git, Chrome/CDP, SQLite, and hashing were sufficient, and the review found no evidence that model capability or tool access blocked a correct result. Future slices should derive code assertions, browser observations, database snapshots, process-restart checks, and manifest closure directly from each frozen obligation before execution.

This is a technical verification record candidate. It does not approve G5, release later batches, prove authentication, authorize deployment or real business use, change the 30 percent criterion, or adopt Factory Control.
