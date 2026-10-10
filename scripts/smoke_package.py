from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_line: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_line,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(command)}\n{detail[-2000:]}")
    return result


def main() -> int:
    tools_root = Path(sys.argv[1] if len(sys.argv) > 1 else "desktop/src-tauri/resources/tools").resolve()
    windows = os.name == "nt"
    extension = ".exe" if windows else ""
    manifest_path = tools_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Packaged tool manifest is missing or unreadable: {manifest_path}\n{error}") from error
    if not isinstance(manifest, dict) or not all(isinstance(manifest.get(key), dict) for key in ("versions", "files_sha256")):
        raise SystemExit(f"Packaged tool manifest is invalid: {manifest_path}")
    worker = tools_root / "worker" / "youtube-video-batch-worker" / f"youtube-video-batch-worker{extension}"
    tool_bin = tools_root / "bin"
    ffmpeg = tool_bin / f"ffmpeg{extension}"
    ffprobe = tool_bin / f"ffprobe{extension}"
    yt_dlp = tool_bin / f"yt-dlp{extension}"
    tesseract = tool_bin / f"tesseract{extension}"
    deno = tool_bin / f"deno{extension}"
    tessdata = tools_root / "tessdata"
    for required in (worker, ffmpeg, ffprobe, yt_dlp, deno, tesseract, tessdata / "eng.traineddata", tessdata / "vie.traineddata"):
        if not required.is_file():
            raise SystemExit(f"Required packaged file is missing: {required}")

    env = os.environ.copy()
    env.update({
        "FFMPEG_BINARY": str(ffmpeg), "FFPROBE_BINARY": str(ffprobe), "YTDLP_BINARY": str(yt_dlp),
        "TESSERACT_BINARY": str(tesseract), "TESSDATA_DIR": str(tessdata),
    })
    version = run([str(yt_dlp), "--version"], env=env).stdout.strip()
    run([str(yt_dlp), "--js-runtimes", f"deno:{deno}", "--version"], env=env)
    deno_version = run([str(deno), "--version"], env=env).stdout.splitlines()[0]
    encoder_list = run([str(ffmpeg), "-hide_banner", "-encoders"], env=env).stdout
    filter_list = run([str(ffmpeg), "-hide_banner", "-filters"], env=env).stdout
    if "libx264" not in encoder_list or " aac " not in encoder_list:
        raise SystemExit("Packaged FFmpeg must include the libx264 video encoder and AAC audio encoder.")
    if " subtitles " not in filter_list:
        raise SystemExit("Packaged FFmpeg is missing the subtitles/libass filter.")
    languages = run([str(tesseract), "--tessdata-dir", str(tessdata), "--list-langs"], env=env).stdout
    if "eng" not in languages.split():
        raise SystemExit("Packaged Tesseract cannot find the required English OCR model.")

    with tempfile.TemporaryDirectory(prefix="youtube-batch-smoke-") as temporary:
        work = Path(temporary)
        (work / "captions.srt").write_text("1\n00:00:00,100 --> 00:00:00,900\nLOCAL SMOKE TEST\n", encoding="utf-8")
        command = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x263a31:s=320x180:r=24:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-vf", "subtitles=captions.srt", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "smoke.mp4",
        ]
        run(command, cwd=work, env=env)
        run([str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "json", "smoke.mp4"], cwd=work, env=env)
        health = run([str(worker), "--db-path", str(work / "smoke.sqlite3")], cwd=work, env=env, input_line='{"id":"smoke","method":"health","params":{}}\n')
        response = json.loads(health.stdout)
        if response.get("ok") is not True or response.get("result", {}).get("status") != "ready":
            raise SystemExit("The packaged Python worker failed its health request.")
        if not (work / "smoke.mp4").is_file() or (work / "smoke.mp4").stat().st_size == 0:
            raise SystemExit("The packaged FFmpeg smoke render did not create an MP4.")
        probe = json.loads(run([
            str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", "smoke.mp4"
        ], cwd=work, env=env).stdout)
        video = next((stream for stream in probe["streams"] if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in probe["streams"] if stream.get("codec_type") == "audio"), None)
        if not video or (video.get("codec_name"), video.get("width"), video.get("height")) != ("h264", 320, 180):
            raise SystemExit("Packaged FFmpeg smoke output is not a 320×180 H.264 video stream.")
        if not audio or audio.get("codec_name") != "aac":
            raise SystemExit("Packaged FFmpeg smoke output is missing its AAC audio stream.")

        sample = work / "ocr-sample.png"
        canvas = Image.new("RGB", (520, 120), "white")
        ImageDraw.Draw(canvas).text((12, 36), "YOUTUBE TOOL SMOKE", fill="black", font=ImageFont.load_default(size=34))
        canvas.save(sample)
        ocr = run([
            str(tesseract), "--tessdata-dir", str(tessdata), str(sample), "stdout",
            "--oem", "1", "--psm", "6", "-l", "eng",
        ], env=env).stdout.upper()
        if "SMOKE" not in ocr:
            raise SystemExit(f"Packaged Tesseract did not recognize its local fixture: {ocr.strip()!r}")
    print(f"Package smoke passed. yt-dlp {version}; {deno_version}; worker starts; H.264/AAC + libass render and OCR fixture passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
