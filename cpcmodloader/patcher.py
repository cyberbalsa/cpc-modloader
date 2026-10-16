"""Deterministic, in-memory patch compilation. Never writes to the game."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from importlib.resources import files as resource_files
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tomllib


class PatchError(Exception):
    """A manifest cannot be safely or unambiguously applied."""


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PatchError("expected a nonempty relative path")
    value = value.replace("\\", "/")
    if "." in value.split("/"):
        raise PatchError(f"path must not contain '.' components: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or PureWindowsPath(value).drive or ".." in p.parts:
        raise PatchError(f"path must stay inside its root: {value!r}")
    # These names are not portable to Windows; ':' also allows NTFS streams.
    for part in p.parts:
        if any(c in part for c in ':<>|"') or part.endswith((".", " ")):
            raise PatchError(f"nonportable path: {value!r}")
        if part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise PatchError(f"reserved Windows path: {value!r}")
    if str(p) == ".":
        raise PatchError("path must name a file")
    return p.as_posix()


def inside(root: Path, value: str) -> Path:
    p = (root / relative_path(value)).resolve()
    if not p.is_relative_to(root.resolve()):
        raise PatchError(f"path escapes root through a symlink: {value}")
    return p


def target_path(value: str) -> str:
    value = relative_path(value.removeprefix("@"))
    if value.startswith("assets/scripts/"):
        value = value[len("assets/scripts/"):]
    elif value.startswith("scripts/"):
        value = value[len("scripts/"):]
    if not value.endswith(".lua"):
        raise PatchError(f"target must be a .lua script: {value}")
    return "assets/scripts/" + value


def read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise PatchError(f"cannot read UTF-8 source {path}: {exc}") from exc


def wildcard(pattern: str) -> re.Pattern:
    return re.compile(re.escape(pattern).replace(r"\*", ".*").replace(r"\?", "."))


def string(data: dict, key: str, default=None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise PatchError(f"{key} must be a string")
    return value


def boolean(data: dict, key: str, default=False) -> bool:
    value = data.get(key, default)
    if type(value) is not bool:
        raise PatchError(f"{key} must be a boolean")
    return value


def integer(data: dict, key: str, default=None, minimum=None):
    value = data.get(key, default)
    if value is None and default is None:
        return None
    if type(value) is not int or (minimum is not None and value < minimum):
        raise PatchError(f"{key} must be an integer" + (f" >= {minimum}" if minimum is not None else ""))
    return value


def strings(value, label: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise PatchError(f"{label} must be a string or nonempty array of strings")
    return value


def only_keys(data: dict, allowed: set[str], label: str):
    if not isinstance(data, dict):
        raise PatchError(f"{label} must be a table")
    extra = data.keys() - allowed
    if extra:
        raise PatchError(f"unknown {label} field(s): {', '.join(sorted(extra))}")


@dataclass
class Manifest:
    path: Path
    root: Path
    priority: int
    patches: list
    variables: dict

    @property
    def label(self):
        return f"{self.root.name}/{self.path.relative_to(self.root).as_posix()}"


@dataclass
class Plan:
    sources: dict[str, str] = field(default_factory=dict)
    original_hashes: dict[str, str] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)

    def report(self):
        return {
            "format": 1,
            "manifests": self.manifests,
            "patches": self.events,
            "files": {
                name: {"original_sha256": self.original_hashes[name],
                       "patched_sha256": hashlib.sha256(text.encode()).hexdigest()}
                for name, text in sorted(self.sources.items())
            },
        }


def discover(mods: Path) -> list[Manifest]:
    if not mods.exists():
        return []
    if not mods.is_dir():
        raise PatchError(f"mods directory is not a directory: {mods}")
    result = []
    for root in sorted(mods.iterdir(), key=lambda p: p.name):
        if not root.is_dir() or root.name.startswith(".") or (root / ".disabled").exists():
            continue
        canonical = [root / "cpcmodloader.toml", *sorted((root / "cpcmodloader").rglob("*.toml"))]
        lovely = [root / "lovely.toml", *sorted((root / "lovely").rglob("*.toml"))]
        canonical = [p for p in canonical if p.is_file()]
        lovely = [p for p in lovely if p.is_file()]
        if canonical and lovely:
            raise PatchError(f"{root.name}: use cpcmodloader or lovely manifests, not both")
        for path in canonical or lovely:
            inside(root, path.relative_to(root).as_posix())
            try:
                data = tomllib.loads(read_text(path))
                only_keys(data, {"manifest", "vars", "patches"}, "top-level")
                meta = data.get("manifest", {})
                only_keys(meta, {"version", "priority", "enabled", "dump_lua"}, "manifest")
                if string(meta, "version") != "1.0.0":
                    raise PatchError("manifest.version must be '1.0.0'")
                if not boolean(meta, "enabled", True):
                    continue
                boolean(meta, "dump_lua", False)  # Already available in the generated profile.
                priority = integer(meta, "priority", 0)
                variables = data.get("vars", {})
                if not isinstance(variables, dict) or not all(isinstance(v, str) for v in variables.values()):
                    raise PatchError("vars must be a table of strings")
                patches = data.get("patches", [])
                if not isinstance(patches, list):
                    raise PatchError("patches must be an array of tables")
                result.append(Manifest(path, root, priority, patches, variables))
            except (PatchError, tomllib.TOMLDecodeError) as exc:
                raise PatchError(f"{path}: {exc}") from exc
    return sorted(result, key=lambda m: (m.priority, m.label))


def substitute(text: str, manifest: Manifest) -> str:
    def replace(match):
        key = match[1]
        if key not in manifest.variables:
            raise PatchError(f"undefined variable: {key}")
        return manifest.variables[key]
    return re.sub(r"\{\{(?:cpcmodloader|lovely):([^{}]+)\}\}", replace, text)


def newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def with_newlines(text: str, nl: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", nl)


def join_code(left: str, right: str, nl: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return left + ("" if left.endswith(("\r", "\n")) else nl) + right


def check_count(data: dict, count: int):
    optional = boolean(data, "optional")
    expected = integer(data, "expected_matches", minimum=0)
    if expected is not None and count != expected:
        raise PatchError(f"expected {expected} matches, found {count}")
    if count == 0 and not optional and expected != 0:
        raise PatchError("pattern matched 0 times (game update or mod conflict)")


def pattern_patch(text: str, data: dict, payload: str):
    pattern = string(data, "pattern")
    patterns = [wildcard(line.strip()) for line in pattern.splitlines()]
    if not patterns:
        raise PatchError("pattern cannot be empty")
    position = string(data, "position")
    if position not in {"before", "after", "at"}:
        raise PatchError("pattern.position must be before, after, or at")
    indent = boolean(data, "match_indent")
    boolean(data, "overwrite")  # Lovely's legacy no-op.
    limit = integer(data, "times", minimum=1)
    nl = newline(text)
    lines = text.splitlines(keepends=True)
    matches, i = [], 0
    while i + len(patterns) <= len(lines):
        if all(p.fullmatch(line.strip()) for p, line in zip(patterns, lines[i:])):
            matches.append(i)
            i += len(patterns)
        else:
            i += 1
    check_count(data, len(matches))
    selected = matches[:limit]
    for start in reversed(selected):
        end = start + len(patterns)
        prefix = re.match(r"[ \t]*", lines[start])[0] if indent else ""
        body = with_newlines(payload, nl)
        body = "".join(prefix + line for line in body.splitlines(keepends=True))
        if body and not body.endswith(nl):
            body += nl
        if position == "at":
            lines[start:end] = [body]
        elif position == "before":
            lines[start:start] = [body]
        else:
            if body and not lines[end - 1].endswith(("\n", "\r")):
                lines[end - 1] += nl
            lines[end:end] = [body]
    return "".join(lines), len(matches), len(selected)


def expand_capture(payload: str, match: re.Match) -> str:
    # Lovely-style $name / ${name} / $1 / $$, not Python replacement escapes.
    def replace(token):
        if token[0] == "$$":
            return "$"
        key = token[1] or token[2]
        try:
            return match.group(int(key) if key.isdigit() else key) or ""
        except (IndexError, KeyError) as exc:
            raise PatchError(f"unknown regex capture ${key}") from exc
    return re.sub(r"\$\$|\$\{(\w+)\}|\$(\w+)", replace, payload)


def regex_patch(text: str, data: dict, payload: str):
    pattern = string(data, "pattern")
    if not pattern:
        raise PatchError("regex pattern cannot be empty")
    pattern = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", pattern)
    try:
        regex = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise PatchError(f"invalid regex: {exc}") from exc
    position = string(data, "position")
    if position not in {"before", "after", "at"}:
        raise PatchError("regex.position must be before, after, or at")
    limit = integer(data, "times", minimum=1)
    matches = list(regex.finditer(text))
    check_count(data, len(matches))
    selected = matches[:limit]
    for match in reversed(selected):
        body = expand_capture(payload, match)
        prefix = expand_capture(string(data, "line_prepend", ""), match)
        body = with_newlines("".join(prefix + line for line in body.splitlines(keepends=True)), newline(text))
        if position == "before":
            body += match[0]
        elif position == "after":
            body = match[0] + body
        text = text[:match.start()] + body + text[match.end():]
    return text, len(matches), len(selected)


FIELDS = {
    "pattern": {"target", "pattern", "position", "payload", "match_indent", "times", "expected_matches", "optional", "overwrite", "name"},
    "regex": {"target", "pattern", "position", "payload", "line_prepend", "times", "expected_matches", "optional", "name"},
    "copy": {"target", "position", "sources", "payload", "name"},
    "module": {"source", "before", "name", "load_now"},
}


def compile_plan(game: Path, mods: Path) -> Plan:
    manifests = discover(mods)
    plan = Plan(manifests=[m.label for m in manifests])
    files = sorted(p.relative_to(game).as_posix() for p in (game / "assets/scripts").rglob("*.lua"))
    work = []
    module_names = set()
    for manifest in manifests:
        for index, entry in enumerate(manifest.patches, 1):
            label = f"{manifest.label} patch #{index}"
            if not isinstance(entry, dict) or len(entry) != 1 or next(iter(entry)) not in FIELDS:
                raise PatchError(f"{label}: expected exactly one pattern, regex, copy, or module table")
            kind = next(iter(entry))
            data = entry[kind]
            try:
                only_keys(data, FIELDS[kind], kind)
                data = {k: substitute(v, manifest) if isinstance(v, str) else v for k, v in data.items()}
                if kind == "module":
                    name = string(data, "name")
                    if not re.fullmatch(r"[A-Za-z_][\w.-]*", name, re.ASCII):
                        raise PatchError("module.name must be a Lua module identifier")
                    if name in module_names:
                        raise PatchError(f"duplicate module name: {name}")
                    module_names.add(name)
                targets = []
                for target in strings(data.get("before" if kind == "module" else "target"), "target"):
                    target = target_path(target)
                    found = [f for f in files if wildcard(target).fullmatch(f)]
                    if not found:
                        raise PatchError(f"no target scripts found: {target}")
                    targets.extend(found)
                work.append((kind, manifest, data, sorted(set(targets)), label))
            except PatchError as exc:
                raise PatchError(f"{label}: {exc}") from exc

    # Modules, then copies, then pattern/regex in declaration order, like Lovely.
    work.sort(key=lambda job: {"module": 0, "copy": 1, "pattern": 2, "regex": 2}[job[0]])
    module_prefixes: dict[str, list[str]] = {}
    for kind, manifest, data, targets, label in work:
        try:
            payload = ""
            if kind == "module":
                body = substitute(read_text(inside(manifest.root, string(data, "source"))), manifest)
                name = json.dumps(data["name"])
                payload = f"_G.cpcmodloader.preload({name}, function(...)\nlocal require = _G.cpcmodloader.require\n{body}\nend)\n"
                if boolean(data, "load_now"):
                    payload += f"_G.cpcmodloader.require({name})\n"
            elif kind == "copy":
                if "sources" not in data and "payload" not in data:
                    raise PatchError("copy needs sources or payload")
                if "sources" in data:
                    for source in strings(data["sources"], "sources"):
                        payload = join_code(payload, substitute(read_text(inside(manifest.root, source)), manifest), "\n")
                payload = join_code(payload, string(data, "payload", ""), "\n")
                if string(data, "position") not in {"prepend", "append"}:
                    raise PatchError("copy.position must be prepend or append")
            else:
                payload = string(data, "payload")
            for target in targets:
                if target not in plan.sources:
                    path = inside(game, target)
                    plan.original_hashes[target] = hashlib.sha256(path.read_bytes()).hexdigest()
                    plan.sources[target] = read_text(path)
                text = plan.sources[target]
                matches = applied = 1
                if kind == "module":
                    module_prefixes.setdefault(target, []).append(payload)
                elif kind == "copy":
                    body = with_newlines(payload, newline(text))
                    if data["position"] == "prepend":
                        text = join_code(body, text, newline(text))
                    else:
                        text = join_code(text, body, newline(text))
                elif kind == "pattern":
                    text, matches, applied = pattern_patch(text, data, payload)
                elif kind == "regex":
                    text, matches, applied = regex_patch(text, data, payload)
                plan.sources[target] = text
                plan.events.append({"patch": label, "type": kind, "target": target, "matches": matches, "applied": applied})
        except PatchError as exc:
            raise PatchError(f"{label}: {exc}") from exc
    runtime = resource_files("cpcmodloader").joinpath("runtime.lua").read_text(encoding="utf-8")
    for target, source in plan.sources.items():
        prefix = runtime + "\n" + "".join(module_prefixes.get(target, []))
        plan.sources[target] = join_code(with_newlines(prefix, newline(source)), source, newline(source))
    return plan
