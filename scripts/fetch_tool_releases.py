from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "scripts" / "toolchain-lock.json").read_text(encoding="utf-8"))
TOOLS = ROOT / "desktop" / "src-tauri" / "resources" / "tools"
BIN = TOOLS / "bin"
LICENSES = TOOLS / "licenses"
USER_AGENT = "youtube-video-batch-tool-packager"


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_json(url: str) -> dict:
    return json.loads(fetch_bytes(url))


def download_verified_asset(repository: str, version: str, asset_name: str, destination: Path) -> tuple[str, str]:
    release = fetch_json(f"https://api.github.com/repos/{repository}/releases/tags/{version}")
    asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
    if asset is None:
        raise SystemExit(f"The pinned release {repository}@{version} has no asset named {asset_name}.")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise SystemExit(f"GitHub did not provide a SHA-256 digest for {repository}@{version}/{asset_name}.")
    payload = fetch_bytes(asset["browser_download_url"])
    actual = hashlib.sha256(payload).hexdigest()
    expected = digest.removeprefix("sha256:").lower()
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch for {asset_name}: expected {expected}, received {actual}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return actual, asset["browser_download_url"]


def download_text(url: str, destination: Path) -> str:
    payload = fetch_bytes(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    BIN.mkdir(parents=True, exist_ok=True)
    LICENSES.mkdir(parents=True, exist_ok=True)
    windows = os.name == "nt"
    if windows:
        if platform.machine().lower() not in {"amd64", "x86_64"}:
            raise SystemExit("The Windows package target is x64; use an AMD64 runner.")
        ytdlp_asset, deno_asset = "yt-dlp.exe", "deno-x86_64-pc-windows-msvc.zip"
        ytdlp_name, deno_name = "yt-dlp.exe", "deno.exe"
    elif platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        ytdlp_asset, deno_asset = "yt-dlp_macos", "deno-aarch64-apple-darwin.zip"
        ytdlp_name, deno_name = "yt-dlp", "deno"
    else:
        raise SystemExit("Release packaging supports Windows x64 and macOS Apple Silicon only.")

    target = "windows-x64" if windows else "macos-aarch64"
    manifest = {"target": target, "tools": {}}
    ytdlp_version = LOCK["yt_dlp"]["version"]
    ytdlp_path = BIN / ytdlp_name
    ytdlp_hash, ytdlp_url = download_verified_asset(
        LOCK["yt_dlp"]["repository"], ytdlp_version, ytdlp_asset, ytdlp_path
    )
    manifest["tools"]["yt-dlp"] = {
        "version": ytdlp_version,
        "asset": ytdlp_asset,
        "url": ytdlp_url,
        "sha256": ytdlp_hash,
    }

    deno_version = LOCK["deno"]["version"]
    deno_archive = ROOT / "worker" / "build" / f"deno-{deno_version}.zip"
    deno_hash, deno_url = download_verified_asset(
        LOCK["deno"]["repository"], f"v{deno_version}", deno_asset, deno_archive
    )
    with zipfile.ZipFile(deno_archive) as archive:
        expected = "deno.exe" if windows else "deno"
        matches = [name for name in archive.namelist() if Path(name).name == expected]
        if len(matches) != 1:
            raise SystemExit(f"Deno release archive should contain one {expected}; found {len(matches)}.")
        destination = BIN / deno_name
        destination.write_bytes(archive.read(matches[0]))
    if not windows:
        ytdlp_path.chmod(ytdlp_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        (BIN / deno_name).chmod((BIN / deno_name).stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    manifest["tools"]["deno"] = {
        "version": deno_version,
        "asset": deno_asset,
        "url": deno_url,
        "sha256": deno_hash,
    }

    raw_root = "https://raw.githubusercontent.com"
    ytdlp_license = LICENSES / "yt-dlp-THIRD_PARTY_LICENSES.txt"
    manifest["licenses"] = {
        "yt-dlp-third-party": download_text(
            f"{raw_root}/yt-dlp/yt-dlp/{ytdlp_version}/THIRD_PARTY_LICENSES.txt", ytdlp_license
        ),
        "Deno": download_text(
            f"{raw_root}/denoland/deno/v{deno_version}/LICENSE.md", LICENSES / "deno-LICENSE.md"
        ),
        "FFmpeg-GPLv2": download_text(
            f"{raw_root}/FFmpeg/FFmpeg/n{LOCK['ffmpeg']['version']}/COPYING.GPLv2",
            LICENSES / "FFmpeg-COPYING.GPLv2",
        ),
        "Tesseract": download_text(
            f"{raw_root}/tesseract-ocr/tesseract/{LOCK['tesseract']['version']}/LICENSE",
            LICENSES / "Tesseract-LICENSE",
        ),
    }
    (TOOLS / "release-assets.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Fetched verified yt-dlp {ytdlp_version} and Deno {deno_version} for {manifest['target']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
