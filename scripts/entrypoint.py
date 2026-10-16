"""PyInstaller entry point (absolute imports work in frozen builds)."""
from cpcmodloader.cli import main

raise SystemExit(main())
