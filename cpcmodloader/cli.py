from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .compatibility import detect_game
from .launcher import (build, default_profile, executable, find_game, launcher_directory,
                       profile_lock, run_game, steam_command, syntax_check, validate_game, show_launch_error)
from .patcher import PatchError, compile_plan, discover
from .updates import check_for_updates, RELEASES_URL, UpdateStatus


def parser():
    result = argparse.ArgumentParser(prog="cpc-modloader", description="Lovely-style Lua patcher for Car Park Capital. Uses the game's normal saves.")
    result.add_argument("--version", action="version", version=f"cpc-modloader {__version__}")
    commands = result.add_subparsers(dest="command", required=True)
    for name, description in (("inspect", "Inspect a game installation"), ("mods", "List enabled patch manifests"),
                              ("check", "Validate patches without building"), ("build", "Prepare an isolated modded game"),
                              ("run", "Build and launch the modded game"),
                              ("steam", "Build and launch using Steam's original command")):
        command = commands.add_parser(name, help=description)
        command.add_argument("--game-dir", type=Path, default=os.environ.get("CPC_GAME_DIR"), help="Steam game directory (auto-detected when omitted)")
        command.add_argument("--mods-dir", type=Path, help="mod folders (default: Mods beside the loader)")
        if name in {"build", "run", "steam"}:
            command.add_argument("--profile-dir", type=Path, help="patched game + settings (saves stay in the installed game folder)")
        if name in {"check", "build", "run", "steam"}:
            command.add_argument("--luac", help="optional path to Lua 5.4's luac compiler")
            command.add_argument("--allow-unsupported-game", action="store_true", help="test an unverified game build (mod requirements still apply)")
        if name in {"run", "steam"}:
            command.add_argument("--no-update-check", action="store_true", help="disable the GitHub release check")
            command.add_argument("--timeout", type=float, help="stop the game after N seconds (smoke tests; exit 124)")
            command.add_argument("game_args", nargs=argparse.REMAINDER, help="game arguments, or Steam's original command, after --")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        base = launcher_directory()
        mods = (args.mods_dir or base / "Mods").resolve()
        if args.command == "mods":
            manifests = discover(mods)
            for manifest in manifests:
                print(f"{manifest.priority:5d}  {manifest.label} ({len(manifest.patches)} patches)")
            if not manifests:
                print(f"No enabled manifests in {mods}")
            return 0
        original_command = None
        if args.command == "steam":
            game, game_index, original_command = steam_command(args.game_args)
            if args.game_dir and args.game_dir.resolve() != game:
                raise PatchError("--game-dir must match the game in Steam's command")
        else:
            game = args.game_dir or (base if (base / "assets/scripts").is_dir() else find_game())
        if game is None:
            raise PatchError("game not found; pass --game-dir '/path/to/Car Park Capital'")
        game = validate_game(game)
        game_info = detect_game(game, executable(game))
        if args.command == "inspect":
            print(json.dumps({"game": str(game), "lua_scripts": len(list((game / "assets/scripts").rglob("*.lua"))),
                              "executable": str(executable(game)), "loader": __version__, "lua": "5.4",
                              "game_version": game_info.report()}, indent=2))
            return 0
        print(game_info.description, flush=True)
        update = UpdateStatus("not_checked")
        if args.command in {"run", "steam"}:
            update = check_for_updates(base / "cpc-modloader-data/update-check.json", enabled=not args.no_update_check)
            if update.notice:
                print(f"{update.notice}\n{RELEASES_URL}", flush=True)
            elif update.state == "unavailable":
                print("Update check unavailable; continuing offline.", flush=True)
        if not game_info.supported and not args.allow_unsupported_game:
            raise PatchError(f"{game_info.description} has not been verified with this loader, or its files have changed.\n"
                             f"Get the latest loader: {RELEASES_URL}\n"
                             "To test this game build, add --allow-unsupported-game before -- in Launch Options.\n"
                             "Clear Launch Options to play without mods.")
        notices = []
        if not game_info.supported:
            notices.append("unverified game build - mods may break")
        if update.notice:
            notices.append(update.notice)
        for notice in notices:
            print(f"Notice: {notice}", flush=True)
        plan = compile_plan(game, mods, game_info=game_info, notices=notices, update=update.report())
        syntax = syntax_check(plan, args.luac)
        print(f"cpc-modloader {__version__}: {len(plan.mods)} mods, {len(plan.manifests)} manifests, {len(plan.events)} patch applications, {len(plan.sources)} patched scripts", flush=True)
        print(f"Syntax: {syntax}", flush=True)
        for event in plan.events:
            print(f"  {event['patch']} -> {event['target']} ({event['applied']}/{event['matches']} matches)", flush=True)
        if args.command == "check":
            return 0
        profile = (args.profile_dir or default_profile(base, game)).resolve()
        if args.command in {"run", "steam"} and args.timeout is not None and args.timeout <= 0:
            raise PatchError("--timeout must be positive")
        executable(game)
        with profile_lock(profile, game, mods):
            previous_report = profile / "game/cpcmodloader-report.json"
            try:
                previous_game = json.loads(previous_report.read_text(encoding="utf-8")).get("game")
            except (OSError, ValueError, AttributeError):
                previous_game = None
            if previous_game and previous_game != game_info.report():
                print("Game update detected since the previous build; rebuilding all patches.", flush=True)
            directory = build(game, profile, plan, syntax)
            print(f"Built: {directory}\nReport: {directory / 'cpcmodloader-report.json'}", flush=True)
            if args.command == "build":
                return 0
            arguments = args.game_args
            if arguments[:1] == ["--"]:
                arguments = arguments[1:]
            log_path = profile / "game.log"
            print(f"Launching; game output: {log_path}", flush=True)
            if original_command is not None:
                original_command[game_index] = str(executable(directory))
            code = run_game(directory, arguments, log_path, args.timeout, command=original_command)
            print(f"Game exited: {code}", flush=True)
            return code if code >= 0 else 128 - code
    except (PatchError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"cpcmodloader: {exc}", file=sys.stderr)
        if args.command in {"run", "steam"}:
            show_launch_error(str(exc), launcher_directory() / "cpc-modloader-data/launch-error.txt")
        return 1
    except KeyboardInterrupt:
        print("cpcmodloader: stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
