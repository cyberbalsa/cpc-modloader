from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cpcmodloader import __version__, overlay
from cpcmodloader.cli import main
from cpcmodloader.compatibility import GameVersion, detect_game, satisfies, version_tuple
from cpcmodloader.launcher import build, executable, profile_lock
from cpcmodloader.patcher import PatchError, compile_plan
from cpcmodloader.updates import check_for_updates, fetch_latest, https_context, MAX_RESPONSE


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpc versions ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "steamapps/common/Car Park Capital"
        self.menu = self.game / overlay.MENU_SCRIPT
        self.menu.parent.mkdir(parents=True)
        self.menu.write_text("function create(menu) end\n")
        for name in ("carparkcapital", "carparkcapital.exe"):
            (self.game / name).write_bytes(b"binary\0Early Access 1.0.1\0")
        self.acf = self.root / "steamapps/appmanifest_3031880.acf"
        self.acf.write_text('"AppState" { "appid" "3031880" "buildid" "25985572" }')
        self.mods = self.root / "Mods"
        self.mods.mkdir()
        self.info = detect_game(self.game, executable(self.game))
        known = {(self.info.version, self.info.executable_sha256, self.info.scripts_sha256)}
        self.known = patch("cpcmodloader.compatibility.TESTED_FILES", known)
        self.known.start()
        self.addCleanup(self.known.stop)

    def manifest(self, compatibility):
        mod = self.mods / "test"
        mod.mkdir(exist_ok=True)
        (mod / "cpcmodloader.toml").write_text('[manifest]\nversion="1.0.0"\n[compatibility]\n' + compatibility)

    def test_detects_version_build_and_unlabelled_changes(self):
        self.assertEqual((self.info.version, self.info.steam_build_id), ("1.0.1", "25985572"))
        self.assertTrue(self.info.supported)
        self.assertFalse(replace(self.info, steam_build_id="25985573").supported)
        self.menu.write_text("function create(menu) changed() end\n")
        self.assertFalse(detect_game(self.game, executable(self.game)).supported)
        self.assertFalse(replace(self.info, executable_sha256="changed").supported)

    def test_steamcmd_and_missing_manifest(self):
        self.acf.unlink()
        self.assertTrue(detect_game(self.game, executable(self.game)).supported)
        acf = self.game / "steamapps/appmanifest_3031880.acf"
        acf.parent.mkdir()
        acf.write_text('"appid" "3031880" "buildid" "new"')
        self.assertIsNone(detect_game(self.game, executable(self.game)).steam_build_id)
        acf.write_text('"appid" "3031880" "buildid" "25985573"')
        self.assertFalse(detect_game(self.game, executable(self.game)).supported)

    def test_missing_or_ambiguous_executable_version(self):
        for data in (b"no version", b"Early Access 1.0.1\0Early Access 1.0.2\0"):
            executable(self.game).write_bytes(data)
            self.assertIsNone(detect_game(self.game, executable(self.game)).version)

    def test_ranges_are_numeric_and_reject_invalid_specs(self):
        self.assertTrue(satisfies("1.0.10", ">=1.0.2, <1.1.0"))
        self.assertFalse(satisfies("1.1.0", ">=1.0.2, <1.1.0"))
        self.assertFalse(satisfies(None, "1.0.1"))
        for spec in ("", "^1.0.0", "1.0", ">=1.0.0,", "==01.0.0"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                satisfies("1.0.1", spec)
        self.assertLess(version_tuple("v0.9.9"), version_tuple("0.10.0"))

    def test_mod_constraints_checked_before_any_patching(self):
        self.manifest('game=">=1.0.1, <1.1.0"\nloader=">=0.1.2"\nsteam_builds=["25985572"]')
        self.assertEqual(compile_plan(self.game, self.mods, game_info=self.info).mods, ["test"])
        for requirements, error in [('game="1.0.2"', "requires game"),
                                    ('loader=">=9.0.0"', "requires loader"),
                                    ('steam_builds=["123"]', "requires Steam build"),
                                    ('game="*"', "invalid version"),
                                    ('steam_builds=[]', "nonempty array")]:
            with self.subTest(requirements=requirements), self.assertRaisesRegex(PatchError, error):
                self.manifest(requirements)
                compile_plan(self.game, self.mods, game_info=self.info)
        self.manifest('game="1.0.1"')
        with self.assertRaisesRegex(PatchError, "detected unknown"):
            compile_plan(self.game, self.mods)

    def test_unknown_game_stops_before_profile_and_override_keeps_mod_gate(self):
        self.acf.write_text('"appid" "3031880" "buildid" "999"')
        arguments = ["build", "--game-dir", str(self.game), "--mods-dir", str(self.mods),
                     "--profile-dir", str(self.root / "profile")]
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
            self.assertEqual(main(arguments), 1)
        self.assertIn("--allow-unsupported-game", err.getvalue())
        self.assertFalse((self.root / "profile").exists())
        self.manifest('game="9.0.0"')
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
            self.assertEqual(main(arguments + ["--allow-unsupported-game"]), 1)
        self.assertIn("requires game", err.getvalue())
        self.assertFalse((self.root / "profile").exists())

    def test_report_runtime_and_multiline_notices(self):
        notices = ["unverified game build - mods may break", "loader out of date - v0.2.0 available on github"]
        plan = compile_plan(self.game, self.mods, game_info=self.info, notices=notices)
        self.assertEqual(plan.report()["game"]["steam_build_id"], "25985572")
        self.assertEqual(plan.report()["notices"], notices)
        self.assertIn('_G.cpcmodloader.game_version = "1.0.1"', plan.sources[overlay.MENU_SCRIPT])
        self.assertIn("const int lines = 3;", plan.assets["assets/shaders/cpcmodloader_overlay.frag"].decode())

    def test_update_during_copy_leaves_previous_profile(self):
        profile = self.root / "profile"
        plan = compile_plan(self.game, self.mods, game_info=self.info)
        with profile_lock(profile, self.game, self.mods):
            current = build(self.game, profile, plan, "test")
            (current / "saves/save.dat").write_text("keep")
            executable(self.game).write_bytes(b"updated executable")
            with self.assertRaisesRegex(PatchError, "game changed during build"):
                build(self.game, profile, plan, "test")
            self.assertEqual((current / "saves/save.dat").read_text(), "keep")
            self.assertEqual((current / executable(self.game).name).read_bytes(), b"binary\0Early Access 1.0.1\0")

    def test_run_errors_are_visible_without_launching(self):
        executable(self.game).write_bytes(b"unknown game")
        with patch("cpcmodloader.cli.show_launch_error") as dialog, patch("cpcmodloader.cli.run_game") as launch, \
             patch("cpcmodloader.cli.launcher_directory", return_value=self.game), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["run", "--no-update-check", "--game-dir", str(self.game)]), 1)
        launch.assert_not_called()
        self.assertIn("not been verified", dialog.call_args.args[0])


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "update.json"

    def test_new_release_notice_and_cache(self):
        with patch("cpcmodloader.updates.fetch_latest", return_value="0.10.0") as fetch:
            result = check_for_updates(self.cache, current="0.9.0")
            self.assertEqual(result.state, "update_available")
            self.assertIn("out of date", result.notice)
            self.assertEqual(check_for_updates(self.cache, current="0.9.0"), result)
            fetch.assert_called_once()

    def test_no_downgrade_and_disable_skips_network_and_cache(self):
        with patch("cpcmodloader.updates.fetch_latest", return_value="0.1.1") as fetch:
            self.assertEqual(check_for_updates(self.cache, enabled=False).state, "disabled")
            fetch.assert_not_called()
            self.assertFalse(self.cache.exists())
            self.assertEqual(check_for_updates(self.cache, current=__version__).state, "up_to_date")

    def test_offline_failure_retries_later_and_retains_known_update(self):
        self.cache.write_text(json.dumps({"checked_at": 1, "ok": True, "latest": "9.0.0"}))
        with patch("cpcmodloader.updates.fetch_latest", side_effect=OSError("offline")) as fetch:
            result = check_for_updates(self.cache)
            self.assertEqual(result.state, "update_available")
            self.assertTrue(result.stale)
            self.assertEqual(check_for_updates(self.cache), result)
            fetch.assert_called_once()

    def test_corrupt_cache_and_http_failure_do_not_block(self):
        for cache in ("{broken", "[]", '{"latest":"evil"}', '{"checked_at": "bad"}'):
            self.cache.write_text(cache)
            with patch("cpcmodloader.updates.fetch_latest", side_effect=ValueError("bad API response")):
                self.assertEqual(check_for_updates(self.cache).state, "unavailable")

    def test_network_wait_has_deadline(self):
        released = threading.Event()
        with patch("cpcmodloader.updates.TIMEOUT", 0.05), \
             patch("cpcmodloader.updates.fetch_latest", side_effect=lambda: released.wait(2)):
            start = time.monotonic()
            try:
                self.assertEqual(check_for_updates(self.cache).state, "unavailable")
                self.assertLess(time.monotonic() - start, 1)
            finally:
                released.set()

    def test_unwritable_cache_is_optional(self):
        self.cache.mkdir()
        with patch("cpcmodloader.updates.fetch_latest", return_value="9.0.0"):
            self.assertEqual(check_for_updates(self.cache).state, "update_available")

    def test_public_stable_release_validation(self):
        for data in ({"tag_name": "v0.2.0", "draft": False, "prerelease": False},
                     {"tag_name": "v0.2.0-beta", "draft": False, "prerelease": True},
                     {"tag_name": "v0.2.0", "draft": True, "prerelease": False},
                     {"tag_name": "garbage", "draft": False, "prerelease": False}, []):
            with patch("urllib.request.urlopen") as request:
                request.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode()
                if isinstance(data, dict) and data.get("tag_name") == "v0.2.0" and not data["draft"]:
                    self.assertEqual(fetch_latest(), "0.2.0")
                else:
                    with self.assertRaises(ValueError):
                        fetch_latest()
        with patch("urllib.request.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b" " * (MAX_RESPONSE + 1)
            with self.assertRaisesRegex(ValueError, "too large"):
                fetch_latest()

    def test_frozen_tls_uses_host_bundle_when_build_paths_are_missing(self):
        with patch("ssl.create_default_context") as create, patch("pathlib.Path.is_file", return_value=True), \
             patch.dict("os.environ", {}, clear=True):
            context = create.return_value
            context.cert_store_stats.return_value = {"x509_ca": 0}
            self.assertIs(https_context(), context)
            context.load_verify_locations.assert_called_once_with(cafile="/etc/ssl/certs/ca-certificates.crt")
            context.load_verify_locations.reset_mock()
            context.cert_store_stats.return_value = {"x509_ca": 100}
            https_context()
            context.load_verify_locations.assert_not_called()

    def test_explicit_tls_configuration_is_respected(self):
        with patch("ssl.create_default_context") as create, patch.dict("os.environ", {"SSL_CERT_FILE": "/custom/roots.pem"}):
            context = create.return_value
            context.cert_store_stats.return_value = {"x509_ca": 0}
            https_context()
            context.load_verify_locations.assert_not_called()


if __name__ == "__main__":
    unittest.main()
