# Writing mods

Create a folder inside `Mods`:

```text
Mods/MyMod/
  cpcmodloader.toml
  code.lua
```

Alternatively place multiple `.toml` files recursively in `Mods/MyMod/cpcmodloader/`. `lovely.toml` and `lovely/**/*.toml` are accepted aliases, but a mod must use one naming family. Top-level manifest files and files within the matching subdirectory are combined. `.disabled` disables the whole mod; hidden mod folders are ignored. Archives must be extracted first.

```toml
[manifest]
version = "1.0.0"  # manifest schema, not the mod's release version
priority = 0       # lower values first; ties sort by mod and manifest path

[vars]
message = "My mod loaded"

[[patches]]
[patches.pattern]
target = "ui_screens/MainMenu.lua"
pattern = 'local paletteGenerator = include("scripts/ui_screens/palette_generator")'
position = "after"
payload = '_G.cpcmodloader.log("{{cpcmodloader:message}}")'
match_indent = true
expected_matches = 1
```

Targets are relative to `assets/scripts/`. `scripts/…`, `assets/scripts/…`, leading `@`, and Windows separators are accepted too. Target arrays and `*`/`?` wildcards are supported; wildcards can span directory separators. Matching is case-sensitive on both platforms. Missing target files are errors.

Patch phases are **module → copy → pattern/regex**. Within each phase, ascending manifest priority and then manifest/patch order apply. Pattern and regex patches are interleaved in declaration order. A later patch sees earlier source changes. Multiple prepends naturally place the last prepended text first. Modules register before copied/injected code executes. Every patched chunk gets an idempotent runtime prelude.

Variables are manifest-local strings. `{{cpcmodloader:key}}` and `{{lovely:key}}` substitute into patch string fields and mod source contents. Values are inserted verbatim, so write valid Lua quoting yourself. Undefined variables fail the build. Built-in Lovely path variables are not implemented.

### Pattern patches

Patterns match complete trimmed lines, or consecutive lines for multiline patterns. `*` matches any number of characters and `?` matches one; other characters are literal. `before`, `after`, and `at` insert before, insert after, and replace the matched lines. `match_indent` adds the first matched line's indentation to each payload line. Line endings are preserved.

`times = N` limits application to the first N matches. `expected_matches = N` requires exactly N matches before limiting, which helps detect game updates and conflicting mods. Without a match, builds fail unless `optional = true` or `expected_matches = 0` is set. This stricter failure behavior intentionally differs from Lovely's warnings. Reports show both found and applied counts.

### Regex patches

```toml
[[patches]]
[patches.regex]
target = "ui_screens/MainMenu.lua"
pattern = '(?<indent>[\t ]*)secondaryPalette\.childBg = secondaryPalette\.windowBg'
position = "at"
line_prepend = "$indent"
payload = 'secondaryPalette.childBg = secondaryPalette.windowBg -- patched'
expected_matches = 1
```

Uses Python's regex syntax in multiline mode, with `(?<name>...)` accepted as an alias for `(?P<name>...)`. Captures in payloads and `line_prepend` use `$name`, `${name}`, or `$1`; `$$` inserts a literal dollar sign. Positions, `times`, `optional`, and `expected_matches` work as above. Regex operates on character spans and adds no automatic newline. Rust-specific regex features and Lovely's `at` capture-group weaving are not implemented.

### Copy patches

```toml
[[patches]]
[patches.copy]
target = "ui_screens/StartupScreen.lua"
position = "prepend"  # or append
sources = ["code.lua"]
payload = '_G.cpcmodloader.log("Ready")'
```

Files are resolved from the mod folder and concatenated in order, followed by the optional inline payload. At least `sources` or `payload` is required. Code is inserted into the target chunk's environment. Appending after a top-level `return` can produce invalid Lua; use `prepend` or a module in that case.

### Module patches

```toml
[[patches]]
[patches.module]
name = "my_mod.helpers"
source = "helpers.lua"
before = "ui_screens/StartupScreen.lua"
load_now = false
```

The file is wrapped as a Lua factory and registered before the target's code. Call `_G.cpcmodloader.require("my_mod.helpers")` for a cached result. Inside a module factory, local `require` uses the same loader. If the game exposes Lua's package library, the module is also registered in `package.preload`; if no native `require` exists, the runtime supplies one. `load_now = true` executes the module immediately after registration. Choose a `before` target that actually executes before its consumers, and register dependencies before eager consumers. Module names must be unique across all enabled manifests.

The runtime exposes `_G.cpcmodloader.version`, `.mod_count`, `.status` (the menu label), `.game_version`, `.game_build`, `.notices`, `.update_url`, `.log(message)`, `.preload(name, factory)`, and `.require(name)`. Unknown game versions/builds are `nil`. Module errors propagate to the game, circular dependencies report an error, and modules are cached per Lua state. Factories inherit their registration chunk's environment. This first version does not expose runtime repatching, native modules, or patch targets inside injected module factories.

### Version requirements

Add an optional top-level table to each manifest:

```toml
[compatibility]
game = ">=1.0.1, <1.1.0"
loader = ">=0.1.2"
steam_builds = ["25985572"] # Optional exact Steam build IDs
```

Versions use three numbers. A bare version or `=` / `==` means exact equality; `>`, `>=`, `<`, and `<=` are also supported. Comma-separated requirements must all match. Wildcards, prereleases, `^`, `~`, and OR expressions are not supported. `manifest.version` remains the manifest format version, `1.0.0`.

Each field is optional. An omitted table adds no mod-specific restriction. A mismatch or an unknown required version stops the entire build before patches run; update or disable the named mod. `--allow-unsupported-game` only bypasses the loader's tested-game check, never a mod's declared requirements. Disabled mods are ignored.
