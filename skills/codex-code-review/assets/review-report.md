# Code review

Scope: <repository, revision/base/head, working/staged/files; explicit exclusions>

## Findings

For each supported issue:

- Severity/title: <critical/high/medium/low and concrete failure>
- Location: <file and relevant current lines>
- Trigger/impact: <input or state causing failure and affected behavior>
- Evidence: <reproduction or code trace; distinguish inference>
- Proposed fix: <smallest sufficient change>

If none is supported, state that none was found within the reviewed scope.

## Guided tour

1. <Behavior/data flow changed, with actual code links>
2. <Validation, authorization, persistence or failure path>
3. <Relevant tests, configuration and migrations>

## Verification

<Checks actually run, commands where useful, observed results, environment and limits>

## Changes made

<Only when fixing was requested: edits, checks, remaining concerns>

Unverified: <missing access, unavailable services, unread code or unexecuted tests>
