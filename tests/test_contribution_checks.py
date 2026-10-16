from pathlib import Path
import unittest

from scripts.check_pr import ACKNOWLEDGEMENTS, validate
from scripts.check_repository import file_errors


class PullRequestTests(unittest.TestCase):
    def description(self):
        return ("## Problem\nThe Steam wrapper drops arguments containing spaces.\n"
                "## Changes\nPreserve the original command list when replacing the executable.\n"
                "## Validation\nRan launcher tests on Linux: 18 passed. Windows awaits CI.\n" +
                "\n".join(f"- [x] {text}" for text in ACKNOWLEDGEMENTS))

    def test_complete_description_and_unrun_platform_are_allowed(self):
        self.assertEqual(validate({"title": "Preserve Steam game arguments", "body": self.description()}), [])
        self.assertEqual(validate({"title": "Preserve Steam game arguments", "body": self.description().replace("\n", "\r\n")}), [])

    def test_empty_template_and_comments_do_not_count_as_evidence(self):
        template = Path(".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(len(validate({"title": "A specific title", "body": template})), 5)
        self.assertEqual(len(validate({"title": "update", "body": None})), 6)

    def test_placeholders_and_unchecked_acknowledgements_fail(self):
        body = self.description().replace("The Steam wrapper drops arguments containing spaces.", "TBD")
        body = body.replace("- [x]", "- [ ]")
        self.assertEqual(len(validate({"title": "Fix arguments", "body": body})), 3)

    def test_description_is_data_even_if_it_contains_shell_code(self):
        body = self.description().replace("The Steam wrapper", "`$(touch /tmp/do-not-create)` in the Steam wrapper")
        self.assertEqual(validate({"title": "Handle shell-like arguments", "body": body}), [])

    def test_only_the_dependabot_identity_gets_generated_body_exception(self):
        self.assertEqual(validate({"user": {"login": "dependabot[bot]", "type": "Bot"}}), [])
        self.assertTrue(validate({"user": {"login": "dependabot[bot]", "type": "User"}}))
        self.assertTrue(validate({"user": {"login": "some-bot", "type": "Bot"}}))


class RepositoryChecksTests(unittest.TestCase):
    def test_source_and_small_synthetic_fixtures_are_allowed(self):
        for name in ("cpcmodloader/runtime.lua", "tests/fixtures/patch.toml", ".github/workflows/test.yml", "docs/reference.md"):
            self.assertEqual(file_errors(name, "100644", 1024), [])

    def test_private_game_and_generated_files_are_rejected(self):
        for name in (".cache/game/file.lua", "assets/scripts/main.lua", "Mods/private/mod.toml",
                     "SAVES/private.sav", "run/default/game.log", "release/cpc-modloader.exe", ".env",
                     "secrets/signing.key", "dist/release.zip", "carparkcapital"):
            with self.subTest(name=name):
                self.assertTrue(file_errors(name, "100644", 100))

    def test_large_files_symlinks_and_submodules_are_rejected(self):
        self.assertTrue(file_errors("fixture.dat", "100644", 1024 * 1024 + 1))
        self.assertTrue(file_errors("link", "120000", 0))
        self.assertTrue(file_errors("vendor", "160000", 0))


if __name__ == "__main__":
    unittest.main()
