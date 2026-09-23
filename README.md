# Factory S4 synthetic sample

This public repository contains only synthetic material for the authorized Factory S4 acceptance exercise.

The sample is a monthly building-energy analysis demonstration. It uses generated CSV data and is not connected to production devices, meters, accounts, or business systems.

## Public boundary

Allowed here:

- synthetic product and review material;
- synthetic sample code and tests after the corresponding Human Gate;
- generated CSV fixtures approved for the sample;
- sanitized summaries and selected synthetic screenshots intended for public review;
- read-only specification/oracle consistency checkers and their deterministic result JSON.

Not allowed here:

- credentials, tokens, private keys, cookies, or account identifiers;
- Control source code or protected records;
- raw deployment, authentication, tool, or operational logs;
- private or real business data;
- production configuration or adoption records.

The repository preserves the G1 through G5 historical review packages and the reviewed first-slice source candidate `0f4547851c267c2094d1716ff0f1e14fc2e40bcc`. This isolated branch extends that sample under the separate `BUILD-EXPAND@R1` authorization; the expansion still requires independent technical and product review. No deployment, real business use, Control adoption, G6 result, or 70 percent threshold change follows from this source branch.

## Run the synthetic sample locally

The application uses Python's standard library. Choose a fresh temporary SQLite path and an unused high loopback port:

```sh
python3 -B -m app.server --host 127.0.0.1 --port 18765 --db /private/tmp/s4-synthetic-demo.sqlite --build-ref LOCAL-REVIEW
```

Open `http://127.0.0.1:18765/` and import `fixtures/G2-valid.csv` with a new lower-case dataset ID. The service refuses non-loopback binding. Its POST limit is 65,536 raw CSV bytes; larger requests return the G4 transport error. The `X-Synthetic-Actor` header is a declarative workflow input, with no login or identity enforcement.

Run the complete Python domain, SQLite, HTTP, and process-restart regression suite with:

```sh
python3 -B -m unittest discover -s tests -q
```

The optional real-Chrome accessibility smoke check uses an existing Playwright installation and a fresh browser profile. It verifies field errors and focus, reduced-motion result navigation, narrow-table Tab and arrow-key operation, history reload, and console health. With the sample already listening on port 18765:

```sh
NODE_PATH=<path-to-installed-node-modules> G5_CHROME=<path-to-Chrome-executable> node tests/browser_accessibility.cjs
```

No browser package is required to run the application or Python suite. The browser check writes no profile or screenshot into this repository; set `G5_SCREENSHOT_DIR` to a temporary directory if review screenshots are needed.

## Expanded contract coverage and limits

`tests/test_expand.py` drives every `G2-AC-12A` through `12R` invalid fixture through both the domain and real HTTP boundary, comparing SQLite logical contents and bytes after each rejection. It also covers error precedence, exact/reordered/quoted replay and changed-ID conflict, quoted LF/CRLF wire forms, exact decimal totals, missing month, zero baseline, exact/near/above 30 percent edges, both declarative actor read paths, and large valid ratios through the maximum HTTP request size. `tests/test_first_slice.py` continues to cover the original sample, atomic persistence, bounded storage faults, and a fresh-process restart.

Percentage arithmetic retains the approved 50-significant-digit Decimal ratio, then rounds that value to three decimals with `ROUND_HALF_EVEN` for display and the strict `> 30.000` anomaly decision. Rendering a large ratio uses enough Decimal coefficient capacity for its integer digits; it does not increase the ratio's 50-digit precision. No implicit kWh digit limit or binary float is introduced.

The browser has no role selector or authentication. Reviewer import is rejected before parsing; Analyst replay reaches canonical identity checks. `PUT`, `PATCH`, and `DELETE` still return the approved G4 `405 / METHOD_NOT_ALLOWED` transport result for both actors without mutation. That response is not evidence of the separate G2 `MUTATION_NOT_PERMITTED` or `IMMUTABLE_HISTORY` business error semantics. The 65,536-byte G4 request ceiling prevents this service from claiming acceptance of every unbounded lexical G2 input. A direct domain call with a 1,000,001-digit otherwise-valid kWh token also exceeds the Python CSV reader's default 131,072-character field limit and returns `INVALID_ROW_SHAPE`; full unbounded-domain acceptance remains open for a separate Human clarification. These limits, accessibility observations, and passing tests are not G6 acceptance or Human approval.
