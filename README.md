# cpc-modloader

A [Lovely-style](https://github.com/ethangreen-dev/lovely-injector) Lua mod loader for **Car Park Capital**.

In Steam, open the game’s **Properties → Installed Files → Browse** to find its folder.

## Linux

1. [Download the Linux ZIP](https://github.com/cyberbalsa/cpc-modloader/releases/latest/download/cpc-modloader-linux-x86_64.zip) and extract its contents into the game folder, beside `carparkcapital`.
2. Open a terminal there and run `chmod +x cpc-modloader`.
3. Set **Properties → General → Launch Options** to:

```text
./cpc-modloader steam -- %command%
```

## Windows

1. [Download the Windows ZIP](https://github.com/cyberbalsa/cpc-modloader/releases/latest/download/cpc-modloader-windows-x86_64.zip) and extract its contents into the game folder, beside `carparkcapital.exe`.
2. Set **Properties → General → Launch Options** to:

```text
.\cpc-modloader.exe steam -- %command%
```

Put mods in `Mods/MyMod/cpcmodloader.toml` inside the game folder, then click **Play** in Steam. The top-left menu label shows the loader version and mod count.

Modded saves: `cpc-modloader-data/default/game/saves`. Original saves stay untouched. Clear Launch Options to play without the loader.

[Writing mods](docs/modding.md) · [Troubleshooting](docs/reference.md)
