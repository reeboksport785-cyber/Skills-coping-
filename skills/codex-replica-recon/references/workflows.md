# Workflow map

Choose the stage that fits the request; a whole-product task can span multiple stages. Invocation uses `$codex-replica-<stage>`, or an ordinary request matching its description.

| Skill | Outcome |
| --- | --- |
| `$codex-replica-recon` | Evidence, screen/state/flow map, feature matrix |
| `$codex-replica-architect` | Architecture, schema, API and staged implementation plan |
| `$codex-replica-design` | Tokens, responsive components, contrast checks |
| `$codex-replica-build` | Working screens and user flows in the selected stack |
| `$codex-replica-backend` | Auth, persistence, permissions and authorized integrations |
| `$codex-replica-test` | Fresh relevant tests, reproducible defects and evidence |
| `$codex-replica-diff` | Functional/visual differences and missing-work order |
| `$codex-replica-entrepreneur` | Real feedback analysis and supported improvements |
| `$codex-replica-brand` | Appropriate identity and original-brand remnant checks |
| `$codex-replica-launch` | Truthful landing, pricing and listing drafts |
| `$codex-replica-deploy` | Release preflight and authorized verified deployment |

The six local helpers are contrast.py, imgdiff.py, parity.py, reviews.py, sweep.py and listing.py. They support the workflows; they do not fetch private service source code or reconstruct an inaccessible backend.
