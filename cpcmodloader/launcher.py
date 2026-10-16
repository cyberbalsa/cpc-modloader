"""Build and launch private game copies on Linux and Windows."""

from __future__ import annotations

from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .patcher import PatchError, Plan, inside
from .compatibility import detect_game
from .saves import is_link, prepare_saves

APP_ID = "3031880"
OWNER = "cpcmodloader-profile.json"
DATA_DIRECTORY = "cpc-modloader-data"


def launcher_directory() -> Path:
    """Frozen releases find Mods beside the executable, regardless of Steam's cwd."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()


def default_profile(base: Path, game: Path) -> Path:
    if base.resolve().is_relative_to(game.resolve()):
        return game / DATA_DIRECTORY / "default"
    return base / "run/default"


def steam_command(arguments: list[str]) -> tuple[Path, int, list[str]]:
    """Locate the native game inside %command%, keeping Steam's runtime wrappers."""
    command = list(arguments[1:] if arguments[:1] == ["--"] else arguments)
    names = {"carparkcapital.exe", "car park capital.exe"} if os.name == "nt" else {"carparkcapital"}
    matches = [i for i, arg in enumerate(command) if Path(arg).name.lower() in names]
    if len(matches) != 1:
        raise PatchError("Steam command must contain the native Car Park Capital executable exactly once; use 'steam -- %command%'")
    index = matches[0]
    program = Path(command[index]).resolve()
    game = validate_game(program.parent)
    if not program.is_file() or program != executable(game).resolve():
        raise PatchError(f"Steam game executable is missing or unsupported: {program}")
    # The child's cwd is the private game. Preserve relative wrapper paths before moving.
    for i in range(index):
        if not command[i].startswith("-") and Path(command[i]).is_file():
            command[i] = str(Path(command[i]).resolve())
    command[index] = str(program)
    return game, index, command


def external_environment() -> dict[str, str]:
    """Keep a frozen loader's private libraries out of the game and Lua compiler."""
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            import ctypes
            if not ctypes.windll.kernel32.SetDllDirectoryW(None):
                raise ctypes.WinError()
        else:
            original = env.pop("LD_LIBRARY_PATH_ORIG", None)
            if original is None:
                env.pop("LD_LIBRARY_PATH", None)
            else:
                env["LD_LIBRARY_PATH"] = original
    return env


def show_launch_error(message: str, log: Path):
    """Steam can hide stdout: leave a readable error and show a desktop dialog."""
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(message + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "cpc-modloader", 0x10)
        elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            if dialog := shutil.which("zenity"):
                command = [dialog, "--error", "--no-markup", "--title=cpc-modloader", "--text=" + message]
            elif dialog := shutil.which("kdialog"):
                command = [dialog, "--title", "cpc-modloader", "--error", message]
            else:
                return
            # Wait so a onefile bundle remains available until the dialog exits.
            subprocess.run(command, env=external_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def validate_game(game: Path) -> Path:
    game = game.resolve()
    if not (game / "assets/scripts").is_dir():
        raise PatchError(f"not a Car Park Capital installation (assets/scripts missing): {game}")
    return game


def executable(game: Path) -> Path:
    names = ("carparkcapital.exe", "CarParkCapital.exe", "Car Park Capital.exe") if os.name == "nt" else ("carparkcapital",)
    for name in names:
        if (game / name).is_file():
            return game / name
    # Windows filenames are case insensitive, but builds may vary in capitalization.
    candidates = [p for p in game.iterdir() if p.name.lower() in {n.lower() for n in names} and p.is_file()]
    if len(candidates) == 1:
        return candidates[0]
    raise PatchError(f"native game executable missing in {game}; expected {names[0]}")


def find_game() -> Path | None:
    libraries = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                libraries.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        libraries.append(Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam")
    else:
        libraries.extend([Path.home() / ".local/share/Steam", Path.home() / ".steam/steam",
                          Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam"])
    import re
    for library in list(libraries):
        vdf = library / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8")):
                libraries.append(Path(match[1].replace("\\\\", "\\")))
    for library in libraries:
        game = library / "steamapps/common/Car Park Capital"
        if (game / "assets/scripts").is_dir():
            return game.resolve()
    return None


def copy_file(source, target):
    """Independent files, using Linux copy-on-write when the filesystem supports it."""
    if sys.platform == "linux":
        try:
            import fcntl
            with open(source, "rb") as src, open(target, "wb") as dst:
                fcntl.ioctl(dst.fileno(), 0x40049409, src.fileno())  # FICLONE
            shutil.copystat(source, target)
            return target
        except OSError:
            pass
    return shutil.copy2(source, target)


def copy_tree(source: Path, target: Path):
    # Refuse symlinks rather than making a supposedly isolated copy share state.
    for p in source.rglob("*"):
        if p.is_symlink():
            raise PatchError(f"symlink in game/profile data is unsupported: {p}")
    shutil.copytree(source, target, copy_function=copy_file)


@contextmanager
def profile_lock(profile: Path, game: Path, mods: Path):
    profile = profile.resolve()
    game = game.resolve()
    data = game / DATA_DIRECTORY
    if game.is_relative_to(profile) or (profile.is_relative_to(game) and
                                      (profile == data or not profile.is_relative_to(data))):
        raise PatchError(f"profile and game directories must not contain each other except beneath {DATA_DIRECTORY}")
    mods = mods.resolve()
    if profile.is_relative_to(mods) or mods.is_relative_to(profile):
        raise PatchError("profile and mods directories must not contain each other")
    profile.mkdir(parents=True, exist_ok=True)
    owner = profile / OWNER
    if not owner.exists() and any(profile.iterdir()):
        raise PatchError(f"refusing to use nonempty unowned profile: {profile}")
    if owner.exists():
        try:
            metadata = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PatchError(f"invalid profile marker: {owner}") from exc
        if metadata != {"format": 1, "game": str(game.resolve())}:
            raise PatchError("profile belongs to a different game installation or format")
    else:
        # Exclusive creation also prevents two initializers from claiming this profile.
        with owner.open("x", encoding="utf-8") as f:
            json.dump({"format": 1, "game": str(game.resolve())}, f)
    lock_path = profile / ".lock"
    # OS locks release on crashes and work on both platforms; keep the inode in place.
    with lock_path.open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PatchError(f"profile is already building or running: {profile}") from exc
        try:
            # Recover a build interrupted between the two directory renames.
            previous = profile / ".previous"
            current = profile / "game"
            if is_link(previous) or is_link(current):
                raise PatchError("profile game/backup directories must not be links")
            if previous.exists() and not current.exists():
                previous.rename(current)
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def syntax_check(plan: Plan, compiler: str | None = None) -> str:
    env = external_environment()
    if compiler:
        found = shutil.which(compiler)
        if not found:
            raise PatchError(f"Lua compiler not found: {compiler}")
        candidates = [found]
    else:
        candidates = [p for n in ("luac5.4", "luac54", "luac") if (p := shutil.which(n))]
    selected = None
    for candidate in candidates:
        version = subprocess.run([candidate, "-v"], env=env, capture_output=True, text=True, timeout=10)
        if "Lua 5.4" in version.stdout + version.stderr:
            selected = candidate
            break
    if not selected:
        if compiler:
            raise PatchError("--luac must point to Lua 5.4's compiler (the game's Lua version)")
        return "skipped: Lua 5.4 luac not found; install it or pass --luac"
    with tempfile.TemporaryDirectory(prefix="cpcmodloader-lua-") as directory:
        for index, (target, source) in enumerate(sorted(plan.sources.items())):
            path = Path(directory) / f"{index}.lua"
            path.write_bytes(source.encode("utf-8"))
            check = subprocess.run([selected, "-p", str(path)], env=env, capture_output=True, text=True, timeout=30)
            if check.returncode:
                raise PatchError(f"Lua syntax error in {target}:\n{check.stderr.strip()}")
    return f"passed: {len(plan.sources)} patched scripts (Lua 5.4)"


def build(game: Path, profile: Path, plan: Plan, syntax: str) -> Path:
    """Caller holds profile_lock. Publish only a completely prepared tree."""
    current = profile / "game"
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=profile))
    previous = profile / ".previous"
    try:
        copy_tree(game / "assets", stage / "assets")
        for path in game.iterdir():
            if path.name.lower() in {"cpc-modloader", "cpc-modloader.exe", "cpcmodloader.pyz"}:
                continue
            if path.is_file():
                if path.is_symlink():
                    raise PatchError(f"symlink in game root: {path}")
                copy_file(path, stage / path.name)
        # Settings stay per-profile; saves use the installed game's directory.
        for name in ("settings.json", "imgui.ini"):
            if (current / name).is_file():
                if (current / name).is_symlink():
                    raise PatchError(f"symlink in profile: {current / name}")
                copy_file(current / name, stage / name)
        if plan.game:
            copied = detect_game(stage, stage / executable(game).name)
            if (copied.executable_sha256 != plan.game.executable_sha256 or
                    copied.scripts_sha256 != plan.game.scripts_sha256 or
                    detect_game(game, executable(game)) != plan.game):
                raise PatchError("game changed during build; retry after the Steam update finishes")
        for target, source in plan.sources.items():
            if hashlib.sha256((stage / target).read_bytes()).hexdigest() != plan.original_hashes[target]:
                raise PatchError(f"source changed during build; retry after the game update finishes: {target}")
            (stage / target).write_bytes(source.encode("utf-8"))
        for target, data in plan.assets.items():
            path = inside(stage, target)
            if path.exists():
                raise PatchError(f"generated asset would overwrite a game file: {target}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        saves = prepare_saves(game, profile, stage)
        report = plan.report() | {"saves": saves, "syntax_check": syntax,
                                "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (stage / "cpcmodloader-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if previous.exists():
            shutil.rmtree(previous)
        if current.exists():
            current.rename(previous)
        try:
            stage.rename(current)
        except OSError:
            if previous.exists():
                previous.rename(current)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return current
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def run_game(directory: Path, arguments: list[str], log_path: Path, timeout: float | None = None,
             command: list[str] | None = None) -> int:
    command = command if command is not None else [str(executable(directory)), *arguments]
    env = external_environment()
    env["SteamAppId"] = APP_ID
    env["SteamGameId"] = APP_ID
    if os.name != "nt":
        env["LD_LIBRARY_PATH"] = str(directory) + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != "nt")

        def stop(force=False):
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif force:
                process.kill()
            else:
                process.terminate()

        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stop(force=True)
                process.wait()
            return 124
        except BaseException:
            if process.poll() is None:
                stop()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    stop(force=True)
                    process.wait()
            raise
