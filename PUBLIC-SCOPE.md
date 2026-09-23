# Public scope

Repository: `cscra/factory-s4-synthetic`

Purpose: public synthetic material for `S4-P-001` only.

This repository does not authorize production use, Control adoption, access to real business systems, or publication of protected Control records. It must not contain secrets, private data, raw operational logs, or the private Control implementation.

The ordinary Agent may write sample material here. Human decisions and formal records remain in the separate protected records repository and are written only through the authorized Recorder path.

The public whitelist also includes read-only specification/oracle consistency checkers and their deterministic, sanitized result JSON. Such a checker is review material and does not authorize product code, a prototype, deployment, or a Human decision.

After an exact Human Gate decision, the whitelist also permits sanitized, synthetic execution-contract inputs under `control-inputs/`. They contain no credentials or operational logs, are not protected record entries themselves, and obtain no authority until the restricted Control recorder validates and publishes them.

For G5 review, the whitelist permits bounded synthetic execution summaries and selected screenshots under `evidence/g4-first-slice/`. Raw browser profiles, local paths, process logs, authentication traces, private Control records, and the complete operational evidence set remain excluded.
