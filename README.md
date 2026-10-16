# cpc-modloader

A [Lovely-style](https://github.com/ethangreen-dev/lovely-injector) Lua mod loader for **Car Park Capital**. Install the game through Steam first.

## Linux

1. [Download the Linux ZIP](https://github.com/cyberbalsa/cpc-modloader/releases/latest/download/cpc-modloader-linux-x86_64.zip) and extract it outside the game folder.
2. Allow `cpc-modloader` to run as a program: open a terminal in its folder and run `chmod +x cpc-modloader`.
3. In Steam, choose **Games → Add a Non-Steam Game → Browse** and select `cpc-modloader`.
4. Open the shortcut’s **Properties**. Set **Start In** to the extracted folder and **Launch Options** to `run`. Launch this shortcut from Steam.

## Windows

1. [Download the Windows ZIP](https://github.com/cyberbalsa/cpc-modloader/releases/latest/download/cpc-modloader-windows-x86_64.zip) and extract it outside the game folder.
2. In Steam, choose **Games → Add a Non-Steam Game → Browse** and select `cpc-modloader.exe`.
3. Open the shortcut’s **Properties**. Set **Start In** to the extracted folder and **Launch Options** to `run`. Launch this shortcut from Steam.

Put extracted mods beside the loader: `Mods/MyMod/cpcmodloader.toml`. The main menu’s top-left label shows the loader version and mod count.

If the game isn’t found, use `run --game-dir "path/to/Car Park Capital"` instead.

Modded saves live in `run/default/game/saves`. Original saves stay untouched.

[Writing mods](docs/modding.md) · [Troubleshooting](docs/reference.md)
