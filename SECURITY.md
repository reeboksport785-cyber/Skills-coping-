# Security scope

`START-HERE.md` routes a user's current request to one of the twelve skills. `codex-code-review` is an instruction-only review workflow with a report template and dated diff-tour notes. It does not install diff-tour or launch another AI CLI. Reading the entrypoint does not install a plugin, grant project access, enable background updates or authorize deployment. Host-model processing is not offline analysis.

The six bundled runtime helpers use Python standard-library code and local I/O. They do not fetch URLs, run external commands, install dependencies, or self-update. The workflows can use an agent's separately available browser/connectors within the user's requested scope.

Review [the dated audit](docs/security-review.ru.md), the pinned upstream provenance in each skill, and `--help` before processing unfamiliar files. Resource bounds, unsupported formats and skipped files limit the result. Contact-pattern redaction is heuristic, not complete anonymization. Do not put secrets or personal exports in public issues or examples.

A passing parity, contrast or listing check does not establish application security or deployment readiness. Use real tests for the implementation. Existing output paths, symlinks, hard links and special-file inputs are refused rather than followed.

For a suspected vulnerability, share a minimal synthetic reproduction with the repository owner privately. Never attach live keys, customer records or a real account export. No security support SLA is promised.
