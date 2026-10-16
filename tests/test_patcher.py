from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cpcmodloader.launcher import syntax_check
from cpcmodloader.patcher import (
    PatchError, Plan, compile_plan, discover, inside, pattern_patch, regex_patch, relative_path, target_path,
)


class PatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cpc test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.scripts = self.game / "assets/scripts"
        self.scripts.mkdir(parents=True)
        (self.scripts / "main.lua").write_bytes(b"local value = 1\nreturn value\n")
        self.mods = self.root / "Mods"
        self.mods.mkdir()

    def manifest(self, body, name="test", priority=0, filename="cpcmodloader.toml"):
        root = self.mods / name
        (root / filename).parent.mkdir(parents=True, exist_ok=True)
        (root / filename).write_text(f'[manifest]\nversion="1.0.0"\npriority={priority}\n' + body, encoding="utf-8")
        return root

    def test_pattern_multiline_indent_crlf_limit(self):
        data = {"pattern": "if * then\nvalue = ?", "position": "after", "match_indent": True, "times": 1, "expected_matches": 2}
        source = "  if x then\r\n    value = 1\r\n  end\r\n  if y then\r\n    value = 2\r\n  end\r\n"
        result, matches, applied = pattern_patch(source, data, "do_it()")
        self.assertEqual((matches, applied), (2, 1))
        self.assertIn("    value = 1\r\n  do_it()\r\n  end", result)
        self.assertEqual(result.count("do_it()"), 1)

    def test_pattern_eof_and_positions(self):
        for position, expected in [("before", "b\na"), ("after", "a\nb\n"), ("at", "b\n")]:
            with self.subTest(position=position):
                result, _, _ = pattern_patch("a", {"pattern": "a", "position": position}, "b")
                self.assertEqual(result, expected)

    def test_pattern_brackets_are_literal(self):
        result, _, _ = pattern_patch("foo[1]", {"pattern": "foo[1]", "position": "at"}, "ok")
        self.assertEqual(result, "ok\n")

    def test_no_match_and_exact_count_fail(self):
        with self.assertRaisesRegex(PatchError, "0 times"):
            pattern_patch("a", {"pattern": "b", "position": "at"}, "c")
        with self.assertRaisesRegex(PatchError, "expected 1 matches, found 2"):
            pattern_patch("a\na", {"pattern": "a", "position": "at", "expected_matches": 1}, "b")
        self.assertEqual(pattern_patch("a", {"pattern": "b", "position": "at", "optional": True}, "c"), ("a", 0, 0))

    def test_regex_captures_and_literal_dollar(self):
        result, matches, applied = regex_patch("  local x = 1\n", {
            "pattern": r"(?<indent> +)local x = (\d+)", "position": "at", "line_prepend": "$indent",
        }, "local y = $2 -- $$ ${indent}")
        self.assertEqual(result, "  local y = 1 -- $   \n")
        self.assertEqual((matches, applied), (1, 1))
        with self.assertRaisesRegex(PatchError, "unknown regex capture"):
            regex_patch("a", {"pattern": "a", "position": "at"}, "$bad")

    def test_regex_zero_width_and_limit(self):
        result, matches, applied = regex_patch("a\nb", {"pattern": "^", "position": "before", "times": 1}, "-- ")
        self.assertEqual((result, matches, applied), ("-- a\nb", 2, 1))

    def test_paths_and_symlink_escape(self):
        for path in ("../x", "/x", r"C:\x", r"\\server\share\x", "a/../../x", "NUL.lua", "x:y", "a/.", ""):
            with self.subTest(path=path), self.assertRaises(PatchError):
                relative_path(path)
        self.assertEqual(target_path(r"scripts\main.lua"), "assets/scripts/main.lua")
        self.assertEqual(target_path("@assets/scripts/main.lua"), "assets/scripts/main.lua")
        link = self.mods / "link"
        try:
            link.symlink_to(self.game, target_is_directory=True)
        except OSError:
            return  # Windows symlinks require Developer Mode or elevation.
        with self.assertRaises(PatchError):
            inside(self.mods, "link/assets/scripts/main.lua")

    def test_discovery_aliases_order_and_disabled(self):
        body = '\n[[patches]]\n[patches.copy]\ntarget="main.lua"\nposition="prepend"\npayload="-- patch"\n'
        self.manifest(body, "z", -1)
        self.manifest(body, "a", 0, "lovely/subdir/x.toml")
        disabled = self.manifest(body, "disabled", -100)
        (disabled / ".disabled").touch()
        self.assertEqual([m.root.name for m in discover(self.mods)], ["z", "a"])
        self.manifest(body, "z", 0, "lovely.toml")
        with self.assertRaisesRegex(PatchError, "not both"):
            discover(self.mods)

    def test_variables_copy_and_multiple_targets(self):
        (self.scripts / "other.lua").write_text("return 2\n", encoding="utf-8")
        root = self.manifest('''
[vars]
value="42"
[[patches]]
[patches.copy]
target=["main.lua", "scripts/other.lua"]
position="prepend"
sources=["prelude.lua"]
payload="local b = {{lovely:value}}"
''')
        (root / "prelude.lua").write_text("local a = {{cpcmodloader:value}}", encoding="utf-8")
        plan = compile_plan(self.game, self.mods)
        self.assertEqual(len(plan.sources), 2)
        self.assertIn("local a = 42\nlocal b = 42\n", plan.sources["assets/scripts/main.lua"])
        self.assertEqual((self.scripts / "main.lua").read_text(), "local value = 1\nreturn value\n")
        self.assertNotEqual(plan.report()["files"]["assets/scripts/main.lua"]["original_sha256"], plan.report()["files"]["assets/scripts/main.lua"]["patched_sha256"])

    def test_priority_conflicts_and_phase_order(self):
        self.manifest('''
[[patches]]
[patches.pattern]
target="main.lua"
pattern="local inserted = 1"
position="at"
payload="local inserted = 2"
expected_matches=1
[[patches]]
[patches.copy]
target="main.lua"
position="prepend"
payload="local inserted = 1"
''', "first", -1)
        self.manifest('''
[[patches]]
[patches.regex]
target="main.lua"
pattern="inserted = 2"
position="at"
payload="inserted = 3"
expected_matches=1
''', "second")
        self.assertIn("local inserted = 3", compile_plan(self.game, self.mods).sources["assets/scripts/main.lua"])

    def test_unknown_fields_and_missing_targets_fail(self):
        path = self.manifest('''
[[patches]]
[patches.copy]
target="missing.lua"
position="prepend"
payload="-- test"
''') / "cpcmodloader.toml"
        with self.assertRaisesRegex(PatchError, "no target"):
            compile_plan(self.game, self.mods)
        path.write_text(path.read_text().replace('target="missing.lua"', 'target="main.lua"\npostion="prepend"'))
        with self.assertRaisesRegex(PatchError, "unknown copy field"):
            compile_plan(self.game, self.mods)

    def test_source_traversal_fails(self):
        self.manifest('''
[[patches]]
[patches.copy]
target="main.lua"
position="prepend"
sources=["../secret.lua"]
''')
        with self.assertRaisesRegex(PatchError, "inside its root"):
            compile_plan(self.game, self.mods)

    def test_undefined_variable_fails(self):
        self.manifest('''
[[patches]]
[patches.copy]
target="main.lua"
position="prepend"
payload="{{lovely:missing}}"
''')
        with self.assertRaisesRegex(PatchError, "undefined variable"):
            compile_plan(self.game, self.mods)

    def test_module_execution_without_package_library(self):
        lua = shutil.which("lua5.4") or shutil.which("lua")
        if not lua:
            self.skipTest("Lua interpreter not installed")
        root = self.manifest('''
[[patches]]
[patches.module]
name="example"
source="module.lua"
before="main.lua"
[[patches]]
[patches.copy]
target="main.lua"
position="prepend"
payload="assert(_G.cpcmodloader.require('example').answer == 42)"
''')
        (root / "module.lua").write_text("return {answer = 42}", encoding="utf-8")
        plan = compile_plan(self.game, self.mods)
        syntax_check(plan)
        result = subprocess.run([lua, "-"], input="package=nil; require=nil\n" + plan.sources["assets/scripts/main.lua"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_duplicates_fail(self):
        body = '''
[[patches]]
[patches.module]
name="example"
source="module.lua"
before="main.lua"
'''
        self.manifest(body, "a")
        self.manifest(body, "b")
        with self.assertRaisesRegex(PatchError, "duplicate module"):
            compile_plan(self.game, self.mods)

    def test_glob_targets_and_bom(self):
        (self.scripts / "other.lua").write_bytes(b"\xef\xbb\xbfreturn 2\n")
        self.manifest('''
[[patches]]
[patches.copy]
target="*.lua"
position="prepend"
payload="-- hello"
''')
        plan = compile_plan(self.game, self.mods)
        self.assertEqual(len(plan.sources), 2)
        self.assertNotIn("\ufeff", plan.sources["assets/scripts/other.lua"])

    def test_invalid_lua_is_rejected(self):
        self.manifest('''
[[patches]]
[patches.copy]
target="main.lua"
position="prepend"
payload="local = broken syntax"
''')
        plan = compile_plan(self.game, self.mods)
        if syntax_check(Plan()).startswith("skipped"):
            self.skipTest("Lua 5.4 compiler not installed")
        with self.assertRaisesRegex(PatchError, "Lua syntax error"):
            syntax_check(plan)

    def test_malformed_manifest_reports_origin(self):
        self.manifest("\n[[patches]\n")
        with self.assertRaisesRegex(PatchError, "cpcmodloader.toml"):
            compile_plan(self.game, self.mods)

    def test_invalid_fields_are_not_coerced(self):
        for field, value in (("times", 0), ("times", True), ("match_indent", "yes"), ("optional", "yes")):
            with self.subTest(field=field), self.assertRaises(PatchError):
                pattern_patch("a", {"pattern": "a", "position": "at", field: value}, "b")

    def test_runtime_cache_cycle_and_error_cleanup(self):
        lua = shutil.which("lua5.4") or shutil.which("lua")
        if not lua:
            self.skipTest("Lua interpreter not installed")
        runtime = Path(__file__).parents[1] / "cpcmodloader/runtime.lua"
        test = '''
local api = _G.cpcmodloader
local calls = 0
api.preload("false_module", function() calls = calls + 1; return false end)
assert(api.require("false_module") == false)
assert(api.require("false_module") == false and calls == 1)
api.preload("loop", function() return api.require("loop") end)
local ok, err = pcall(api.require, "loop")
assert(not ok and string.find(err, "circular"))
assert(api.loading.loop == nil)
api.preload("empty", function() end)
assert(api.require("empty") == true)
'''
        result = subprocess.run([lua, "-"], input=runtime.read_text() + test, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
