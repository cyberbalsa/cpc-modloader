"""Validate PR metadata as data; never interpolate contributor text into a shell."""

import json
import os
from pathlib import Path
import re
import sys

ACKNOWLEDGEMENTS = (
    "I reviewed the full diff and can explain the changes.",
    "The validation above describes work I actually performed.",
)


def validate(pr: dict) -> list[str]:
    if pr.get("user", {}).get("login") == "dependabot[bot]" and pr["user"].get("type") == "Bot":
        return []  # Generated dependency summaries; all code/review checks still apply.
    errors = []
    title = pr.get("title", "").strip()
    if not title or title.casefold() in {"update", "fix", "changes", "test", "pull request"}:
        errors.append("Use a title that describes the specific change.")
    body = (pr.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    headings = list(re.finditer(r"^##[ \t]+([^\r\n]+)[ \t]*$", body, re.M))
    sections = {}
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        sections[match[1].strip().casefold()] = body[match.end():end]
    for section in ("Problem", "Changes", "Validation"):
        content = sections.get(section.casefold(), "")
        content = re.sub(r"^\s*-\s+\[[ xX]\].*$", "", content, flags=re.M).strip()
        if not content or re.fullmatch(r"(?i)(n/?a|none|tbd|todo|pending|\.\.\.)[.!]?", content):
            errors.append(f"Fill the {section} section with specific details (explain checks you could not run).")
    for acknowledgement in ACKNOWLEDGEMENTS:
        if not re.search(r"^\s*- \[[xX]\] " + re.escape(acknowledgement) + r"\s*$", body, re.M):
            errors.append(f"Confirm: {acknowledgement}")
    return errors


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    if "pull_request" not in event:
        print("PR metadata is missing from the event.")
        return 1
    errors = validate(event["pull_request"])
    for error in errors:
        print(error)
    if not errors:
        print("PR description includes the problem, changes, and validation.")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
