# Evidence and feature contract

Use project-local `replica/` artifacts shared by the eleven Codex replica skills. Preserve existing IDs and files; never overwrite user evidence to fit a template.

## Features CSV

Required columns: `feature,area,priority,original,clone,notes`.

- `feature`: a distinct observable behavior, optionally prefixed with a stable feature ID.
- `area`: workflow or product area; reference screen S-IDs and flow F-IDs in notes.
- `priority`: `must`, `should` or `could`, based on the user's requested scope.
- `original`: `yes` if observed/evidenced, `no` for our independent additions, `unknown` for inaccessible behavior. Do not claim inferred functionality is verified.
- `clone`: `no`, `partial`, `yes` or `skip`. `yes` needs actual implementation/test evidence. `skip` needs a reason and must remain visible in coverage reports.
- `notes`: dated source/evidence, implementation status, test ID or reason for exclusion. Minimize personal details.

The parity helper weights must/should/could as 3/2/1 and partial as half credit. It is a planning metric, not proof of equivalence or readiness. Report evaluated, excluded and unknown counts next to the percentage. A requested must-have cannot become an accepted exclusion merely to pass a gate.

## Research map

For every source keep URL/reference, access date, coverage and confidence. Use `observed`, `inferred`, `unverified` consistently. A screenshot proves an appearance/state; it does not prove authorization, persistence, billing correctness or the private schema.

Screens: `S-ID | route/entry | purpose | components | states | source`.
Flows: `F-ID | user goal | screen path | branches/errors | completion condition | source`.
Entities: `entity | fields/relationships | evidence | confidence | unresolved constraints`.

Store permitted reference images separately from shipped assets. Do not persist account details, private payment screens or authentication material as shared research.
