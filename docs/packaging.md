# Desktop packaging

The release targets are Windows x64 and macOS Apple Silicon. The app carries a PyInstaller one-folder worker and a target-native media toolchain as Tauri resources. Each target is built on its own runner because PyInstaller, native libraries, and platform bundles are target-specific. See the [Ticket 07 research report](research/ticket-07-windows-macos-packaging.md) for the source comparison and upstream references.

## Toolchain included in each package

| Tool | Locked version | Purpose |
| --- | --- | --- |
| FFmpeg / ffprobe | 9.0.2 | Source/background probe and final H.264/AAC render with libass subtitles. |
| yt-dlp | 2026.08.19 | Source metadata, audio, captions, and source thumbnail download. |
| Deno | 2.9.7 | JavaScript runtime used by current yt-dlp YouTube extraction. |
| Tesseract | 5.5.3 | OCR text from the original thumbnail. |
| tessdata_fast | pinned commit in `scripts/toolchain-lock.json` | English (`eng`) and Vietnamese (`vie`) LSTM language models. |

The packager fails if a pinned tool version or required FFmpeg capability changes. Before Tauri packaging, `scripts/stage_tools.py` creates this resource layout:

```text
desktop/src-tauri/resources/tools/
├── bin/                 # ffmpeg, ffprobe, yt-dlp, deno, tesseract
├── lib/                 # non-system macOS dylibs needed by Tesseract
├── licenses/            # upstream notices and license texts
├── tessdata/            # eng.traineddata and vie.traineddata
├── worker/              # PyInstaller one-folder Python worker
└── manifest.json        # target, tool versions, source URLs, SHA-256 hashes
```

On Windows, the pinned Chocolatey FFmpeg Full build supplies FFmpeg and ffprobe; the Tesseract install directory's DLLs are copied beside the executables. On macOS, Homebrew supplies FFmpeg and Tesseract and `dylibbundler` copies Tesseract's non-system library dependencies into `lib/` and rewrites their runtime paths. yt-dlp and Deno are downloaded from their official GitHub releases and checked against GitHub's SHA-256 asset digest before extraction. The OCR models are fetched from the pinned `tessdata_fast` commit.

The worker receives absolute executable paths and the app's resource directory from the Tauri host. The tool directory is prepended to `PATH`, and the worker passes the selected Deno path to yt-dlp explicitly with `--js-runtimes`. The app data database, downloaded sources, outputs, and user-selected backgrounds remain outside the read-only application bundle.

At every app launch, the startup splash checks FFmpeg/ffprobe capabilities, Tesseract, and its OCR models. Missing pinned `eng`/`vie` models are restored from the exact revision and SHA-256 values in the packaged manifest. It then checks the latest stable releases for yt-dlp and Deno; missing or older binaries are downloaded from their official GitHub releases, SHA-256 verified, executed to verify their reported versions, and atomically installed under the app data `tools/` directory. The Tauri host prefers those app-data copies on later worker requests, leaving the installed app bundle unchanged. The main workspace opens only after this completes. If GitHub is unreachable or a download cannot be verified, the splash stays open with an error and Retry action.

YouTube cookies are optional. Settings stores the path to the user-selected Netscape-format `cookies.txt` file and the worker adds `--cookies` to metadata, source media, subtitle, and thumbnail commands. The cookie file stays in its original location; its contents are not copied to the database or uploaded. Treat the file as a password because it contains login session credentials.

Only `eng` and `vie` traineddata are included in this first package. Other OCR languages can still be configured, but Tesseract will report the missing model and the job will continue to manual thumbnail review.

## Build and smoke-check locally

Run the commands from the repository root. A target-native machine and its system prerequisites are required.

### macOS Apple Silicon

Install Rust, Node 24, Python 3.12, Xcode Command Line Tools, and Homebrew. Install the pinned toolchain versions; if Homebrew has moved past a locked version, update `scripts/toolchain-lock.json` and validate the new package before building.

```sh
brew install ffmpeg tesseract dylibbundler
export YOUTUBE_BATCH_FFMPEG="$(brew --prefix ffmpeg)/bin/ffmpeg"
export YOUTUBE_BATCH_FFPROBE="$(brew --prefix ffmpeg)/bin/ffprobe"
export YOUTUBE_BATCH_TESSERACT="$(brew --prefix tesseract)/bin/tesseract"
export YOUTUBE_BATCH_TESSERACT_RUNTIME="$(brew --prefix tesseract)"
python3.12 -m venv worker/.venv
source worker/.venv/bin/activate
python -m pip install -r worker/requirements-build.txt
python scripts/fetch_tool_releases.py
python scripts/stage_tools.py
python scripts/build_worker.py
python scripts/smoke_package.py
cd desktop
npm ci
npm run build
npm run tauri -- build --bundles app,dmg
```

`YOUTUBE_BATCH_ALLOW_TOOL_VERSION_DRIFT=1` can be used for a local diagnostic build when an installed tool is one patch behind the lock. Do not set it in release CI.

### Windows x64

Install Rust, Node 24, Python 3.12, Visual Studio C++ Build Tools, and Chocolatey. The executable paths below are the same locations used by `.github/workflows/package-smoke.yml`.

```powershell
choco install ffmpeg-full --version=9.0.2 --yes
choco install tesseract --version=5.5.3.20260724 --yes
choco install nsis --yes
$ffmpegBin = (Get-ChildItem "$env:ChocolateyInstall\lib\ffmpeg-full\tools" -Filter ffmpeg.exe -Recurse | Select-Object -First 1).DirectoryName
$env:YOUTUBE_BATCH_FFMPEG = Join-Path $ffmpegBin "ffmpeg.exe"
$env:YOUTUBE_BATCH_FFPROBE = Join-Path $ffmpegBin "ffprobe.exe"
$env:YOUTUBE_BATCH_TESSERACT = "$env:ProgramFiles\Tesseract-OCR\tesseract.exe"
$env:YOUTUBE_BATCH_TESSERACT_RUNTIME = "$env:ProgramFiles\Tesseract-OCR"
py -3.12 -m venv worker/.venv
worker/.venv/Scripts/python.exe -m pip install -r worker/requirements-build.txt
worker/.venv/Scripts/python.exe scripts/fetch_tool_releases.py
worker/.venv/Scripts/python.exe scripts/stage_tools.py
worker/.venv/Scripts/python.exe scripts/build_worker.py
worker/.venv/Scripts/python.exe scripts/smoke_package.py
Push-Location desktop
npm ci
npm run build
npm run tauri -- build --bundles nsis
Pop-Location
```

## What the fixture smoke test checks

`scripts/smoke_package.py` uses only local generated fixtures; it does not contact YouTube or need account credentials. It checks:

- yt-dlp and Deno start and print their versions;
- FFmpeg exposes `libx264`, AAC, and the `subtitles` filter;
- Tesseract finds `eng` in the packaged data folder and recognizes text in a generated image;
- FFmpeg loops a generated background, adds generated audio, burns an SRT caption, and writes a playable H.264/AAC MP4;
- ffprobe reports a 320×180 H.264 video stream and an AAC audio stream;
- the packaged worker starts and answers its JSON health request.

The same checks run on both target runners in `.github/workflows/package-smoke.yml`. The workflow also builds and uploads the native Tauri package; it does not install and launch the generated installer. Locally, run the smoke script against the final `.app/Contents/Resources/resources/tools` directory as well as the staged directory. The smoke does not automate clicking native file dialogs; the app uses the Tauri dialog plugin for background and output path selection, which still needs a manual check on each OS before a user-facing release.

## Native dialogs and WebView

File and folder selection use `tauri-plugin-dialog`; the native dialogs return paths that the worker receives as ordinary local paths. Tauri uses the system WebView: WKWebView on macOS and WebView2 on Windows. The Windows NSIS installer uses the WebView2 bootstrapper path; an offline installer would need a separate WebView2 offline payload and is not produced by this workflow.

## Signing and redistribution

Local development bundles do not need distribution credentials. macOS direct distribution needs Developer ID signing and notarization. Windows code signing is required for Microsoft Store distribution and avoids the unsigned-app SmartScreen warning. Add signing secrets only to a release workflow; do not add them to local builds.

The selected FFmpeg path includes libx264 and therefore uses a GPL-enabled FFmpeg build. yt-dlp's standalone executable also bundles third-party components; the package includes its upstream `THIRD_PARTY_LICENSES.txt`. Tesseract and its traineddata use Apache-2.0. The resource bundle includes the upstream license files fetched during packaging, but they are not a substitute for auditing every native dependency copied by Homebrew/Chocolatey. Before publishing installer artifacts outside personal/internal use, review the exact `manifest.json`, all copied dynamic-library licenses, source-code availability obligations for the FFmpeg build, and each upstream redistribution condition. The current CI artifact is a packaging/smoke artifact, not a signed public release.
