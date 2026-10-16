# Commands and profiles

| Command | Purpose |
| --- | --- |
| `inspect` | Show the game version, Steam build, file hashes, compatibility, and executable |
| `mods` | List enabled manifests in application order |
| `check` | Resolve patches and check Lua syntax without creating a profile |
| `build` | Prepare an isolated game without launching it |
| `run` | Rebuild patches, launch, and wait for the game to exit |
| `steam` | Build and replace the game executable in Steam's `%command%` |

Options follow the command. All commands accept `--game-dir` and `--mods-dir`. `build`, `run`, and `steam` accept `--profile-dir`. An installation in the game folder uses `cpc-modloader-data/default`; standalone installations keep `run/default`. Release executables find `Mods` beside themselves, independent of the working directory. Source commands use the working directory instead.

`steam -- %command%` preserves Steam's runtime wrappers and game arguments, replacing only the native game executable with the patched copy. On Linux, use the game's native Linux build. For direct `run`, pass game arguments after `--`. Set `CPC_GAME_DIR` or `--game-dir` to override discovery; in `steam` mode it must match the game in Steam's command.

The main menu shows the loader version and loaded mod count in the top-left corner, including when no mods are installed. Each enabled mod folder counts once, even if it contains several manifests. Disabled folders and manifests do not count. The label disappears when you leave the main menu.

Lua syntax checks run automatically when a Lua **5.4** compiler is available as `luac5.4`, `luac54`, or `luac`. Use `--luac /path/to/luac` to specify one explicitly. An explicitly requested compiler must exist and be version 5.4. Without a suitable compiler, the command clearly reports that syntax checking was skipped; manifest validation and match checks still run.

The profile contains:

```text
cpc-modloader-data/default/
  cpcmodloader-profile.json       # ownership and source installation
  game.log                       # latest game stdout/stderr
  game/
    carparkcapital[.exe]
    assets/scripts/...           # patched sources available for inspection
    cpcmodloader-report.json     # manifests, matches, file hashes, syntax result
    saves/                       # link to the installed game's saves
    settings.json                # persistent modded settings
    imgui.ini
```

Saves, scenario progress, and blueprints use the installed game's normal `saves/` directory, including when launched through Steam. The profile points there with a Linux symlink or Windows directory junction; Windows does not need Developer Mode. Writes go straight to that folder so Steam Cloud can sync them. Clearing Launch Options keeps the same saves.

On the first build after upgrading from v0.1.2 or earlier, the loader backs up nonempty profile saves to `saves-backup-*/saves` inside the profile, then imports files missing from the normal save folder. Existing files win any conflict; the old profile's versions remain in the backup. The build output and report list the backup path and conflicts. Close the game before upgrading. For a different, older profile, copy any saves you want from it into the game's normal `saves/` folder while the game is closed.

Settings remain per-profile. The first build copies the installed game's settings; later builds preserve `settings.json` and `imgui.ini`.

Assets and the executable are independent copies. Linux uses copy-on-write cloning when supported; otherwise the launcher copies files, as it does on Windows. Allow about the size of the installation per profile, plus temporary build space. Builds are staged before publication, failures keep the previous build, and an OS lock prevents concurrent builds/launches in the same profile. Do not launch the generated executable directly while rebuilding that profile.

Removing a mod, adding a `.disabled` file in its folder, or setting a manifest's `enabled = false` takes effect on the next launch or build. To uninstall, clear Steam's Launch Options and remove `cpc-modloader` / `cpc-modloader.exe` and `cpc-modloader-docs`. Keep `Mods` and any `saves-backup-*` folders you want to retain. Your current saves stay in the game's `saves/` folder.

## Game updates

v0.1.3 recognizes **Early Access 1.0.1, Steam build 25985572**, on Linux and Windows. The loader reads the version from the executable and the build ID from Steam's app manifest, then checks executable and Lua source hashes against tested copies. Without a Steam manifest, matching version and file hashes are sufficient. A changed executable or script is treated as unverified even if the version number stayed the same.

An unverified game stops before building or launching. The previous profile and saves stay in place. Steam launch failures show a desktop dialog when Windows, Zenity, or KDialog is available; the message is also saved to `cpc-modloader-data/launch-error.txt` beside the loader.

Install the latest loader first. To test an unverified game, back up the game's saves and add the override before `--`:

```text
# Linux
./cpc-modloader steam --allow-unsupported-game -- %command%
# Windows
.\cpc-modloader.exe steam --allow-unsupported-game -- %command%
```

The menu then shows an unverified-game warning. Mod version requirements and patch matching still apply. Clear Launch Options to play the original game. Remove the override after a loader release adds support for the new game build.

`check`, `build`, `run`, and `steam` enforce these checks. Each successful build records game identity, compatibility, and notices in `game/cpcmodloader-report.json`. If the executable or Lua sources change during copying, the build is discarded.

## Loader updates

`run` and `steam` check the [latest public stable GitHub release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release) at most once per day. A newer version adds an amber menu notice and a download link in launcher output. Download the new ZIP and extract it over the loader while the game is closed. Mods and saves stay in place.

The check sends no game files, mod list, or Steam account details. It waits at most three seconds, continues offline on failure, and retries failures after an hour. A previously detected newer release still produces a notice offline. Results are cached in `cpc-modloader-data/update-check.json` beside the loader; nothing is downloaded or installed automatically.

Add `--no-update-check` before `--` in Steam Launch Options to disable the network check and update notice. `inspect`, `mods`, `check`, and `build` never check GitHub.
