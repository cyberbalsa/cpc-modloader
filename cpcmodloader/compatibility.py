"""Identify the installed game and compare explicit compatibility requirements."""

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re


# Tested Steam build 25985572, Early Access 1.0.1. Hashes contain no game data.
TESTED_BUILDS = {"25985572"}
TESTED_FILES = {
    ("1.0.1", "440ca76e686cabfb40db4f1c434a4910a0e884b4733f034c2fb9963132581074",
     "d9323b63dfb928e28fbccb9e3af0aab9745a59ad29798d146b660ccfaa06ad21"),
    ("1.0.1", "9a802851eff515824cbb7281fc700bb7b816107f6aea2c0646aeb2a0b019719b",
     "e675d744f9bad51c1cb7e43315d5ebd850eb6e49338aeafcfbb73a42978190dd"),
}


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value) or len(value) > 32:
        raise ValueError(f"expected a stable version such as 1.0.1, got {value!r}")
    return tuple(map(int, value.removeprefix("v").split(".")))


def requirements(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    if not isinstance(spec, str):
        raise ValueError("version requirement must be a string")
    result = []
    for clause in spec.split(","):
        match = re.fullmatch(r"\s*(==|>=|<=|>|<|=)?\s*(v?\d+\.\d+\.\d+)\s*", clause)
        if not match:
            raise ValueError(f"invalid version requirement: {spec!r}; use e.g. >=1.0.1, <1.1.0")
        result.append((match[1] or "==", version_tuple(match[2])))
    return result


def satisfies(version: str | None, spec: str) -> bool:
    clauses = requirements(spec)
    if version is None:
        return False
    actual = version_tuple(version)
    return all({"==": actual == wanted, "=": actual == wanted, ">=": actual >= wanted,
                "<=": actual <= wanted, ">": actual > wanted, "<": actual < wanted}[op]
               for op, wanted in clauses)


@dataclass(frozen=True)
class GameVersion:
    version: str | None
    steam_build_id: str | None
    executable_sha256: str
    scripts_sha256: str

    @property
    def supported(self) -> bool:
        return ((self.version, self.executable_sha256, self.scripts_sha256) in TESTED_FILES and
                (self.steam_build_id is None or self.steam_build_id in TESTED_BUILDS))

    @property
    def description(self) -> str:
        return f"Car Park Capital {self.version or 'unknown version'} (Steam build {self.steam_build_id or 'unknown'})"

    def report(self) -> dict:
        return asdict(self) | {"supported": self.supported}


def detect_game(game: Path, program: Path) -> GameVersion:
    data = program.read_bytes()
    versions = set(re.findall(rb"(?:Early Access |Car Park Capital v?)(\d+\.\d+\.\d+)(?=[\x00\s])", data))
    version = next(iter(versions)).decode("ascii") if len(versions) == 1 else None
    build_id = None
    # Normal Steam library layout, then SteamCMD's force_install_dir layout.
    for manifest in (game.parent.parent / "appmanifest_3031880.acf",
                     game / "steamapps/appmanifest_3031880.acf"):
        try:
            text = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if not re.search(r'"appid"\s+"3031880"', text):
            continue
        match = re.search(r'"buildid"\s+"(\d+)"', text)
        if match:
            build_id = match[1]
            break
    scripts = hashlib.sha256()
    for path in sorted((game / "assets/scripts").rglob("*.lua"), key=lambda p: p.relative_to(game).as_posix()):
        scripts.update(path.relative_to(game).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return GameVersion(version, build_id, hashlib.sha256(data).hexdigest(), scripts.hexdigest())
