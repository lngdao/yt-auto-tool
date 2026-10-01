from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"
DIST_DIR = ROOT / "desktop" / "src-tauri" / "resources" / "tools" / "worker"
WORK_DIR = ROOT / "worker" / "build" / "pyinstaller"


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir",
        "--name", "youtube-video-batch-worker", "--distpath", str(DIST_DIR),
        "--workpath", str(WORK_DIR), "--specpath", str(WORK_DIR), str(WORKER_DIR / "worker.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True, env=os.environ.copy())
    executable = "youtube-video-batch-worker.exe" if os.name == "nt" else "youtube-video-batch-worker"
    packaged_worker = DIST_DIR / "youtube-video-batch-worker" / executable
    if not packaged_worker.is_file():
        raise SystemExit(f"PyInstaller completed without the expected worker at {packaged_worker}")
    print(f"Built packaged worker: {packaged_worker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
