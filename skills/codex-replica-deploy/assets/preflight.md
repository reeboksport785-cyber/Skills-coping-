# Release record

- Project, target account/environment and exact revision:
- User-authorized action and scope:
- Preview/build artifact:
- Production changes proposed:
- Recovery/rollback owner and procedure:

| Check | Exact command/evidence | Result | Limitation/required next action |
| --- | --- | --- | --- |
| Relevant tests and build | <fresh evidence> | unverified | <limits> |
| Coverage and critical defects | <matrix and bug IDs> | unverified | <limits> |
| Dependencies and secrets | <actual scan scope> | unverified | <limits> |
| Tenant/role isolation | <synthetic cross-account cases> | unverified | <limits> |
| Payments/integrations | <test mode, retry and entitlement cases> | unverified | <limits> |
| Migrations/backups/rollback | <staging/recovery evidence> | unverified | <limits> |
| Production identity/assets | <provenance and checks> | unverified | <limits> |
| Domain/HTTPS/configuration | <provider-reported values> | unverified | <limits> |
| Actual deployed revision and health | <observed result> | unverified | <limits> |

Allowed result labels: confirmed, partial, unverified, failed. Do not treat a skipped or unavailable check as passed. Keep preview readiness distinct from production readiness.

Record only actual observed URLs and changes. Do not perform a real purchase/refund, send messages, modify unrelated services or enable recurring jobs unless the corresponding instruction authorizes it.
