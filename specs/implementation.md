# G4 technical implementation plan — candidate, not Gate approval

Status: `G4_CANDIDATE_NOT_APPROVED`

Project: `S4-P-001`
Planned execution task after an exact G4 approval: `BUILD-SLICE@R1`
Planned activity: `IMPLEMENT_SLICE`
Required gate: `G4`

The approved G3 decision permits preparation of this plan and its completion contract only. It does not authorize the first-slice implementation. No application server, domain engine, SQLite database, connected browser flow, deployment, real-business use, Control adoption, or 70 percent criterion change is created or approved by this document.

## 1. Fixed outcome and boundaries

If Human later approves the exact G4 package, the first implementation slice will prove one synthetic vertical path on one Mac:

1. start a Python standard-library HTTP service on `127.0.0.1`;
2. import the approved synthetic CSV as raw bytes through a real HTTP request;
3. reject a negative-kWh batch and a duplicate-key batch without mutation;
4. calculate the approved monthly totals and comparisons with exact decimal arithmetic;
5. commit the accepted dataset and derived results atomically to SQLite;
6. read the accepted result through the API and browser;
7. exit the application process, start a new process against the same database, and reload the same immutable dataset ID with identical records and calculations.

The slice uses only Python's standard library: `http.server`, `sqlite3`, `csv`, `decimal`, `hashlib`, `json`, `re`, `urllib`, and ordinary filesystem/process modules. It installs no package, calls no external service, exposes no non-loopback listener, and adds no authentication claim.

The current approved criterion remains `G2-30PCT-R1`. The unapproved 70 percent proposal is absent from the API, UI, schema, configuration, and tests.

## 2. Planned files and component boundaries

Implementation files may be created only after exact G4 approval.

| File | Responsibility | May depend on |
|---|---|---|
| `app/domain.py` | Validate dataset ID and raw CSV bytes; normalize exact values; calculate totals, comparisons, and anomalies; return immutable domain values or one machine error code | Python standard library only; no HTTP or SQLite |
| `app/storage.py` | Own the SQLite schema, transactions, replay classification, immutable writes, and deterministic reads | `app.domain` value objects and `sqlite3`; no HTTP |
| `app/server.py` | Bind loopback, enforce HTTP limits and action/role preflight, translate API requests to domain/storage calls, and serve static assets | `app.domain`, `app.storage`, standard-library HTTP |
| `app/static/index.html` | Actual synthetic import, result, error, and history experience against the local API; preserve the approved G3 information hierarchy and limitation labels | Same-origin local API only; no external asset |
| `tests/` | Unit, HTTP, SQLite, browser-fixture, and process-restart checks | Fixed public synthetic fixtures only |

The domain layer receives bytes and scalar identities; it never reads files or the database. The storage layer receives a fully validated in-memory candidate and performs no CSV interpretation. The HTTP layer owns request-size and method checks but does not duplicate calculation rules. This separation lets unit tests prove business semantics without a service and lets HTTP tests prove the real boundary without treating a web response alone as calculation evidence.

## 3. HTTP and browser contract

The service binds exactly `127.0.0.1` and an explicitly supplied high port. Startup fails if a non-loopback host is requested. There is no reverse proxy, Tunnel route, TLS termination, daemon installation, public deployment, or modification to the existing Control service.

Planned endpoints:

| Method and path | Request | Response |
|---|---|---|
| `GET /api/health` | no body | build commit, criterion version, schema version, database identity, and readiness; no secret or environment dump |
| `POST /api/datasets` | raw `text/csv` bytes; required `Content-Length` from 1 through 65,536 bytes; required `X-Dataset-ID`; required declarative `X-Synthetic-Actor: ANALYST` | `201` with the immutable dataset result, or one exact rejection code |
| `GET /api/datasets` | required actor `ANALYST` or `REVIEWER` | deterministic history summary |
| `GET /api/datasets/{dataset_id}` | required actor `ANALYST` or `REVIEWER` | original rows, totals, comparisons, anomaly list, criterion, canonical identity, and record IDs |

Raw CSV bytes remain the POST body so invalid UTF-8, BOM, LF/CRLF, bare-CR, mixed-ending, and quoted-newline cases can be tested at the real boundary. The dataset ID and declarative actor are ASCII headers. The actor header implements the approved workflow matrix for acceptance testing; it is not authentication or user isolation. Every screen and report must keep `NO_LOGIN` and `IDENTITY_ENFORCEMENT_NOT_PROVEN` visible.

The first-slice transport profile is exact: a missing length is HTTP 411 / `HTTP_LENGTH_REQUIRED`, a length above 65,536 bytes is HTTP 413 / `HTTP_PAYLOAD_TOO_LARGE`, a non-`text/csv` media type is HTTP 415 / `HTTP_MEDIA_TYPE_REQUIRED`, and an unsupported method is HTTP 405 / `METHOD_NOT_ALLOWED`. These are technical envelope results, not new G2 business-validation codes. They are selected before reading a body and never mutate state. The 65,536-byte ceiling is a G4 resource boundary for this slice; the slice does not claim that larger otherwise-valid G2 inputs have been accepted or rejected under the full product contract.

The first browser screen keeps the G3 ledger-first layout but replaces fixed scenario buttons only where the approved first slice has a real endpoint: dataset ID, synthetic CSV file selection, import action, exact error/result panel, and history reload. It sends the selected bytes to the local API and renders only returned canonical values. It does not add threshold editing, delete/edit/recompute controls, login, production branding, telemetry, external fonts, or network assets.

The server rejects unsupported methods with a deterministic `METHOD_NOT_ALLOWED`; it never maps PUT, PATCH, or DELETE to mutation. JSON errors use one stable shape:

```json
{"ok":false,"error":{"code":"NEGATIVE_KWH","message":"synthetic batch rejected"}}
```

The machine code is authoritative. Human-readable text may explain it but cannot replace it.

## 4. Domain algorithm

The parser applies the approved error priority in `specs/error-catalog.json`:

1. reject a disallowed actor before reading the body;
2. enforce a bounded body size, strict UTF-8, no BOM, one consistent LF or CRLF convention, canonical dataset ID, exact header, and non-empty data;
3. parse the selected RFC 4180 subset and validate each row in physical order: month, building, kWh;
4. validate the complete payload before duplicate or replay checks;
5. reject duplicate `(month, building)` keys;
6. construct the replay identity from dataset ID plus canonical rows sorted by `(month, building)`;
7. compute totals and comparisons before opening a write transaction.

`decimal.Decimal` runs under an explicit 50-significant-digit local context. Input kWh accepts at most three fractional digits and is serialized at exactly three. The parser first forms a canonical arbitrary-precision integer-thousandths value without binary float. Totals use exact arbitrary-precision addition. For a positive prior month, the service calculates the ratio, quantizes it to `0.001` using `ROUND_HALF_EVEN`, and applies strict `quantized_percent > Decimal("30.000")`. `NO_PRIOR_MONTH` and `ZERO_BASELINE` store null percent and `anomaly=false`. The first slice exercises `NO_PRIOR_MONTH`; the frozen `ZERO_BASELINE` rule is reserved for a later approved batch and is not a first-slice test or completion obligation.

Domain output is immutable and contains the source-byte SHA-256, canonical-row SHA-256, exact rows, totals, comparisons, anomalies, and `criterion_version=G2-30PCT-R1`. No binary float enters calculation, persistence, JSON encoding, or assertions.

## 5. SQLite design and transaction boundary

The database uses foreign keys, `journal_mode=DELETE`, and `synchronous=FULL`. Schema creation is an explicit setup step; ordinary restart performs no migration or timestamp update. The first slice uses one process and bounded requests, so no connection pool or background worker is introduced.

Planned tables:

- `datasets(dataset_id PRIMARY KEY, source_bytes BLOB, source_sha256, canonical_sha256, criterion_version, accepted_sequence UNIQUE)`;
- `source_rows(dataset_id, ordinal, month, building, kwh_token, kwh_milli_text, PRIMARY KEY(dataset_id, ordinal), UNIQUE(dataset_id, month, building))`;
- `monthly_totals(dataset_id, month, total_milli_text, PRIMARY KEY(dataset_id, month))`;
- `comparisons(dataset_id, month, building, status, percent_change_milli_text NULL, anomaly, PRIMARY KEY(dataset_id, month, building))`.

The bounded accepted source bytes and original valid kWh token are preserved alongside the canonical row representation. Values ending in `_milli_text` are canonical base-10 integer-thousandths stored as SQLite `TEXT`, so SQLite's signed 64-bit `INTEGER` range cannot truncate an otherwise representable approved value. Non-negative energy values use `0|[1-9][0-9]*`; signed percentages use `-?(0|[1-9][0-9]*)`. The domain layer supplies and validates these strings; SQLite never casts them to `REAL` or performs energy or percentage arithmetic. Status and anomaly columns have CHECK constraints. Derived tables reference `datasets` with foreign keys and cannot outlive it.

G2 fixes a 50-significant-digit percentage context but does not bound the number of input digits. The first slice proves the fixed public sample and named negative controls only, all within that context; it does not claim every syntactically valid huge ratio. Before a later batch or G6 can claim the complete numeric domain, an independent analysis must prove that the 50-digit rule yields a defined three-decimal result across that domain or route an explicit G2 clarification through its own Human decision. No implicit size limit, SQLite coercion, or binary float may be used to hide that open point.

Before `BEGIN IMMEDIATE`, the service completes wire, row, duplicate, and calculation validation. Inside the transaction it reads any existing `dataset_id`. Equal canonical rows produce `DUPLICATE_DATASET_REPLAY`; different rows produce `DATASET_ID_REUSE_CONFLICT`; both roll back without writes. A new dataset inserts its envelope, original rows, totals, and comparisons in one transaction. Any exception rolls back and returns a bounded internal error without a partial history row.

No edit, delete, overwrite, in-place recompute, or criterion mutation operation exists. Direct inspection tests compare row counts and canonical query results before and after every rejected batch.

## 6. First slice and later batches

### First slice after G4 approval

The first slice is deliberately one complete path rather than many partial features:

- primary valid sample `fixtures/G2-valid.csv` under dataset ID `g2-sample-2026-01-02`;
- totals `300.000` and `370.000`;
- A at `60.000%` anomalous, B at `5.000%` normal, and both January rows `NO_PRIOR_MONTH`;
- negative batch rejection using `fixtures/G2-negative.csv`, with no mutation;
- duplicate-key batch rejection using `fixtures/G2-duplicate.csv`, with no mutation;
- real browser import/read path on loopback;
- process A exit followed by process B start on the same database and exact same-ID reload;
- stable dataset and result record identities plus unchanged calculation JSON across restart.

The first slice does not claim the entire G2 catalog. Its package and evidence must state which scenarios ran and which remain for later approved batches.

### Later batches, only after G5 approval

Later batches may add the remaining error-priority cases, replay/conflict variants, quoted fields, exact-decimal and threshold edges, missing-month and zero-baseline cases, the complete Analyst/Reviewer action matrix, browser accessibility refinements, packaging, and full regression. G5 approval may release only work already inside the approved G4 route. The separate 30-to-70 criterion change still requires its own G2 revision decision and is not a later batch by default.

## 7. Test and evidence plan

The Builder must first add tests that fail for missing implementation, then implement the smallest first slice that makes them pass. Required evidence is tied to the exact source commit, test inputs, service process, database and browser session.

### Domain and storage

- unit assertions for the valid sample, negative rejection, duplicate-key rejection, Decimal formatting, threshold comparison, and the `NO_PRIOR_MONTH` state exercised by the slice;
- transaction assertions that a rejected mixed batch leaves all four tables unchanged;
- direct SQLite checks for foreign keys, unique keys, canonical integer-thousandths text, criterion version and immutable same-ID behavior;
- a test that no binary float is present in domain or persistence values.

### Real HTTP and restart

- start the actual server on an allocated loopback port and send raw bytes with `urllib.request`;
- verify status, content type, error code, dataset identity and canonical result body;
- verify actor preflight occurs before body parsing; Reviewer import, unsupported methods, missing/oversized length and wrong media type all fail without a database mutation;
- capture source commit, build input hashes, PID, process start time, listener, database path/hash, schema version and input hashes;
- stop process A cleanly, prove it is no longer listening, start process B with a different PID, and read the same dataset ID;
- compare the persisted record IDs, canonical API body, table contents and database bytes before and after the read-only restart;
- retain one isolated wrong-candidate negative control only when the acceptance plan reaches that separately prepared test; never point the shared Control service at the sample app.

### Browser and independent judgment

- exercise import, exact error presentation, valid result, history and restart reload in a real browser at desktop and narrow viewport;
- verify keyboard operation, focus visibility, stale-result clearing, scroll containment and an empty console;
- an independent technical reviewer checks source identity, HTTP, SQLite, atomicity, calculations and restart evidence;
- an independent product reviewer checks the actual experience against the frozen G3 information and interaction contract;
- Builder self-checks and static UI audits cannot substitute for either independent decision.

The frozen completion contract is `control-inputs/G4-FIRST-SLICE-completion-contract.json`. A completion claim can be satisfied only by exact artifacts from one candidate and one execution observation, with independent `SOURCE_AUTHENTICITY` and `BUSINESS_COMPLIANCE` records covering every required output. A green test suite alone does not satisfy the contract.

The current Control wire format has only the formal purposes `SOURCE_AUTHENTICITY` and `BUSINESS_COMPLIANCE`; it cannot encode invented `TECHNICAL_COMPLIANCE` or `PRODUCT_COMPLIANCE` purposes. It also does not itself require two different `BUSINESS_COMPLIANCE` record identities or limit a claim to one observation. Therefore, before recording the claim, a protected preparation check must require exactly one observation reference and distinct technical and product verification record references, both tied to that observation and candidate. The formal coverage rows retain separate technical and product tokens, and the two native record readbacks are preserved. This is an explicit `AGENT_COMPLIANCE` process control and limitation, not a claim of technically unbypassable reviewer separation.

## 8. Risks and intentional simplifications

- **No identity boundary.** Actor headers are declarative and spoofable. Reports retain `IDENTITY_ENFORCEMENT_NOT_PROVEN`; no security acceptance is claimed.
- **Loopback HTTP only.** There is no TLS because the service is not network-exposed. Binding any non-loopback address is a hard failure.
- **Single-process SQLite.** The slice does not claim multi-writer scalability. `BEGIN IMMEDIATE`, bounded payloads and one service process make the accepted concurrency model explicit.
- **Standard-library server.** The implementation avoids frameworks, background workers, migrations and frontend builds. It must compensate with explicit body limits, method handling, content types, escaping and deterministic shutdown tests.
- **CSV edge complexity.** Wire-ending and quoted-field rules are checked before ordinary CSV parsing where needed, so `csv` defaults cannot silently normalize forbidden inputs.
- **Restart evidence.** A page showing a version string is insufficient. Evidence binds the commit, process A/B identity, listener, input, database and returned record IDs.
- **Public synthetic material.** Only approved fixtures, plan text and bounded evidence may enter this repository. Raw operational logs, credentials, private paths containing secrets, Control source and real data remain excluded.

## 9. Gate decision requested

Human G4 review decides whether this exact route, dependency set, complexity, resource boundary, first slice, later-batch split, risks and completion contract may authorize `BUILD-SLICE@R1`. Approval of the future frozen G4 submission would permit only the first slice described here. It would not approve the first-slice result, release later batches, accept G5/G6, deploy the app, adopt Control, use real business data, or change the criterion to 70 percent.
