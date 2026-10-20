# KaTrain Electron

An Electron desktop shell for the original single-board [KaTrain](https://github.com/sanderland/katrain) interface, with persistent analysis sessions and a recent-games menu. Built and tested on **Apple Silicon macOS**.

## Added features compared with traditional KaTrain

These additions are implemented by this wrapper around upstream commit `f4981cf905cece90085ce4e3967415d0c16d525f`; this comparison does not claim that every newer upstream release lacks them.

- **Resume without re-analyzing:** saves the whole game tree and complete/partial KataGo analysis every 15 seconds and on normal close. Restores the selected position, variations, notes, and relevant view state. Reopens paused in Analysis mode without automatically re-requesting cached analysis.
- **Open Recent:** File → Open Recent remembers the latest 12 successfully viewed files across launches. Reopening moves an entry to the top without duplicates. Clear Recent Games clears only the list; missing files produce a warning.
- **Electron desktop integration:** native menus, open/save shortcuts, Finder file associations, drag-and-drop, single-instance handling, and persistent window bounds.
- **Separate app identity:** a custom indigo Go-grid icon and isolated settings/session data, allowing the app to coexist with traditional KaTrain.

Game rules, AI strategies, teaching tools, overlays, notes, SGF/NGF/GIB support, and advanced tools remain provided by upstream KaTrain. The four-game Workspace and study-PDF scripts are **not** part of this app or repository.

## Architecture and source scope

Electron owns the visible window and menus. The custom Python bridge runs upstream Kivy in a hidden window and sends rendered frames through private process pipes. An Electron canvas displays them and forwards input. There is no local HTTP server or screen-recording permission. This is an Electron/Python hybrid, not a JavaScript rewrite; individual Kivy controls are not HTML accessibility elements. Changed frames render at up to 20 fps.

Only the Electron shell, its custom Python bridge/session code, assets, scripts, and tests are stored here. The build fetches the pinned upstream KaTrain commit into ignored `build/` directories. Traditional KaTrain application source, Workspace modifications, models, binaries, game records, and local user data are not committed.

## Build on Apple Silicon macOS

Prerequisites:

- Xcode Command Line Tools (`xcode-select --install`), Git, Node.js/npm, and [uv](https://docs.astral.sh/uv/).
- Python 3.12 (uv can install it).
- A working **macOS arm64 KataGo executable** and a compatible neural-network `.bin.gz` model from [KataGo](https://github.com/lightvector/KataGo). Use a model supported by your engine version. The tested configuration uses a Homebrew-linked Metal backend and a b18 model. Use the original executable from its installation, not an executable extracted from an existing app bundle; the bundler resolves system and absolute Homebrew library paths. Models are separate downloads, not included in this repository.

```sh
git clone https://github.com/hzhang08/katrain-electron.git
cd katrain-electron
uv sync --python 3.12
npm ci

# Replace these with actual files on your machine.
export KATAGO_BINARY="/absolute/path/to/katago"
export KATAGO_MODEL="/absolute/path/to/model.bin.gz"

npm run build:backend
npm run package
```

The backend builder fetches the pinned KaTrain Git commit, freezes it with the bridge using PyInstaller, bundles the engine/model and non-system Homebrew libraries, and writes build provenance and license files. Dependency installation and the upstream fetch require internet access. `uv.lock` and `package-lock.json` pin dependency resolutions.

Outputs:

- `release/KaTrain Electron-darwin-arm64/KaTrain Electron.app`
- `release/KaTrain-Electron-mac-arm64.zip`

The packaged app includes its runtimes: users do not need Python, Node, Homebrew, or the source checkout. Packaging does not replace an installed app by default. To install to `~/Applications`, quit KaTrain Electron first and run:

```sh
KATRAIN_INSTALL=1 npm run package
```

The bundle is ad-hoc signed. Developer ID signing and notarization are not configured. These scripts do not implement Windows, Linux, or Intel macOS packaging.

## Development and validation

After building backend resources:

```sh
npm start
node --test tests/recent-games.test.cjs
uv run pytest tests/test_session.py
npm test
npm run test:session
```

Smoke tests use temporary user data and the real KataGo engine. They cover board input, analysis, navigation, dialogs, opening a file, reopening via Open Recent, history persistence, notes, saving, resizing, and shutdown. The session test then launches a fresh process and verifies exact cached restoration without analysis requests. GUI tests require an interactive macOS desktop.

Test the packaged app without development runtimes on PATH:

```sh
PATH=/usr/bin:/bin "release/KaTrain Electron-darwin-arm64/KaTrain Electron.app/Contents/MacOS/KaTrain Electron" --smoke
```

## Saved data

File → Show App Data opens `~/Library/Application Support/KaTrain Electron/`. Data includes `session.json`, `recent-games.json`, `window.json`, and `backend.log`. See [SESSION_FORMAT.md](SESSION_FORMAT.md) for the versioned snapshot format and recovery behavior. These are local user files and should not be committed. Session autosaving does not overwrite source game records.

## License and attribution

MIT; see [LICENSE](LICENSE). KaTrain is by Sander Land and contributors. Upstream code is fetched as a build dependency rather than vendored. The application bundle includes dependency licenses and `build-info.json` with the upstream revision, engine version, and model checksum. Electron, Kivy, KataGo, and model files retain their respective licenses.
