from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "scripts" / "toolchain-lock.json").read_text(encoding="utf-8"))
TOOLS = ROOT / "desktop" / "src-tauri" / "resources" / "tools"
BIN = TOOLS / "bin"
LIB = TOOLS / "lib"
TESSDATA = TOOLS / "tessdata"
LICENSES = TOOLS / "licenses"
USER_AGENT = "youtube-video-batch-tool-packager"


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(command)}\n{detail[-2000:]}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def copy_runtime_dlls(source: Path) -> None:
    if os.name != "nt":
        return
    for path in source.rglob("*.dll"):
        destination = BIN / path.name
        if destination.exists() and sha256(destination) != sha256(path):
            raise SystemExit(f"Conflicting Windows runtime DLLs have the same filename: {path.name}")
        if not destination.exists():
            shutil.copy2(path, destination)


def bundle_macos_libraries() -> None:
    if platform.system() != "Darwin":
        return
    bundler = shutil.which("dylibbundler")
    if not bundler:
        raise SystemExit("Install dylibbundler with Homebrew before staging macOS tools.")
    LIB.mkdir(parents=True, exist_ok=True)
    command = [bundler, "-b", "-cd"]
    for name in ("ffmpeg", "ffprobe", "yt-dlp", "deno", "tesseract"):
        executable = BIN / name
        if executable.is_file():
            command.extend(["-x", str(executable)])
    command.extend(["-d", str(LIB), "-p", "@executable_path/../lib"])
    run(command)


def fetch_traineddata() -> dict[str, str]:
    repository = LOCK["tesseract"]["traineddata_repository"]
    revision = LOCK["tesseract"]["traineddata_revision"]
    TESSDATA.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for language in LOCK["tesseract"]["languages"]:
        hashes[language] = download(
            f"https://raw.githubusercontent.com/{repository}/{revision}/{language}.traineddata",
            TESSDATA / f"{language}.traineddata",
        )
    license_url = f"https://raw.githubusercontent.com/{repository}/{revision}/LICENSE"
    hashes["LICENSE"] = download(license_url, LICENSES / "tessdata_fast-LICENSE")
    return hashes


def main() -> int:
    if os.name != "nt" and not (platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}):
        raise SystemExit("Release staging supports Windows x64 and macOS Apple Silicon only.")
    names = ("ffmpeg", "ffprobe", "yt-dlp.exe" if os.name == "nt" else "yt-dlp", "deno.exe" if os.name == "nt" else "deno")
    missing = [BIN / name for name in names[-2:] if not (BIN / name).is_file()]
    if missing:
        raise SystemExit(f"Run scripts/fetch_tool_releases.py first; missing: {', '.join(map(str, missing))}")

    tesseract_source = Path(os.environ.get("YOUTUBE_BATCH_TESSERACT", ""))
    ffmpeg_source = Path(os.environ.get("YOUTUBE_BATCH_FFMPEG", ""))
    ffprobe_source = Path(os.environ.get("YOUTUBE_BATCH_FFPROBE", ""))
    tesseract_runtime = Path(os.environ.get("YOUTUBE_BATCH_TESSERACT_RUNTIME", str(tesseract_source.parent)))
    for label, path in (("FFmpeg", ffmpeg_source), ("ffprobe", ffprobe_source), ("Tesseract", tesseract_source)):
        if not path.is_file():
            raise SystemExit(f"Set YOUTUBE_BATCH_{label.upper().replace('-', '')} to the installed executable path; got {path}.")

    # Preserve the already fetched upstream release executables and notices while resetting their target folder.
    fetch_manifest = TOOLS / "release-assets.json"
    fetched = json.loads(fetch_manifest.read_text(encoding="utf-8"))
    fetched_licenses = {path.name: path.read_bytes() for path in LICENSES.iterdir() if path.is_file()}
    fetched_binaries = {name: (BIN / name).read_bytes() for name in names[-2:]}
    for directory in (BIN, LIB, TESSDATA, LICENSES):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    for name, payload in fetched_binaries.items():
        (BIN / name).write_bytes(payload)
        if os.name != "nt":
            (BIN / name).chmod((BIN / name).stat().st_mode | 0o111)
    for name, payload in fetched_licenses.items():
        (LICENSES / name).write_bytes(payload)

    extension = ".exe" if os.name == "nt" else ""
    for label, source in (("ffmpeg", ffmpeg_source), ("ffprobe", ffprobe_source), ("tesseract", tesseract_source)):
        destination = BIN / f"{label}{extension}"
        shutil.copy2(source.resolve(), destination)
        if os.name != "nt":
            destination.chmod(destination.stat().st_mode | 0o111)
    copy_runtime_dlls(tesseract_runtime)
    tessdata_hashes = fetch_traineddata()
    bundle_macos_libraries()

    versions = {
        "ffmpeg": run([str(BIN / f"ffmpeg{extension}"), "-version"]).stdout.splitlines()[0],
        "ffprobe": run([str(BIN / f"ffprobe{extension}"), "-version"]).stdout.splitlines()[0],
        "yt-dlp": run([str(BIN / names[-2]), "--version"]).stdout.strip(),
        "deno": run([str(BIN / names[-1]), "--version"]).stdout.splitlines()[0],
        "tesseract": run([str(BIN / f"tesseract{extension}"), "--version"]).stdout.splitlines()[0],
    }
    expected_versions = {
        "ffmpeg": LOCK["ffmpeg"]["version"],
        "yt-dlp": LOCK["yt_dlp"]["version"],
        "deno": f"deno {LOCK['deno']['version']}",
        "tesseract": f"tesseract {LOCK['tesseract']['version']}",
    }
    actual_version_tokens = {
        "ffmpeg": versions["ffmpeg"].split()[2],
        "yt-dlp": versions["yt-dlp"],
        "deno": versions["deno"].split()[:2],
        "tesseract": " ".join(versions["tesseract"].split()[:2]),
    }
    for name, expected in expected_versions.items():
        actual = actual_version_tokens[name]
        if isinstance(actual, list):
            actual = " ".join(actual)
        if actual != expected and os.environ.get("YOUTUBE_BATCH_ALLOW_TOOL_VERSION_DRIFT") != "1":
            raise SystemExit(f"{name} version mismatch: expected {expected}; packaged {actual}.")

    manifest = {
        **fetched,
        "target": "windows-x64" if os.name == "nt" else "macos-aarch64",
        "versions": versions,
        "tessdata_revision": LOCK["tesseract"]["traineddata_revision"],
        "tessdata_sha256": tessdata_hashes,
        "files_sha256": {
            str(path.relative_to(TOOLS)): sha256(path)
            for path in sorted(TOOLS.rglob("*"))
            if path.is_file() and path.name != "release-assets.json"
        },
    }
    (TOOLS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged media runtime for {manifest['target']}: " + ", ".join(versions.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
