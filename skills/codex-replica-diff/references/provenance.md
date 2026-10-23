# Provenance

Adapted for Codex from the workflow and local tools in [Jakeschincariol/replica-skill](https://github.com/Jakeschincariol/replica-skill/tree/77c9436fb3d18c3d58169efb8caf4fe906b0dc51), commit `77c9436fb3d18c3d58169efb8caf4fe906b0dc51`, reviewed on 2026-10-23.

Original copyright: Jake Schincariol, 2026. See [LICENSE](../LICENSE). This adaptation is independent and is not endorsed by the original author. Native Codex metadata, tool routing, side-effect boundaries and evidence requirements replace Claude plugin commands. Bundled Python tools are hardened local adaptations; they make no network calls and are not general security scanners.

Keep source attribution when distributing adapted tools. Review and test changes before updating the installed skill; installation never grants access to third-party accounts or permission to publish another project.

## Runtime and limits

These are workflows plus local helpers, not a service-code downloader. Helpers use only the Python standard library, were tested on Python 3.12, and require POSIX no-follow directory/file operations (Linux, macOS or WSL). They refuse unsafe links and existing output paths rather than silently falling back. Native Windows requires WSL. No installer, background service, telemetry or automatic upstream update is included.

Bounds and exclusions are part of the result: oversized/unsupported inputs are untested, and redaction is heuristic rather than universal anonymization. Inspect reports before sharing them. Use each helper's `--help` for exact accepted formats and options.

## Maintenance checks

The portable tests cover all six helpers in the five sibling tool-bearing skills. From this file's actual skill directory, run:

```sh
python3 -I -B -m unittest discover -s <skill-dir>/scripts/tests -v
```

Keep all eleven skill directories as siblings for this suite. Run the tests after changes; preserve the pinned provenance and MIT notices. Hashes authenticate the reviewed snapshot against the fetched Git tree, not the publisher's identity or future updates.
