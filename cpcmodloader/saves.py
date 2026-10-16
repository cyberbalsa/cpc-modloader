"""Keep the game's normal save directory visible from patched game copies."""

from __future__ import annotations

import filecmp
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .patcher import PatchError


def is_link(path: Path) -> bool:
    """Include Windows junctions on Python 3.11, before Path.is_junction."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def link_directory(target: Path, link: Path):
    try:
        if os.name == "nt":
            # CPython's native junction API avoids cmd.exe quoting and does not
            # require Developer Mode or symbolic-link privileges.
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        raise PatchError(f"cannot link the game's saves at {target}: {exc}. "
                         "Use a filesystem that supports directory links.") from exc


def legacy_files(directory: Path) -> list[Path]:
    """Do not follow links while backing up a pre-0.1.3 save directory."""
    def unreadable(error):
        raise error

    files = []
    for root, directories, names in os.walk(directory, onerror=unreadable):
        for name in directories + names:
            path = Path(root) / name
            if is_link(path):
                raise PatchError(f"link in old profile saves is unsupported: {path}")
            if not path.is_dir():
                if not path.is_file():
                    raise PatchError(f"not a regular save file: {path}")
                files.append(path.relative_to(directory))
    return sorted(files)


def prepare_saves(game: Path, profile: Path, stage: Path) -> dict:
    target = (game / "saves").resolve()
    if target.is_relative_to(profile) or profile.is_relative_to(target):
        raise PatchError("the game's save directory must be outside the profile")
    target.mkdir(parents=True, exist_ok=True)
    old = profile / "game/saves"
    report = {"directory": str(target), "backup": None, "imported": [], "conflicts": []}
    if is_link(old):
        if old.resolve() != target:
            raise PatchError(f"profile saves point somewhere other than the game's saves: {old}")
        files = []
    elif old.exists():
        if not old.is_dir():
            raise PatchError(f"profile saves are not a directory: {old}")
        files = legacy_files(old)
    else:
        files = []

    # Never fall back to separate saves if directory links are unavailable.
    link_directory(target, stage / "saves")
    if files:
        backup = Path(tempfile.mkdtemp(prefix="saves-backup-", dir=profile)) / "saves"
        shutil.copytree(old, backup)
        report["backup"] = str(backup)
        for relative in files:
            # Steam owns this metadata; an old profile must not replace it.
            if relative.name == "steam_autocloud.vdf":
                continue
            source = backup / relative
            destination = target / relative
            parent = target
            blocked = False
            for part in relative.parts[:-1]:
                parent /= part
                if is_link(parent) or (parent.exists() and not parent.is_dir()):
                    blocked = True
                    break
                parent.mkdir(exist_ok=True)
            if blocked or is_link(destination):
                report["conflicts"].append(relative.as_posix())
                continue
            if destination.exists():
                if not destination.is_file() or not filecmp.cmp(source, destination, shallow=False):
                    report["conflicts"].append(relative.as_posix())
                continue
            # Exclusive creation protects against a cloud download arriving
            # between the existence check and this copy.
            try:
                output = destination.open("xb")
            except FileExistsError:
                report["conflicts"].append(relative.as_posix())
                continue
            try:
                with output, source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                shutil.copystat(source, destination)
            except BaseException:
                destination.unlink()
                raise
            report["imported"].append(relative.as_posix())
        print(f"Old profile saves backed up to: {backup}", flush=True)
        print(f"Imported {len(report['imported'])} missing saves; "
              f"kept {len(report['conflicts'])} conflicting files in the backup. "
              "Existing game saves were not overwritten.", flush=True)
    print(f"Saves: {target}", flush=True)
    return report
