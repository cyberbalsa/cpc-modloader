from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .launcher import build, executable, find_game, profile_lock, run_game, syntax_check, validate_game
from .patcher import PatchError, compile_plan, discover


def parser():
    result = argparse.ArgumentParser(prog="cpc-modloader", description="Lovely-style Lua patcher for Car Park Capital. Original game files remain untouched.")
    result.add_argument("--version", action="version", version=f"cpc-modloader {__version__}")
    commands = result.add_subparsers(dest="command", required=True)
    for name, description in (("inspect", "Inspect a game installation"), ("mods", "List enabled patch manifests"),
                              ("check", "Validate patches without building"), ("build", "Prepare an isolated modded game"),
                              ("run", "Build and launch the modded game")):
        command = commands.add_parser(name, help=description)
        command.add_argument("--game-dir", type=Path, default=os.environ.get("CPC_GAME_DIR"), help="Steam game directory (auto-detected when omitted)")
        command.add_argument("--mods-dir", type=Path, default=Path("Mods"), help="mod folders (default: ./Mods)")
        if name in {"build", "run"}:
            command.add_argument("--profile-dir", type=Path, default=Path("run/default"), help="private game + saves (default: ./run/default)")
        if name in {"check", "build", "run"}:
            command.add_argument("--luac", help="optional path to Lua 5.4's luac compiler")
        if name == "run":
            command.add_argument("--timeout", type=float, help="stop the game after N seconds (smoke tests; exit 124)")
            command.add_argument("game_args", nargs=argparse.REMAINDER, help="game arguments after --")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        mods = args.mods_dir.resolve()
        if args.command == "mods":
            manifests = discover(mods)
            for manifest in manifests:
                print(f"{manifest.priority:5d}  {manifest.label} ({len(manifest.patches)} patches)")
            if not manifests:
                print(f"No enabled manifests in {mods}")
            return 0
        game = args.game_dir or find_game()
        if game is None:
            raise PatchError("game not found; pass --game-dir '/path/to/Car Park Capital'")
        game = validate_game(game)
        if args.command == "inspect":
            print(json.dumps({"game": str(game), "lua_scripts": len(list((game / "assets/scripts").rglob("*.lua"))),
                              "executable": str(executable(game)), "loader": __version__, "lua": "5.4"}, indent=2))
            return 0
        plan = compile_plan(game, mods)
        syntax = syntax_check(plan, args.luac)
        print(f"cpc-modloader {__version__}: {len(plan.mods)} mods, {len(plan.manifests)} manifests, {len(plan.events)} patch applications, {len(plan.sources)} patched scripts", flush=True)
        print(f"Syntax: {syntax}", flush=True)
        for event in plan.events:
            print(f"  {event['patch']} -> {event['target']} ({event['applied']}/{event['matches']} matches)", flush=True)
        if args.command == "check":
            return 0
        profile = args.profile_dir.resolve()
        if args.command == "run" and args.timeout is not None and args.timeout <= 0:
            raise PatchError("--timeout must be positive")
        executable(game)
        with profile_lock(profile, game, mods):
            directory = build(game, profile, plan, syntax)
            print(f"Built: {directory}\nReport: {directory / 'cpcmodloader-report.json'}", flush=True)
            if args.command == "build":
                return 0
            arguments = args.game_args
            if arguments[:1] == ["--"]:
                arguments = arguments[1:]
            log_path = profile / "game.log"
            print(f"Launching; game output: {log_path}", flush=True)
            code = run_game(directory, arguments, log_path, args.timeout)
            print(f"Game exited: {code}", flush=True)
            return code if code >= 0 else 128 - code
    except (PatchError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"cpcmodloader: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("cpcmodloader: stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
