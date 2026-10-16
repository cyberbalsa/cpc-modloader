"""Exercise a frozen executable without distributing any game files."""

from pathlib import Path
import subprocess
import sys
import tempfile

program = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="cpc bundle test ") as temporary:
    root = Path(temporary)
    scripts = root / "game/assets/scripts"
    scripts.mkdir(parents=True)
    (scripts / "main.lua").write_text("return 1\n", encoding="utf-8")
    (scripts / "entities/3d").mkdir(parents=True)
    (scripts / "entities/3d/MainMenu.lua").write_text("function create(menu) end\n", encoding="utf-8")
    mod = root / "Mods/test"
    mod.mkdir(parents=True)
    (mod / "cpcmodloader.toml").write_text('''[manifest]
version = "1.0.0"
[[patches]]
[patches.copy]
target = "main.lua"
position = "prepend"
payload = "print('bundled mod')"
''', encoding="utf-8")
    result = subprocess.run([str(program), "check", "--game-dir", str(root / "game"), "--mods-dir", str(root / "Mods")], cwd=root, capture_output=True, text=True, timeout=60)
    print(result.stdout, end="")
    if result.returncode or "2 patched scripts" not in result.stdout:
        raise SystemExit(result.stderr or f"Unexpected result: {result.returncode}")
