# Commands and profiles


| Command | Purpose |
| --- | --- |
| `inspect` | Show the detected executable and Lua script count |
| `mods` | List enabled manifests in application order |
| `check` | Resolve patches and check Lua syntax without creating a profile |
| `build` | Prepare an isolated game without launching it |
| `run` | Rebuild patches, launch, and wait for the game to exit |

Options follow the command. All commands accept `--game-dir` and `--mods-dir`. `build` and `run` accept `--profile-dir` (default `run/default`). Set `CPC_GAME_DIR` to override automatic game discovery. Pass game arguments after `--`.

Lua syntax checks run automatically when a Lua **5.4** compiler is available as `luac5.4`, `luac54`, or `luac`. Use `--luac /path/to/luac` to specify one explicitly. An explicitly requested compiler must exist and be version 5.4. Without a suitable compiler, the command clearly reports that syntax checking was skipped; manifest validation and match checks still run.

The profile contains:

```text
run/default/
  cpcmodloader-profile.json       # ownership and source installation
  game.log                       # latest game stdout/stderr
  game/
    carparkcapital[.exe]
    assets/scripts/...           # patched sources available for inspection
    cpcmodloader-report.json     # manifests, matches, file hashes, syntax result
    saves/                       # persistent modded saves
    settings.json                # persistent modded settings
    imgui.ini
```

The first build copies the installed game's settings and starts with an **empty modded saves directory**. Subsequent builds preserve the profile's `saves/`, `settings.json`, and `imgui.ini`. To use an existing save, copy it into the profile's `game/saves/` while the game is closed. Launch the original game through Steam for your original saves.

Assets and the executable are independent copies. Linux uses copy-on-write cloning when supported; otherwise the launcher copies files, as it does on Windows. Allow about the size of the installation per profile, plus temporary build space. Builds are staged before publication, failures keep the previous build, and an OS lock prevents concurrent builds/launches in the same profile. Do not launch the generated executable directly while rebuilding that profile.

Removing a mod, adding a `.disabled` file in its folder, or setting a manifest's `enabled = false` takes effect on the next `run` or `build`. To remove the loader, remove this project and any profiles you no longer need; profiles contain your modded saves.

