"""Build a portable Python zipapp and source release using only the standard library."""

from pathlib import Path
import shutil
import tempfile
import zipapp
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

with tempfile.TemporaryDirectory(prefix="cpcmodloader-package-") as temporary:
    stage = Path(temporary)
    shutil.copytree(ROOT / "cpcmodloader", stage / "cpcmodloader", ignore=shutil.ignore_patterns("__pycache__"))
    (stage / "__main__.py").write_text("from cpcmodloader.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
    zipapp.create_archive(stage, DIST / "cpcmodloader.pyz", interpreter="/usr/bin/env python3", compressed=True)

with zipfile.ZipFile(DIST / "cpcmodloader-source.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for entry in ("cpcmodloader", "scripts", "tests", "examples", "docs", ".github", "README.md", "CONTRIBUTING.md", "SECURITY.md", "requirements-dev.txt", "LICENSE", "pyproject.toml", ".gitignore"):
        path = ROOT / entry
        for source in sorted(path.rglob("*") if path.is_dir() else [path]):
            if source.is_file() and "__pycache__" not in source.parts:
                archive.write(source, Path("cpcmodloader") / source.relative_to(ROOT))

print(DIST / "cpcmodloader.pyz")
print(DIST / "cpcmodloader-source.zip")
