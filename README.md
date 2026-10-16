# cpc-modloader

A [Lovely-style](https://github.com/ethangreen-dev/lovely-injector) Lua mod loader for **Car Park Capital** on Windows and Linux.

1. Install Car Park Capital through Steam.
2. [Download](https://github.com/cyberbalsa/cpc-modloader/releases/latest) the loader for your OS and extract it outside the game folder. No Python installation needed.
3. Put each extracted mod folder in `Mods` beside the loader: `Mods/MyMod/cpcmodloader.toml`.
4. In Steam, choose **Games → Add a Non-Steam Game → Browse** and select `cpc-modloader.exe` (Windows) or `cpc-modloader` (Linux).
5. Open that shortcut’s **Properties**. Set **Start In** to the extracted folder and **Launch Options** to `run`. Click **Play** on this shortcut to launch with mods.

If the game isn’t found, use `run --game-dir "path/to/Car Park Capital"` instead. On Linux, allow the loader to run as a program if needed.

Modded saves live in `run/default/game/saves`; your original game and saves stay untouched. Remove a mod folder to disable it on the next launch.

[Writing mods](docs/modding.md) · [Troubleshooting and commands](docs/reference.md)
