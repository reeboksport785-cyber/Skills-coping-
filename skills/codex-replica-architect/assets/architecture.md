# Implementation architecture

## Evidence and decisions

Source map/version, existing stack, constraints, assumptions and unresolved requirements. Record options and the concrete reason for each choice.

## Data model

| Entity | Ownership | Fields/types | Constraints | Indexes | Retention |
| --- | --- | --- | --- | --- | --- |
| <entity> | <user/tenant/public> | <fields> | <invariants> | <queries> | <policy> |

## API and jobs

| Flow | Route/action | Caller and authorization | Input limits | Result/errors | Idempotency/retry |
| --- | --- | --- | --- | --- | --- |
| F01 | <action> | <policy> | <validation> | <contract> | <mechanism> |

## Incremental delivery

Core vertical slice, remaining requested flows/states, integration seams and evidence needed to mark each complete. Keep real services and temporary mocks distinguishable.

## Failure and recovery

Transactions/concurrency, missing-provider behavior, backups, migration/rollback, isolation, secret handling and relevant tests.
