"""Package a PyInstaller executable for end users."""

from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
platform = "windows" if sys.platform == "win32" else "linux"
binary = "cpc-modloader.exe" if platform == "windows" else "cpc-modloader"
output = ROOT / "dist" / f"cpc-modloader-{platform}-x86_64.zip"

with tempfile.TemporaryDirectory(prefix="cpc-release-") as temporary:
    stage = Path(temporary) / "cpc-modloader"
    stage.mkdir()
    shutil.copy2(ROOT / "dist" / binary, stage / binary)
    documentation = stage / "cpc-modloader-docs"
    documentation.mkdir()
    for name in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / name, documentation / name)
    for name in ("docs", "examples"):
        shutil.copytree(ROOT / name, documentation / name)
    (stage / "Mods").mkdir()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file() or path.name == "Mods":
                archive.write(path, path.relative_to(stage))
print(output)
