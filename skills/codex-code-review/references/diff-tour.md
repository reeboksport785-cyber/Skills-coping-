# diff-tour provenance and optional viewer

The initial tool was [init-co-jp/diff-tour](https://github.com/init-co-jp/diff-tour). The source snapshot reviewed on 2026-10-23 was [eeaf897ce18e37018540d6b425accbed4945389c](https://github.com/init-co-jp/diff-tour/tree/eeaf897ce18e37018540d6b425accbed4945389c). That dated review does not approve newer releases or arbitrary prebuilt binaries.

`codex-code-review` is an independent instruction workflow for the current agent. It does not redistribute or install upstream code, Go dependencies, an executable or an AI backend. It has no installer hook or updater. Reasoning and project checks use the host agent's tools and permissions.

## Preserve the initial review's findings

- Downloading and immediately executing `main/install.sh` does not pin reviewed content.
- Exporting a whole Git revision can include tracked `.env` files despite `.gitignore`. Select files explicitly and inspect both versions.
- `--no-ext-diff` does not disable text conversion; use `--no-textconv` too and suppress filesystem-monitor hooks and the pager.
- Default upstream tour generation launches another AI CLI; code it reads can reach that provider and persist in caches/sessions. It is not offline analysis.
- Viewer/editor provenance, local-only behavior and input handling need separate validation.

## If a viewer is requested

1. Verify executable provenance and the hash against a trusted local build record; the filename alone is insufficient.
2. Use minimal sanitized snapshots and an explicitly reviewed local-only entry point if that build provides one. Do not assume upstream binaries accept fork-specific flags.
3. Keep external AI/generation disabled for an offline viewer request. Never silently fall back to upstream default generation.
4. If the reviewed viewer is absent, use a guided review in chat and explain the limitation. Installing/rebuilding a viewer is a separate concrete task.
