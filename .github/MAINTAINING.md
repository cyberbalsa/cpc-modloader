# Repository controls

Issue forms collect reproducible reports; they cannot verify that a report is true. API clients can bypass forms. Use `needs-information` for missing evidence and `needs-triage` until a report is understood. Close duplicates with a link. Do not close reproducible bugs just because they are old.

Before approving a fork's Actions run, inspect its workflow, dependency, and script changes. External fork runs need approval, use read-only tokens, and receive no repository secrets. Actions are pinned to commit SHAs; Dependabot proposes updates monthly.

`main` requires the `CI` and `PR description` checks, an up-to-date branch, resolved conversations, and a linear history. Force pushes and deletion are blocked. All files are owned by `@cyberbalsa`; outside PRs need one code-owner approval, dismissed when new commits arrive.

The repository admin can bypass the review requirement through a PR to merge their own work. A separate ruleset keeps required checks mandatory, including for admins. There is no direct-push bypass. Use squash merges and inspect the final diff before merging.

Settings are under [Rules](https://github.com/cyberbalsa/cpc-modloader/settings/rules) and [Actions](https://github.com/cyberbalsa/cpc-modloader/settings/actions). If checks are renamed, update the required-check ruleset too. Keep private vulnerability reporting enabled and retain secret scanning/push protection.
