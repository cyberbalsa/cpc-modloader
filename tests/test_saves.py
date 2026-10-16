from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from cpcmodloader.launcher import build, profile_lock
from cpcmodloader.patcher import PatchError, Plan
from cpcmodloader.saves import is_link, link_directory


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpc saves & spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = self.root / "installed game"
        (self.game / "assets/scripts").mkdir(parents=True)
        self.saves = self.game / "saves"
        self.saves.mkdir()
        (self.saves / "progress.json").write_text("original progress")
        self.profile = self.root / "profile"
        self.mods = self.root / "Mods"

    def legacy(self):
        with profile_lock(self.profile, self.game, self.mods):
            old = self.profile / "game/saves"
            old.mkdir(parents=True)
        return old

    def build(self):
        with profile_lock(self.profile, self.game, self.mods):
            return build(self.game, self.profile, Plan(), "test")

    def test_saves_are_shared_in_both_directions_and_survive_profile_removal(self):
        directory = self.build()
        self.assertTrue(is_link(directory / "saves"))
        self.assertTrue((directory / "saves").samefile(self.saves))
        self.assertEqual((directory / "saves/progress.json").read_text(), "original progress")
        (directory / "saves/new.cpcp").write_bytes(b"modded session")
        self.assertEqual((self.saves / "new.cpcp").read_bytes(), b"modded session")
        (self.saves / "progress.json").write_text("cloud update")
        self.assertEqual((directory / "saves/progress.json").read_text(), "cloud update")
        self.build()
        self.assertEqual(list(self.profile.glob("saves-backup-*")), [])
        shutil.rmtree(self.profile)
        self.assertEqual((self.saves / "progress.json").read_text(), "cloud update")
        self.assertEqual((self.saves / "new.cpcp").read_bytes(), b"modded session")

    def test_migration_keeps_conflicts_backs_up_everything_and_imports_missing(self):
        old = self.legacy()
        (old / "progress.json").write_text("old modded progress")
        (old / "new.cpcp").write_bytes(b"old save")
        (old / "blueprints").mkdir()
        (old / "blueprints/parking.cpbp").write_bytes(b"blueprint")
        (old / "steam_autocloud.vdf").write_text("old steam metadata")
        (self.saves / "same.cpcp").write_bytes(b"same")
        (old / "same.cpcp").write_bytes(b"same")
        directory = self.build()
        report = json.loads((directory / "cpcmodloader-report.json").read_text())["saves"]
        backup = Path(report["backup"])
        self.assertEqual((backup / "progress.json").read_text(), "old modded progress")
        self.assertEqual((backup / "steam_autocloud.vdf").read_text(), "old steam metadata")
        self.assertEqual((self.saves / "progress.json").read_text(), "original progress")
        self.assertEqual((self.saves / "new.cpcp").read_bytes(), b"old save")
        self.assertEqual((self.saves / "blueprints/parking.cpbp").read_bytes(), b"blueprint")
        self.assertFalse((self.saves / "steam_autocloud.vdf").exists())
        self.assertEqual(report["conflicts"], ["progress.json"])
        self.assertEqual(report["imported"], ["blueprints/parking.cpbp", "new.cpcp"])
        self.build()
        self.assertEqual(len(list(self.profile.glob("saves-backup-*"))), 1)
        self.assertEqual((backup / "new.cpcp").read_bytes(), b"old save")

    def test_failed_backup_leaves_old_and_original_saves(self):
        old = self.legacy()
        (old / "new.cpcp").write_bytes(b"keep")
        copytree = shutil.copytree

        def fail_backup(source, destination, *args, **kwargs):
            if Path(source) == old:
                raise OSError("disk full")
            return copytree(source, destination, *args, **kwargs)

        with patch("cpcmodloader.saves.shutil.copytree", side_effect=fail_backup):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual((old / "new.cpcp").read_bytes(), b"keep")
        self.assertEqual((self.saves / "progress.json").read_text(), "original progress")
        self.assertFalse((self.saves / "new.cpcp").exists())

    def test_failed_publish_cleans_link_without_deleting_shared_saves(self):
        directory = self.build()
        rename = Path.rename

        def fail_stage(path, destination):
            if path.name.startswith(".staging-"):
                raise OSError("publish failed")
            return rename(path, destination)

        with patch.object(Path, "rename", fail_stage):
            with self.assertRaisesRegex(OSError, "publish failed"):
                self.build()
        self.assertEqual((directory / "saves/progress.json").read_text(), "original progress")
        self.assertEqual(list(self.profile.glob(".staging-*")), [])

    def test_link_failure_never_falls_back_to_empty_saves(self):
        old = self.legacy()
        (old / "old.cpcp").write_bytes(b"keep")
        with patch("cpcmodloader.saves.link_directory", side_effect=PatchError("link unavailable")):
            with self.assertRaisesRegex(PatchError, "link unavailable"):
                self.build()
        self.assertFalse(is_link(old))
        self.assertEqual((old / "old.cpcp").read_bytes(), b"keep")
        self.assertEqual(list(self.profile.glob("saves-backup-*")), [])

    def test_legacy_links_are_rejected_without_following_them(self):
        old = self.legacy()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.cpcp").write_bytes(b"keep")
        link_directory(outside, old / "linked")
        with self.assertRaisesRegex(PatchError, "link in old profile"):
            self.build()
        self.assertEqual((outside / "keep.cpcp").read_bytes(), b"keep")

    def test_migration_does_not_follow_links_in_destination(self):
        old = self.legacy()
        (old / "blueprints").mkdir()
        (old / "blueprints/new.cpbp").write_bytes(b"blueprint")
        outside = self.root / "outside"
        outside.mkdir()
        link_directory(outside, self.saves / "blueprints")
        directory = self.build()
        report = json.loads((directory / "cpcmodloader-report.json").read_text())["saves"]
        self.assertEqual(report["conflicts"], ["blueprints/new.cpbp"])
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((Path(report["backup"]) / "blueprints/new.cpbp").read_bytes(), b"blueprint")

    def test_file_directory_conflicts_are_backed_up(self):
        old = self.legacy()
        (old / "blueprints").mkdir()
        (old / "blueprints/parking.cpbp").write_bytes(b"blueprint")
        (self.saves / "blueprints").write_text("existing file")
        (old / "city.cpcp").write_bytes(b"city")
        (self.saves / "city.cpcp").mkdir()
        directory = self.build()
        report = json.loads((directory / "cpcmodloader-report.json").read_text())["saves"]
        self.assertEqual(report["conflicts"], ["blueprints/parking.cpbp", "city.cpcp"])
        self.assertEqual((self.saves / "blueprints").read_text(), "existing file")

    def test_empty_legacy_saves_use_existing_progress_without_backup(self):
        (self.legacy() / "scenarios").mkdir()
        directory = self.build()
        self.assertTrue((directory / "saves").samefile(self.saves))
        self.assertEqual(list(self.profile.glob("saves-backup-*")), [])

    def test_new_install_creates_shared_save_directory(self):
        shutil.rmtree(self.saves)
        directory = self.build()
        self.assertTrue((directory / "saves").samefile(self.saves))


if __name__ == "__main__":
    unittest.main()
