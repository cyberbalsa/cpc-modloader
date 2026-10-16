"""Catch accidentally tracked local/game data and inconsistent package versions."""

from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_ROOTS = {".cache", ".venv", "run", "dist", "build", "mods", "assets", "saves", "cpc-modloader-data"}
BLOCKED_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".log", ".zip", ".7z", ".pem", ".key"}


def file_errors(name: str, mode: str, size: int) -> list[str]:
    path = PurePosixPath(name.lower())
    errors = []
    if mode not in {"100644", "100755"}:
        errors.append("symlinks and submodules are not allowed")
    if (path.parts[0] in BLOCKED_ROOTS or "__pycache__" in path.parts or
            path.suffix in BLOCKED_SUFFIXES or path.name.startswith(".env") or
            path.name in {"carparkcapital", "cpc-modloader", "settings.json", "imgui.ini"}):
        errors.append("local data, game files, credentials, or generated output must not be committed")
    if size > 1024 * 1024:
        errors.append("file exceeds 1 MiB; use a small synthetic fixture")
    return errors


def main() -> int:
    errors = []
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    for entry in filter(None, entries):
        metadata, name = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        if stage != "0":
            errors.append(f"{name}: unresolved merge conflict")
            continue
        # Do not follow symlinks or open submodules when checking a PR.
        size = (ROOT / name).lstat().st_size if mode in {"100644", "100755"} else 0
        errors.extend(f"{name}: {error}" for error in file_errors(name, mode, size))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    source = (ROOT / "cpcmodloader/__init__.py").read_text(encoding="utf-8")
    version = re.search(r'^__version__ = "([^"]+)"$', source, re.M)
    if not version or version[1] != project["project"]["version"]:
        errors.append("pyproject.toml and cpcmodloader.__version__ must match")
    for error in errors:
        print(error)
    if not errors:
        print("Tracked files and package versions passed.")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
