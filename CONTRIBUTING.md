# Contributing

Use the issue forms. Bug reports need the loader/game versions, OS, launch command, reproduction steps, and relevant logs. Test with an empty `Mods` folder when possible. A failure caused by one mod usually belongs with its author. Explain checks you cannot run; do not guess their results.

Redact Steam IDs, usernames, personal paths, and tokens. Do not upload game executables, extracted game scripts/assets, saves, or full Steam configuration files. See [SECURITY.md](SECURITY.md) for private vulnerability reports.

Keep each PR focused. Explain the problem, resulting behavior, and validation in the template. Discuss large features before implementing them. You are responsible for submitted code, including generated code: review it, understand it, and test it. Unexplained changes or fabricated test results are grounds to close a PR.

From a clone of the repo, use Python 3.11 or newer in a virtual environment:

```sh
python -m pip install -r requirements-dev.txt
python -m ruff check .
python scripts/check_repository.py
python -m unittest discover -s tests -v
python scripts/package.py
python dist/cpcmodloader.pyz --version
```

Install Lua 5.4 to run the Lua integration tests; without it, some tests skip. Add a regression test for a behavior change or explain why an existing test covers it. Docs-only edits need a content/link check. List the OS you tested and any platform you could not test. CI tests and packages Windows and Linux without game files; it does not replace an in-game test for launcher or overlay changes.

Do not commit generated builds, logs, caches, credentials, or files larger than 1 MiB. Use small synthetic fixtures for tests. Keep runtime dependencies optional unless a feature needs one. Preserve original game files and modded saves.

All PRs need passing checks and resolved review threads. Outside contributions also need the code owner's approval. New commits dismiss old approvals. The PR-description check requires filled `Problem`, `Changes`, and `Validation` sections and both acknowledgements; Dependabot's generated descriptions are accepted. Maintainers may request a smaller reproduction or split PR before reviewing.
