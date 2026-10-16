from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cpcmodloader.cli import main
from cpcmodloader.launcher import (DATA_DIRECTORY, OWNER, build, default_profile, executable,
                                  external_environment, launcher_directory, profile_lock, run_game, steam_command)
from cpcmodloader.patcher import PatchError, Plan


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpc launcher ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()  # Expand Windows' RUNNER~1 temp alias.
        self.game = self.root / "original game"
        (self.game / "assets/scripts").mkdir(parents=True)
        (self.game / "assets/scripts/main.lua").write_text("return 1\n")
        (self.game / "assets/texture.dat").write_bytes(b"original asset")
        (self.game / "settings.json").write_text('{"original": true}')
        (self.game / "carparkcapital").write_bytes(b"placeholder")
        (self.game / "carparkcapital.exe").write_bytes(b"placeholder")
        (self.game / "saves").mkdir()
        (self.game / "saves/vanilla.sav").write_bytes(b"keep vanilla")
        self.mods = self.root / "Mods"
        self.profile = self.root / "profile"

    def test_build_isolation_and_persistent_profile_state(self):
        import hashlib
        target = "assets/scripts/main.lua"
        plan = Plan(sources={target: "return 42\n"}, original_hashes={target: hashlib.sha256((self.game / target).read_bytes()).hexdigest()})
        with profile_lock(self.profile, self.game, self.mods):
            directory = build(self.game, self.profile, plan, "test")
            self.assertEqual((directory / target).read_text(), "return 42\n")
            self.assertEqual((self.game / target).read_text(), "return 1\n")
            self.assertFalse((directory / "saves/vanilla.sav").exists())
            (directory / "saves/modded.sav").write_bytes(b"modded save")
            (directory / "settings.json").write_text('{"modded": true}')
            (directory / "assets/texture.dat").write_bytes(b"changed asset")
            build(self.game, self.profile, Plan(), "test")
            self.assertEqual((directory / "saves/modded.sav").read_bytes(), b"modded save")
            self.assertEqual((directory / "settings.json").read_text(), '{"modded": true}')
            self.assertEqual((directory / target).read_text(), "return 1\n")
            self.assertEqual((directory / "assets/texture.dat").read_bytes(), b"original asset")
        self.assertEqual((self.game / "settings.json").read_text(), '{"original": true}')
        self.assertEqual((self.game / "saves/vanilla.sav").read_bytes(), b"keep vanilla")

    def test_refuse_nonempty_and_overlapping_profiles(self):
        self.profile.mkdir()
        (self.profile / "important.txt").touch()
        with self.assertRaisesRegex(PatchError, "unowned"):
            with profile_lock(self.profile, self.game, self.mods):
                pass
        for destination in (self.game, self.game / "profile", self.root, self.mods):
            with self.subTest(destination=destination), self.assertRaisesRegex(PatchError, "must not contain"):
                with profile_lock(destination, self.game, self.mods):
                    pass

    def test_in_game_profile_does_not_copy_itself_or_loader(self):
        profile = self.game / DATA_DIRECTORY / "default"
        mods = self.game / "Mods"
        mods.mkdir()
        (mods / "keep.txt").write_text("mod")
        (self.game / "cpc-modloader.exe").write_bytes(b"loader")
        (self.game / "cpc-modloader").write_bytes(b"loader")
        with profile_lock(profile, self.game, mods):
            directory = build(self.game, profile, Plan(), "test")
            (directory / "saves/save.dat").write_bytes(b"save")
            build(self.game, profile, Plan(), "test")
            self.assertEqual((directory / "saves/save.dat").read_bytes(), b"save")
            for name in (DATA_DIRECTORY, "Mods", "cpc-modloader", "cpc-modloader.exe"):
                self.assertFalse((directory / name).exists())
        self.assertEqual((mods / "keep.txt").read_text(), "mod")
        with self.assertRaises(PatchError):
            with profile_lock(self.game / DATA_DIRECTORY, self.game, mods):
                pass

    def test_frozen_paths_are_beside_loader(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(self.game / "cpc-modloader.exe")):
            base = launcher_directory()
        self.assertEqual(base, self.game)
        self.assertEqual(default_profile(base, self.game), self.game / DATA_DIRECTORY / "default")
        self.assertEqual(default_profile(self.root / "standalone", self.game), self.root / "standalone/run/default")

    def test_steam_command_preserves_wrappers_and_arguments(self):
        wrapper = self.root / "runtime wrapper"
        wrapper.write_bytes(b"wrapper")
        game_exe = executable(self.game)
        original = ["--", str(wrapper), "--verb=waitforexitandrun", "--", str(game_exe), "--name", "spaces and ; punctuation"]
        game, index, command = steam_command(original)
        self.assertEqual(game, self.game)
        self.assertEqual(index, 3)
        self.assertEqual(command, original[1:])
        self.assertEqual(original[0], "--")
        for invalid in ([], ["%command%"], [str(game_exe), str(game_exe)]):
            with self.subTest(invalid=invalid), self.assertRaises(PatchError):
                steam_command(invalid)

    def test_steam_cli_builds_in_game_and_replaces_only_executable(self):
        game_exe = executable(self.game)
        wrapper = str(self.root / "wrapper")
        with patch("cpcmodloader.cli.launcher_directory", return_value=self.game), \
             patch("cpcmodloader.cli.run_game", return_value=7) as launch:
            code = main(["steam", "--allow-unsupported-game", "--no-update-check", "--", wrapper, "--", str(game_exe), "--name", "two words"])
        self.assertEqual(code, 7)
        profile = self.game / DATA_DIRECTORY / "default"
        self.assertEqual(launch.call_args.args[0], profile / "game")
        self.assertEqual(launch.call_args.kwargs["command"],
                         [wrapper, "--", str(profile / "game" / game_exe.name), "--name", "two words"])
        self.assertEqual((self.game / "assets/scripts/main.lua").read_text(), "return 1\n")

    def test_steam_relative_wrapper_keeps_original_location(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="cpc wrapper ") as temp:
            wrapper = Path(temp) / "wrapper"
            wrapper.write_bytes(b"wrapper")
            relative = str(wrapper.relative_to(Path.cwd()))
            _, _, command = steam_command([relative, "--", str(executable(self.game))])
            self.assertEqual(command[0], str(wrapper.resolve()))

    def test_lock_prevents_second_process(self):
        script = "from pathlib import Path; from cpcmodloader.launcher import profile_lock; import sys\nwith profile_lock(*map(Path, sys.argv[1:])): pass"
        with profile_lock(self.profile, self.game, self.mods):
            result = subprocess.run([sys.executable, "-c", script, str(self.profile), str(self.game), str(self.mods)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already building or running", result.stderr)
        with profile_lock(self.profile, self.game, self.mods):
            pass  # Released even after the other process failed.

    def test_failed_build_preserves_current(self):
        with profile_lock(self.profile, self.game, self.mods):
            directory = build(self.game, self.profile, Plan(), "test")
            (directory / "saves/modded.sav").write_text("keep")
            with patch("cpcmodloader.launcher.copy_tree", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    build(self.game, self.profile, Plan(), "test")
            self.assertEqual((directory / "saves/modded.sav").read_text(), "keep")
            self.assertEqual(list(self.profile.glob(".staging-*")), [])

    def test_generated_assets_are_isolated_and_cannot_overwrite(self):
        target = "assets/models/loader.glb"
        with profile_lock(self.profile, self.game, self.mods):
            directory = build(self.game, self.profile, Plan(assets={target: b"loader model"}), "test")
            self.assertEqual((directory / target).read_bytes(), b"loader model")
            self.assertFalse((self.game / target).exists())
            with self.assertRaisesRegex(PatchError, "overwrite a game file"):
                build(self.game, self.profile, Plan(assets={"assets/texture.dat": b"replacement"}), "test")
            self.assertEqual((directory / target).read_bytes(), b"loader model")

    def test_game_update_during_build_is_rejected(self):
        with profile_lock(self.profile, self.game, self.mods):
            directory = build(self.game, self.profile, Plan(), "test")
            plan = Plan(sources={"assets/scripts/main.lua": "return 42"}, original_hashes={"assets/scripts/main.lua": "outdated hash"})
            with self.assertRaisesRegex(PatchError, "source changed"):
                build(self.game, self.profile, plan, "test")
            self.assertEqual((directory / "assets/scripts/main.lua").read_text(), "return 1\n")

    def test_recover_interrupted_publish(self):
        with profile_lock(self.profile, self.game, self.mods):
            directory = build(self.game, self.profile, Plan(), "test")
            directory.rename(self.profile / ".previous")
        with profile_lock(self.profile, self.game, self.mods):
            self.assertTrue((self.profile / "game/assets/scripts/main.lua").is_file())

    def test_launch_arguments_environment_and_exit_code(self):
        log = self.root / "game.log"
        code = "import os,sys,json; print(json.dumps([os.getcwd(),os.environ['SteamAppId'],sys.argv[1:]])); sys.exit(7)"
        with patch("cpcmodloader.launcher.executable", return_value=Path(sys.executable)):
            result = run_game(self.game, ["-c", code, "an argument with spaces", 'quote"'], log)
        self.assertEqual(result, 7)
        output = json.loads(log.read_text())
        self.assertEqual(Path(output[0]), self.game)
        self.assertEqual(output[1:], ["3031880", ["an argument with spaces", 'quote"']])

    def test_launch_timeout_reaps_child(self):
        with patch("cpcmodloader.launcher.executable", return_value=Path(sys.executable)):
            result = run_game(self.game, ["-c", "import time; time.sleep(10)"], self.root / "timeout.log", timeout=0.1)
        self.assertEqual(result, 124)

    @unittest.skipIf(sys.platform == "win32", "POSIX loader environment")
    def test_frozen_subprocess_restores_original_library_paths(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"LD_LIBRARY_PATH": "/private/bundle", "LD_LIBRARY_PATH_ORIG": "/steam/libs"}, clear=True):
            env = external_environment()
            self.assertEqual(env["LD_LIBRARY_PATH"], "/steam/libs")
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/private/bundle")
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"LD_LIBRARY_PATH": "/private/bundle"}, clear=True):
            self.assertNotIn("LD_LIBRARY_PATH", external_environment())

    def test_check_does_not_create_profile(self):
        code = main(["check", "--allow-unsupported-game", "--game-dir", str(self.game), "--mods-dir", str(self.mods)])
        self.assertEqual(code, 0)
        self.assertFalse(self.profile.exists())


if __name__ == "__main__":
    unittest.main()
