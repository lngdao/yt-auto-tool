import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_ENTRY = PROJECT_ROOT / "worker" / "worker.py"


class WorkerApiBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "app.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(self, method: str, params: dict | None = None, env: dict[str, str] | None = None) -> dict:
        payload = json.dumps({"id": "test-request", "method": method, "params": params or {}})
        environment = os.environ.copy()
        if env:
            environment.update(env)
        completed = subprocess.run(
            [sys.executable, str(WORKER_ENTRY), "--db-path", str(self.database)],
            input=payload + "\n",
            capture_output=True,
            text=True,
            check=False,
            cwd=PROJECT_ROOT,
            timeout=10,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout.strip())

    def add_backgrounds(self, channel_id: str, count: int) -> list[dict]:
        assets = []
        for index in range(count):
            path = self.root / f"background-{index}.mp4"
            path.write_bytes(b"fixture")
            assets.append(
                self.request(
                    "backgrounds.add_to_channel",
                    {"channel_id": channel_id, "path": str(path)},
                )["result"]
            )
        return assets

    def metadata_tool(self) -> Path:
        script = self.root / "fake-yt-dlp"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys, time\n"
            "with open(os.environ['YTDLP_ARGS_LOG'], 'a') as output:\n"
            "    output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "url = sys.argv[-1]\n"
            "video_id = url.rsplit('=', 1)[-1]\n"
            "if '--dump-single-json' in sys.argv:\n"
            "    metadata = {'id': video_id, 'title': 'Fixture ' + video_id, 'duration': 123.5, 'thumbnail': 'https://example.test/' + video_id + '.jpg'}\n"
            "    metadata.update(json.loads(os.environ.get('FAKE_SUBTITLE_METADATA', '{}')))\n"
            "    print(json.dumps(metadata))\n"
            "    raise SystemExit(0)\n"
            "template = sys.argv[sys.argv.index('--output') + 1]\n"
            "destination = pathlib.Path(template.split('%(ext)s')[0]).parent\n"
            "destination.mkdir(parents=True, exist_ok=True)\n"
            "time.sleep(float(os.environ.get('FAKE_YTDLP_SLEEP', '0')))\n"
            "if '--write-subs' in sys.argv or '--write-auto-subs' in sys.argv:\n"
            "    language = sys.argv[sys.argv.index('--sub-langs') + 1]\n"
            "    (destination / ('subtitle.' + language + '.vtt')).write_text('WEBVTT\\n\\n00:00:01.000 --> 00:00:02.000\\nhello\\n')\n"
            "else:\n"
            "    extension = 'mp4' if '--merge-output-format' in sys.argv else 'mp3'\n"
            "    fixture = os.environ.get('FAKE_SOURCE_FIXTURE')\n"
            "    if fixture:\n"
            "        import shutil\n"
            "        extension = pathlib.Path(fixture).suffix.lstrip('.') or extension\n"
            "        shutil.copyfile(fixture, destination / ('source.' + extension))\n"
            "    else:\n"
            "        (destination / ('source.' + extension)).write_bytes(b'fixture source')\n"
            "if '--write-thumbnail' in sys.argv:\n"
            "    fixture_thumbnail = os.environ.get('FAKE_THUMBNAIL_FIXTURE')\n"
            "    if fixture_thumbnail:\n"
            "        import shutil\n"
            "        shutil.copyfile(fixture_thumbnail, destination / 'source.jpg')\n"
            "    else:\n"
            "        (destination / 'source.jpg').write_bytes(b'fixture thumbnail')\n"
        )
        script.chmod(0o755)
        return script

    def lookup_batch_metadata(self, batch_id: str, subtitle_metadata: dict | None = None) -> list[dict]:
        argument_log = self.root / "yt-dlp-arguments.jsonl"
        env = {"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(argument_log)}
        if subtitle_metadata is not None:
            env["FAKE_SUBTITLE_METADATA"] = json.dumps(subtitle_metadata)
        result = self.request(
            "batches.lookup_metadata",
            {"batch_id": batch_id},
            env=env,
        )["result"]
        self.metadata_arguments = json.loads(argument_log.read_text().splitlines()[-1])
        return result

    def create_confirmed_job(
        self,
        video_id: str,
        preferences: list[str],
        subtitle_metadata: dict | None = None,
        background_path: Path | None = None,
    ):
        channel = self.request("channels.create", {"name": f"Channel {video_id}"})["result"]
        self.request(
            "channels.set_subtitle_languages",
            {"channel_id": channel["id"], "languages": preferences},
        )
        if background_path:
            self.request("backgrounds.add_to_channel", {"channel_id": channel["id"], "path": str(background_path)})
        else:
            self.add_backgrounds(channel["id"], 1)
        imported = self.request(
            "batches.import_text",
            {"name": f"Batch {video_id}", "channel_id": channel["id"], "content": f"https://youtu.be/{video_id}"},
        )["result"]
        self.lookup_batch_metadata(imported["batch"]["id"], subtitle_metadata)
        confirmed = self.request("batches.confirm", {"batch_id": imported["batch"]["id"]})["result"]
        return channel, confirmed["batch"], confirmed["jobs"][0]

    def make_ffmpeg_fixtures(self, width: int = 160, height: int = 90, frame_rate: int = 24):
        ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
        ffprobe = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            self.skipTest("ffmpeg and ffprobe are required for render fixture tests")
        background = self.root / f"background-{width}x{height}.mp4"
        audio = self.root / "source-audio.wav"
        video_result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             f"color=c=0x202830:s={width}x{height}:r={frame_rate}:d=1.25", "-an", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", str(background)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        audio_result = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=48000:duration=1.1", "-ac", "2", str(audio)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(video_result.returncode, 0, video_result.stderr)
        self.assertEqual(audio_result.returncode, 0, audio_result.stderr)
        return background, audio

    def wait_for_queue_state(self, batch_id: str, task_id: str, states: set[str], timeout: float = 25) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.request("queue.status", {"batch_id": batch_id})["result"]
            task = next((item for item in result["tasks"] if item["id"] == task_id), None)
            self.assertIsNotNone(task, f"queue task {task_id} disappeared")
            if task["state"] in states:
                return task
            time.sleep(0.12)
        self.fail(f"Queue task {task_id} did not reach any of {sorted(states)} before timeout")

    def test_health_reports_worker_ready(self) -> None:
        response = self.request("health")

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["status"], "ready")

    def test_thumbnail_ocr_uses_source_image_text_and_exports_separate_png(self) -> None:
        from PIL import Image

        channel = self.request("channels.create", {"name": "Thumbnail OCR"})["result"]
        self.add_backgrounds(channel["id"], 1)
        source_image = self.root / "original-thumbnail.jpg"
        Image.new("RGB", (320, 180), "#263a31").save(source_image, format="JPEG")
        ocr = self.root / "fake-tesseract"
        ocr.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--list-langs' in sys.argv:\n"
            " print('List of available languages (1):\\neng')\n"
            "else:\n"
            " print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext')\n"
            " print('5\\t1\\t1\\t1\\t1\\t1\\t1\\t1\\t90\\t30\\t94\\tSOURCE_WORDS')\n"
        )
        ocr.chmod(0o755)
        batch = self.request(
            "batches.import_text",
            {"name": "Thumbnail OCR run", "channel_id": channel["id"], "content": "https://youtu.be/thumb123456"},
        )["result"]
        self.lookup_batch_metadata(batch["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": batch["batch"]["id"]})["result"]
        job = confirmed["jobs"][0]
        fake_ytdlp = self.metadata_tool()
        args_log = self.root / "download-args.jsonl"
        downloaded = self.request(
            "jobs.download_sources",
            {"batch_id": batch["batch"]["id"], "job_id": job["id"], "output_dir": str(self.root / "downloads")},
            env={
                "YTDLP_BINARY": str(fake_ytdlp),
                "YTDLP_ARGS_LOG": str(args_log),
                "FAKE_THUMBNAIL_FIXTURE": str(source_image),
                "TESSERACT_BINARY": str(ocr),
            },
        )["result"]

        self.assertEqual(downloaded["thumbnail_ocr_text"], "SOURCE_WORDS")
        self.assertEqual(downloaded["thumbnail_text"], "SOURCE_WORDS")
        self.assertEqual(downloaded["thumbnail_ocr_status"], "awaiting_confirmation")
        self.assertEqual(Path(downloaded["source_thumbnail_path"]).read_bytes(), source_image.read_bytes())
        self.assertIn("Fixture thumb123456", downloaded["title"])

        rendered = self.request("jobs.render_thumbnail", {"job_id": job["id"], "text": "EDITED WORDS"})["result"]
        self.assertEqual(rendered["thumbnail_text"], "EDITED WORDS")
        self.assertEqual(rendered["thumbnail_ocr_status"], "complete")
        self.assertTrue(rendered["thumbnail_output_path"].endswith("thumbnail.png"))
        self.assertNotEqual(Path(rendered["thumbnail_output_path"]).read_bytes(), source_image.read_bytes())
        with Image.open(rendered["thumbnail_output_path"]) as image:
            self.assertEqual(image.size, (1280, 720))
        self.assertEqual(Path(rendered["source_thumbnail_path"]).read_bytes(), source_image.read_bytes())

    def test_thumbnail_preset_pool_balances_and_continues_across_batches(self) -> None:
        channel = self.request("channels.create", {"name": "Thumbnail rotation"})["result"]
        self.add_backgrounds(channel["id"], 1)
        presets = []
        for index in range(3):
            preset = self.request(
                "thumbnail.presets.create",
                {"name": f"Shared style {index + 1}", "style": {"background_type": "solid", "background_color": f"#{index + 1:06X}"}},
            )["result"]
            presets.append(preset)
        for preset in presets:
            self.request("channels.add_thumbnail_preset", {"channel_id": channel["id"], "preset_id": preset["id"]})

        first = self.request(
            "batches.import_text",
            {"name": "Thumbnail styles first run", "channel_id": channel["id"], "content": "\n".join(f"https://youtu.be/style{i:06d}" for i in range(7))},
        )["result"]
        first_ids = [job["thumbnail_preset_id"] for job in first["jobs"]]
        self.assertLessEqual(max(first_ids.count(preset_id) for preset_id in set(first_ids)) - min(first_ids.count(preset_id) for preset_id in set(first_ids)), 1)
        self.assertTrue(all(first_ids[index] != first_ids[index - 1] for index in range(1, len(first_ids))))
        self.lookup_batch_metadata(first["batch"]["id"])
        self.request("batches.confirm", {"batch_id": first["batch"]["id"]})

        second = self.request(
            "batches.import_text",
            {"name": "Thumbnail styles second run", "channel_id": channel["id"], "content": "\n".join(f"https://youtu.be/next{i:07d}" for i in range(4))},
        )["result"]
        self.assertTrue(all(second["jobs"][index]["thumbnail_preset_id"] != second["jobs"][index - 1]["thumbnail_preset_id"] for index in range(1, len(second["jobs"]))))
        self.assertNotEqual(second["jobs"][0]["thumbnail_preset_id"], first_ids[-1])

    def test_manual_thumbnail_mode_saves_original_without_running_ocr(self) -> None:
        channel = self.request("channels.create", {"name": "Manual thumbnails"})["result"]
        self.request("channels.set_thumbnail_settings", {"channel_id": channel["id"], "mode": "manual", "languages": ["eng"]})
        self.add_backgrounds(channel["id"], 1)
        batch = self.request(
            "batches.import_text",
            {"name": "Manual thumbnail", "channel_id": channel["id"], "content": "https://youtu.be/manual12345"},
        )["result"]
        self.lookup_batch_metadata(batch["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": batch["batch"]["id"]})["result"]
        downloaded = self.request(
            "jobs.download_sources",
            {"batch_id": batch["batch"]["id"], "job_id": confirmed["jobs"][0]["id"], "output_dir": str(self.root / "downloads")},
            env={"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(self.root / "manual-args.jsonl"), "TESSERACT_BINARY": str(self.root / "missing-tesseract")},
        )["result"]

        self.assertEqual(downloaded["thumbnail_mode"], "manual")
        self.assertEqual(downloaded["thumbnail_ocr_status"], "manual")
        self.assertTrue(Path(downloaded["source_thumbnail_path"]).is_file())
        self.assertIsNone(downloaded["thumbnail_output_path"])

    def test_low_confidence_thumbnail_review_does_not_block_video_render(self) -> None:
        from PIL import Image

        background, audio = self.make_ffmpeg_fixtures()
        _, batch, job = self.create_confirmed_job("review12345", ["en"], background_path=background)
        source_image = self.root / "low-confidence.jpg"
        Image.new("RGB", (320, 180), "#324638").save(source_image, format="JPEG")
        ocr = self.root / "low-confidence-tesseract"
        ocr.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--list-langs' in sys.argv:\n"
            " print('List of available languages (1):\\neng')\n"
            "else:\n"
            " print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext')\n"
            " print('5\\t1\\t1\\t1\\t1\\t1\\t1\\t1\\t90\\t30\\t18\\tUNCERTAIN')\n"
        )
        ocr.chmod(0o755)
        downloaded = self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(self.root / "review-downloads")},
            env={
                "YTDLP_BINARY": str(self.metadata_tool()),
                "YTDLP_ARGS_LOG": str(self.root / "review-args.jsonl"),
                "FAKE_SOURCE_FIXTURE": str(audio),
                "FAKE_THUMBNAIL_FIXTURE": str(source_image),
                "TESSERACT_BINARY": str(ocr),
            },
        )["result"]
        self.assertEqual(downloaded["thumbnail_ocr_status"], "needs_review")
        self.assertEqual(downloaded["thumbnail_text"], "UNCERTAIN")
        self.request("jobs.skip_captions", {"job_id": job["id"]})

        rendered = self.request("jobs.render_video", {"batch_id": batch["id"], "job_id": job["id"]})["result"]

        self.assertEqual(rendered["render_status"], "complete", rendered["render_error"])
        self.assertEqual(rendered["thumbnail_ocr_status"], "needs_review")

    def test_skip_thumbnail_mode_does_not_download_or_process_a_thumbnail(self) -> None:
        channel = self.request("channels.create", {"name": "No thumbnail"})["result"]
        self.request("channels.set_thumbnail_settings", {"channel_id": channel["id"], "mode": "skip", "languages": ["eng"]})
        self.add_backgrounds(channel["id"], 1)
        batch = self.request(
            "batches.import_text",
            {"name": "Skip thumbnails", "channel_id": channel["id"], "content": "https://youtu.be/skip1234567"},
        )["result"]
        self.lookup_batch_metadata(batch["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": batch["batch"]["id"]})["result"]
        args_log = self.root / "skip-args.jsonl"
        downloaded = self.request(
            "jobs.download_sources",
            {"batch_id": batch["batch"]["id"], "job_id": confirmed["jobs"][0]["id"], "output_dir": str(self.root / "downloads")},
            env={"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(args_log)},
        )["result"]
        arguments = json.loads(args_log.read_text().splitlines()[0])

        self.assertIsNone(downloaded["source_thumbnail_path"])
        self.assertEqual(downloaded["thumbnail_ocr_status"], "skipped")
        self.assertNotIn("--write-thumbnail", arguments)

    def test_first_worker_requests_can_initialize_a_fresh_database_concurrently(self) -> None:
        payload = json.dumps({"id": "parallel-health", "method": "health", "params": {}}) + "\n"

        def request_health() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(WORKER_ENTRY), "--db-path", str(self.database)],
                input=payload,
                capture_output=True,
                text=True,
                check=False,
                cwd=PROJECT_ROOT,
                timeout=10,
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: request_health(), range(6)))

        for response in responses:
            self.assertEqual(response.returncode, 0, response.stderr)
            decoded = json.loads(response.stdout)
            self.assertTrue(decoded["ok"], decoded)
            self.assertEqual(decoded["result"]["status"], "ready")

    def test_existing_channel_database_is_migrated_with_empty_subtitle_preferences(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE channels(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO channels(id, name, slug, active, created_at, updated_at)
            VALUES ('legacy-channel', 'Legacy', 'legacy', 1, 'now', 'now');
            """
        )
        connection.commit()
        connection.close()

        channels = self.request("channels.list")["result"]

        self.assertEqual(channels[0]["id"], "legacy-channel")
        self.assertEqual(channels[0]["subtitle_languages"], [])

    def test_channel_can_be_created_and_retrieved_after_worker_restart(self) -> None:
        created = self.request("channels.create", {"name": "Kênh Đêm"})
        channel = created["result"]

        self.assertEqual(channel["name"], "Kênh Đêm")
        self.assertEqual(channel["slug"], "kenh-dem")

        listed = self.request("channels.list")
        self.assertEqual(len(listed["result"]), 1)
        self.assertEqual(listed["result"][0]["id"], channel["id"])

    def test_channel_can_be_edited_hidden_and_reactivated(self) -> None:
        channel = self.request("channels.create", {"name": "Góc Bình Yên"})["result"]
        updated = self.request(
            "channels.update",
            {"channel_id": channel["id"], "name": "Góc Bình Yên Mới"},
        )["result"]
        hidden = self.request(
            "channels.set_active",
            {"channel_id": channel["id"], "active": False},
        )["result"]
        reactivated = self.request(
            "channels.set_active",
            {"channel_id": channel["id"], "active": True},
        )["result"]

        self.assertEqual(updated["name"], "Góc Bình Yên Mới")
        self.assertFalse(hidden["active"])
        self.assertTrue(reactivated["active"])

    def test_channel_can_be_duplicated_with_its_background_pool(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Gốc"})["result"]
        background = self.root / "background.mp4"
        background.write_bytes(b"fixture")
        self.request(
            "backgrounds.add_to_channel",
            {"channel_id": channel["id"], "path": str(background)},
        )

        duplicate = self.request(
            "channels.duplicate",
            {"channel_id": channel["id"], "name": "Kênh Bản Sao"},
        )["result"]
        backgrounds = self.request(
            "backgrounds.list",
            {"channel_id": duplicate["id"]},
        )["result"]

        self.assertEqual(duplicate["name"], "Kênh Bản Sao")
        self.assertNotEqual(duplicate["id"], channel["id"])
        self.assertEqual(len(backgrounds), 1)
        self.assertEqual(backgrounds[0]["path"], str(background.resolve()))

    def test_background_asset_is_reusable_by_multiple_channels(self) -> None:
        first = self.request("channels.create", {"name": "Kênh Một"})["result"]
        second = self.request("channels.create", {"name": "Kênh Hai"})["result"]
        background = self.root / "shared-background.mp4"
        background.write_bytes(b"fixture")

        first_result = self.request(
            "backgrounds.add_to_channel",
            {"channel_id": first["id"], "path": str(background)},
        )["result"]
        second_result = self.request(
            "backgrounds.add_to_channel",
            {"channel_id": second["id"], "path": str(background)},
        )["result"]

        self.assertEqual(first_result["id"], second_result["id"])
        first_assets = self.request("backgrounds.list", {"channel_id": first["id"]})["result"]
        second_assets = self.request("backgrounds.list", {"channel_id": second["id"]})["result"]
        self.assertEqual(first_assets[0]["path"], str(background.resolve()))
        self.assertEqual(second_assets[0]["path"], str(background.resolve()))

    def test_existing_background_can_be_assigned_and_removed_from_a_channel(self) -> None:
        first = self.request("channels.create", {"name": "Kênh Nguồn"})["result"]
        second = self.request("channels.create", {"name": "Kênh Đích"})["result"]
        background = self.root / "reusable.mp4"
        background.write_bytes(b"fixture")
        asset = self.request(
            "backgrounds.add_to_channel",
            {"channel_id": first["id"], "path": str(background)},
        )["result"]

        library = self.request("backgrounds.library")["result"]
        self.assertEqual(len(library), 1)
        self.assertEqual(library[0]["id"], asset["id"])

        assigned = self.request(
            "backgrounds.assign_to_channel",
            {"channel_id": second["id"], "asset_id": asset["id"]},
        )
        self.assertTrue(assigned["ok"])
        self.assertEqual(
            self.request("backgrounds.list", {"channel_id": second["id"]})["result"][0]["id"],
            asset["id"],
        )

        removed = self.request(
            "backgrounds.remove_from_channel",
            {"channel_id": second["id"], "asset_id": asset["id"]},
        )
        self.assertTrue(removed["ok"])
        self.assertEqual(self.request("backgrounds.list", {"channel_id": second["id"]})["result"], [])
        self.assertEqual(len(self.request("backgrounds.library")["result"]), 1)

    def test_missing_background_can_be_relinked_without_changing_its_asset_id(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Relink"})["result"]
        original = self.root / "old-location.mp4"
        original.write_bytes(b"fixture")
        asset = self.request(
            "backgrounds.add_to_channel",
            {"channel_id": channel["id"], "path": str(original)},
        )["result"]
        original.unlink()
        replacement = self.root / "new-location.mp4"
        replacement.write_bytes(b"new fixture")

        relinked = self.request(
            "backgrounds.relink_asset",
            {"asset_id": asset["id"], "path": str(replacement)},
        )["result"]
        assigned = self.request("backgrounds.list", {"channel_id": channel["id"]})["result"]

        self.assertEqual(relinked["id"], asset["id"])
        self.assertEqual(relinked["path"], str(replacement.resolve()))
        self.assertTrue(relinked["available"])
        self.assertEqual(assigned[0]["id"], asset["id"])
        self.assertTrue(assigned[0]["available"])

    def test_batch_import_flags_invalid_duplicate_and_unknown_channel_rows(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Import"})["result"]
        self.add_backgrounds(channel["id"], 1)
        pasted = self.request(
            "batches.import_text",
            {
                "name": "Pasted URLs",
                "channel_id": channel["id"],
                "content": "https://youtu.be/abcdefghijk\nnot a youtube url\nhttps://youtube.com/watch?v=abcdefghijk",
            },
        )["result"]
        states = [job["readiness"] for job in pasted["jobs"]]
        self.assertEqual(states, ["needs_metadata", "invalid_url", "duplicate_url"])

        table = self.request(
            "batches.import_text",
            {
                "name": "CSV import",
                "content": "Channel,URL\nKênh Import,https://youtu.be/lmnopqrstuv\nMissing Channel,https://youtu.be/wxyzabcdefg\nKênh Import,https://example.com/nope",
            },
        )["result"]
        self.assertEqual(table["jobs"][0]["channel_id"], channel["id"])
        self.assertEqual(table["jobs"][1]["readiness"], "unknown_channel")
        self.assertEqual(table["jobs"][2]["readiness"], "invalid_url")

    def test_batch_metadata_lookup_uses_yt_dlp_adapter_without_downloading_video(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Metadata"})["result"]
        self.add_backgrounds(channel["id"], 1)
        batch = self.request(
            "batches.import_text",
            {"name": "Lookup", "channel_id": channel["id"], "content": "https://youtu.be/abcdefghijk"},
        )["result"]["batch"]

        looked_up = self.lookup_batch_metadata(batch["id"])

        self.assertEqual(looked_up[0]["video_id"], "abcdefghijk")
        self.assertEqual(looked_up[0]["title"], "Fixture abcdefghijk")
        self.assertEqual(looked_up[0]["duration_seconds"], 123.5)
        self.assertTrue(looked_up[0]["thumbnail_url"].endswith("abcdefghijk.jpg"))
        self.assertEqual(looked_up[0]["metadata_status"], "ready")
        self.assertIn("--skip-download", self.metadata_arguments)
        self.assertIn("--dump-single-json", self.metadata_arguments)
        self.assertNotIn("-f", self.metadata_arguments)

    def test_balanced_background_assignments_continue_across_batches_and_stay_confirmed(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Cân Bằng"})["result"]
        assets = self.add_backgrounds(channel["id"], 3)
        first = self.request(
            "batches.import_text",
            {
                "name": "First",
                "channel_id": channel["id"],
                "content": "\n".join(f"https://youtu.be/{index:011d}" for index in range(1, 7)),
            },
        )["result"]["batch"]
        self.lookup_batch_metadata(first["id"])
        first_confirmed = self.request("batches.confirm", {"batch_id": first["id"]})["result"]
        first_jobs = first_confirmed["jobs"]
        first_counts = {asset["id"]: 0 for asset in assets}
        for job in first_jobs:
            first_counts[job["background_asset_id"]] += 1
        self.assertEqual(sorted(first_counts.values()), [2, 2, 2])
        self.assertTrue(all(a["background_asset_id"] != b["background_asset_id"] for a, b in zip(first_jobs, first_jobs[1:])))

        second = self.request(
            "batches.import_text",
            {"name": "Second", "channel_id": channel["id"], "content": "\n".join(f"https://youtu.be/{index:011d}" for index in range(7, 10))},
        )["result"]["batch"]
        self.lookup_batch_metadata(second["id"])
        second_jobs = self.request("batches.confirm", {"batch_id": second["id"]})["result"]["jobs"]
        total_counts = first_counts.copy()
        for job in second_jobs:
            total_counts[job["background_asset_id"]] += 1
        self.assertLessEqual(max(total_counts.values()) - min(total_counts.values()), 1)

        reopened = self.request("batches.get", {"batch_id": second["id"]})["result"]
        self.assertEqual(
            [job["background_asset_id"] for job in reopened["jobs"]],
            [job["background_asset_id"] for job in second_jobs],
        )

    def test_manual_background_override_survives_rebalance(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Override"})["result"]
        assets = self.add_backgrounds(channel["id"], 2)
        imported = self.request(
            "batches.import_text",
            {"name": "Override", "channel_id": channel["id"], "content": "\n".join(f"https://youtu.be/{index:011d}" for index in range(11, 15))},
        )["result"]
        batch = imported["batch"]
        self.lookup_batch_metadata(batch["id"])
        jobs = imported["jobs"]
        override = self.request(
            "batches.override_background",
            {"batch_id": batch["id"], "job_id": jobs[0]["id"], "asset_id": assets[1]["id"]},
        )
        self.assertTrue(override["ok"])
        rebalanced = self.request("batches.rebalance_backgrounds", {"batch_id": batch["id"]})["result"]["jobs"]
        self.assertEqual(rebalanced[0]["background_asset_id"], assets[1]["id"])
        self.assertTrue(rebalanced[0]["background_locked"])
        self.assertEqual(
            sum(1 for job in rebalanced if job["background_asset_id"] == assets[0]["id"]),
            2,
        )

    def test_unknown_channels_invalid_urls_and_appended_rows_can_be_corrected(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Chỉnh Sửa"})["result"]
        self.add_backgrounds(channel["id"], 2)
        imported = self.request(
            "batches.import_text",
            {
                "name": "Corrections",
                "content": "Channel,URL\nKênh Chỉnh Sửa,https://youtu.be/abcdefghijk\nWrong channel,https://youtu.be/lmnopqrstuv\nKênh Chỉnh Sửa,not a video URL",
            },
        )["result"]
        batch_id = imported["batch"]["id"]
        unknown_job = imported["jobs"][1]
        invalid_job = imported["jobs"][2]
        self.assertEqual(unknown_job["readiness"], "unknown_channel")
        self.assertEqual(invalid_job["readiness"], "invalid_url")

        corrected_channel = self.request(
            "batches.update_job",
            {"batch_id": batch_id, "job_id": unknown_job["id"], "channel_id": channel["id"]},
        )["result"]
        self.assertEqual(corrected_channel["channel_id"], channel["id"])
        corrected_url = self.request(
            "batches.update_job",
            {"batch_id": batch_id, "job_id": invalid_job["id"], "url": "https://youtu.be/wxyzabcdefg"},
        )["result"]
        self.assertEqual(corrected_url["channel_id"], channel["id"])
        self.assertEqual(corrected_url["readiness"], "needs_metadata")

        self.lookup_batch_metadata(batch_id)
        appended = self.request(
            "batches.append_text",
            {"batch_id": batch_id, "channel_id": channel["id"], "content": "https://youtu.be/123456789ab"},
        )["result"]
        self.assertEqual(len(appended["jobs"]), 4)
        self.lookup_batch_metadata(batch_id)
        confirmed = self.request("batches.confirm", {"batch_id": batch_id})["result"]
        self.assertEqual(confirmed["batch"]["state"], "confirmed")
        self.assertEqual(confirmed["batch"]["ready_count"], 4)

    def test_subtitle_selection_obeys_channel_order_and_job_override(self) -> None:
        tracks = {
            "subtitles": {
                "en-GB": [{"ext": "vtt", "name": "English"}],
                "vi": [{"ext": "srt", "name": "Vietnamese"}],
            },
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
                "vi": [{"ext": "json3"}],
                "fr": [{"ext": "vtt"}],
            },
        }
        channel, batch, job = self.create_confirmed_job("abcde123456", ["en", "vi"], tracks)

        selected = self.request("jobs.inspect_subtitles", {"job_id": job["id"]})["result"]
        self.assertEqual(selected["selected"], {"language": "en-GB", "source": "creator", "decision": "youtube"})

        override = self.request(
            "jobs.set_subtitle_language_override",
            {"job_id": job["id"], "languages": ["fr", "vi"]},
        )["result"]
        self.assertEqual(override["preferences"], ["fr", "vi"])
        self.assertEqual(override["selected"], {"language": "fr", "source": "automatic", "decision": "youtube"})

        second_override = self.request(
            "jobs.set_subtitle_language_override",
            {"job_id": job["id"], "languages": ["vi"]},
        )["result"]
        self.assertEqual(second_override["selected"], {"language": "vi", "source": "creator", "decision": "youtube"})
        persisted_channel = self.request("channels.list")["result"]
        persisted = next(item for item in persisted_channel if item["id"] == channel["id"])
        self.assertEqual(persisted["subtitle_languages"], ["en", "vi"])

    def test_supplied_subtitle_is_only_used_when_no_preferred_youtube_track_exists(self) -> None:
        tracks = {"subtitles": {"en": [{"ext": "vtt"}]}, "automatic_captions": {}}
        channel, _, job = self.create_confirmed_job("fghij123456", ["en"], tracks)
        supplied = self.root / "captions.srt"
        supplied.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")

        matching = self.request(
            "jobs.attach_subtitle_file",
            {"job_id": job["id"], "path": str(supplied)},
        )["result"]
        self.assertEqual(matching["selected"]["source"], "creator")
        self.assertIsNone(matching["job"]["supplied_subtitle_path"])

        self.request("jobs.set_subtitle_language_override", {"job_id": job["id"], "languages": ["de"]})
        fallback = self.request(
            "jobs.attach_subtitle_file",
            {"job_id": job["id"], "path": str(supplied)},
        )["result"]
        self.assertEqual(fallback["selected"], {"language": "de", "source": "supplied_file", "decision": "use_file"})
        skipped = self.request("jobs.skip_captions", {"job_id": job["id"]})["result"]
        self.assertEqual(skipped["selected"]["decision"], "skip")
        self.assertEqual(skipped["job"]["channel_id"], channel["id"])

    def test_source_download_defaults_to_audio_and_saves_source_thumbnail_and_creator_captions(self) -> None:
        tracks = {"subtitles": {"en": [{"ext": "vtt"}]}, "automatic_captions": {"en": [{"ext": "vtt"}]}}
        _, batch, job = self.create_confirmed_job("klmno123456", ["en"], tracks)
        output = self.root / "output"
        argument_log = self.root / "download-arguments.jsonl"
        tool = self.metadata_tool()
        response = self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(output)},
            env={"YTDLP_BINARY": str(tool), "YTDLP_ARGS_LOG": str(argument_log)},
        )
        downloaded = response["result"]

        self.assertEqual(downloaded["download_status"], "complete")
        self.assertFalse(downloaded["include_video_source"])
        self.assertTrue(Path(downloaded["source_audio_path"]).is_file())
        self.assertEqual(Path(downloaded["source_audio_path"]).suffix, ".mp3")
        self.assertIsNone(downloaded["source_video_path"])
        self.assertTrue(Path(downloaded["source_thumbnail_path"]).is_file())
        self.assertEqual(downloaded["subtitle_decision"], "youtube")
        self.assertEqual(downloaded["subtitle_source"], "creator")
        self.assertTrue(any(item["kind"] == "subtitle_youtube" and item["available"] for item in downloaded["artifacts"]))
        commands = [json.loads(line) for line in argument_log.read_text().splitlines()]
        media_command = next(command for command in commands if "--write-thumbnail" in command)
        subtitle_command = next(command for command in commands if "--write-subs" in command)
        self.assertEqual(media_command[media_command.index("-f") + 1], "bestaudio/best")
        self.assertNotIn("--no-call-home", media_command)
        self.assertIn("--skip-download", subtitle_command)
        self.assertNotIn("--write-auto-subs", subtitle_command)

    def test_download_without_a_matching_subtitle_waits_for_file_or_skip_decision(self) -> None:
        _, batch, job = self.create_confirmed_job("pqrst123456", ["de"], {"subtitles": {}, "automatic_captions": {}})
        argument_log = self.root / "waiting-download-arguments.jsonl"
        downloaded = self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(self.root / "waiting-output")},
            env={"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(argument_log)},
        )["result"]
        self.assertEqual(downloaded["download_status"], "needs_subtitle_decision")
        self.assertEqual(downloaded["subtitle_decision"], "needs_decision")

        supplied = self.root / "fallback.vtt"
        supplied.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n")
        attached = self.request("jobs.attach_subtitle_file", {"job_id": job["id"], "path": str(supplied)})["result"]
        self.assertEqual(attached["job"]["subtitle_decision"], "use_file")
        self.assertEqual(attached["job"]["download_status"], "complete")

    def test_full_source_video_is_an_explicit_download_option(self) -> None:
        _, batch, job = self.create_confirmed_job("vwxyz123456", ["de"], {"subtitles": {}, "automatic_captions": {}})
        argument_log = self.root / "full-video-arguments.jsonl"
        downloaded = self.request(
            "jobs.download_sources",
            {
                "batch_id": batch["id"],
                "job_id": job["id"],
                "output_dir": str(self.root / "full-video-output"),
                "include_video_source": True,
                "max_video_height": 720,
            },
            env={"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(argument_log)},
        )["result"]

        self.assertTrue(downloaded["include_video_source"])
        self.assertIsNone(downloaded["source_audio_path"])
        self.assertTrue(Path(downloaded["source_video_path"]).is_file())
        self.assertEqual(Path(downloaded["source_video_path"]).suffix, ".mp4")
        commands = [json.loads(line) for line in argument_log.read_text().splitlines()]
        video_command = next(command for command in commands if "--merge-output-format" in command)
        self.assertEqual(video_command[video_command.index("-f") + 1], "bestvideo[height<=720]+bestaudio/best[height<=720]")

    def test_render_inspection_detects_aspect_ratio_mismatch_and_stores_resolution(self) -> None:
        background, _ = self.make_ffmpeg_fixtures(width=90, height=160)
        _, batch, job = self.create_confirmed_job("cdefg123456", [], background_path=background)
        inspected = self.request("jobs.inspect_render", {"job_id": job["id"]})
        self.assertTrue(inspected["ok"], inspected)
        self.assertTrue(inspected["result"]["requires_frame_decision"])
        self.assertEqual(inspected["result"]["profile_frame"], {"width": 1280, "height": 720, "frame_rate": 24.0})
        self.assertEqual(inspected["result"]["background_frame"], {"width": 90, "height": 160, "frame_rate": 24.0})

        configured = self.request(
            "jobs.configure_output",
            {
                "job_id": job["id"],
                "profile": "720p",
                "frame_preference": "background",
                "fit_mode": "contain",
            },
        )
        self.assertTrue(configured["ok"], configured)
        plan = self.request("jobs.inspect_render", {"job_id": job["id"]})["result"]
        self.assertFalse(plan["requires_frame_decision"])
        self.assertEqual(plan["output_frame"], {"width": 90, "height": 160, "frame_rate": 24.0})
        self.assertEqual(plan["fit_mode"], "contain")

        bulk = self.request(
            "batches.configure_output_bulk",
            {"batch_id": batch["id"], "job_ids": [job["id"]], "profile": "custom",
             "custom_width": 640, "custom_height": 480, "custom_frame_rate": 30,
             "frame_preference": "profile", "fit_mode": "crop"},
        )
        self.assertTrue(bulk["ok"], bulk)
        custom_plan = self.request("jobs.inspect_render", {"job_id": job["id"]})["result"]
        self.assertEqual(custom_plan["profile_frame"], {"width": 640, "height": 480, "frame_rate": 30.0})
        self.assertEqual(custom_plan["output_frame"], custom_plan["profile_frame"])

    def test_real_ffmpeg_renders_720p_audio_and_background(self) -> None:
        background, audio_fixture = self.make_ffmpeg_fixtures()
        _, batch, job = self.create_confirmed_job("hijkl123456", [], background_path=background)
        self.request("jobs.skip_captions", {"job_id": job["id"]})
        download = self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(self.root / "render-inputs")},
            env={
                "YTDLP_BINARY": str(self.metadata_tool()),
                "YTDLP_ARGS_LOG": str(self.root / "render-download-args.jsonl"),
                "FAKE_SOURCE_FIXTURE": str(audio_fixture),
            },
        )["result"]
        self.assertEqual(download["download_status"], "complete")

        rendered = self.request("jobs.render_video", {"batch_id": batch["id"], "job_id": job["id"]})

        self.assertTrue(rendered["ok"], rendered)
        output_job = rendered["result"]
        self.assertEqual(output_job["render_status"], "complete")
        self.assertEqual(output_job["encoder_used"], "libx264")
        self.assertTrue(Path(output_job["output_video_path"]).is_file())
        ffprobe = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
        details = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height,avg_frame_rate:format=duration", "-of", "json", output_job["output_video_path"]],
            capture_output=True, text=True, check=False, timeout=15,
        )
        self.assertEqual(details.returncode, 0, details.stderr)
        probe = json.loads(details.stdout)
        video_stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video_stream["width"], video_stream["height"]), (1280, 720))
        self.assertEqual(video_stream["avg_frame_rate"], "24/1")
        self.assertTrue(any(stream["codec_type"] == "audio" for stream in probe["streams"]))
        self.assertGreater(float(probe["format"]["duration"]), 1.0)

    def test_real_ffmpeg_burns_captions_and_saves_srt_when_libass_is_available(self) -> None:
        ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is required for caption burn-in fixture test")
        capabilities = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=False, timeout=15)
        if " subtitles " not in capabilities.stdout:
            self.skipTest("Local FFmpeg has no subtitles/libass filter; configure FFMPEG_BINARY to an ffmpeg-full build")
        background, audio_fixture = self.make_ffmpeg_fixtures()
        _, batch, job = self.create_confirmed_job("mnopq123456", ["de"], {"subtitles": {}, "automatic_captions": {}}, background)
        subtitle = self.root / "captions.srt"
        subtitle.write_text("1\n00:00:00,200 --> 00:00:01,000\nVISIBLE CAPTION\n")
        self.request("jobs.attach_subtitle_file", {"job_id": job["id"], "path": str(subtitle)})
        self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(self.root / "caption-inputs")},
            env={
                "YTDLP_BINARY": str(self.metadata_tool()),
                "YTDLP_ARGS_LOG": str(self.root / "caption-download-args.jsonl"),
                "FAKE_SOURCE_FIXTURE": str(audio_fixture),
            },
        )

        rendered = self.request("jobs.render_video", {"batch_id": batch["id"], "job_id": job["id"]})["result"]

        self.assertEqual(rendered["render_status"], "complete")
        self.assertTrue(Path(rendered["srt_sidecar_path"]).is_file())
        self.assertIn("VISIBLE CAPTION", Path(rendered["srt_sidecar_path"]).read_text())
        frame = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", "0.5", "-i", rendered["output_video_path"], "-frames:v", "1", "-vf", "crop=480:90:400:600", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            capture_output=True, check=False, timeout=15,
        )
        self.assertEqual(frame.returncode, 0, frame.stderr.decode(errors="replace"))
        self.assertGreater(max(frame.stdout) - min(frame.stdout), 30)

    def test_render_records_actionable_error_when_ffmpeg_has_no_libass(self) -> None:
        ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is required for renderer failure fixture test")
        capabilities = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=False, timeout=15)
        if " subtitles " in capabilities.stdout:
            self.skipTest("Local FFmpeg includes libass, so the missing-filter failure path is unavailable")
        background, audio_fixture = self.make_ffmpeg_fixtures()
        _, batch, job = self.create_confirmed_job("rstuv123456", ["en"], {"subtitles": {}, "automatic_captions": {}}, background)
        subtitle = self.root / "captions.srt"
        subtitle.write_text("1\n00:00:00,200 --> 00:00:01,000\nVisible caption\n")
        self.request("jobs.attach_subtitle_file", {"job_id": job["id"], "path": str(subtitle)})
        self.request(
            "jobs.download_sources",
            {"batch_id": batch["id"], "job_id": job["id"], "output_dir": str(self.root / "missing-libass-inputs")},
            env={"YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(self.root / "missing-libass-args.jsonl"), "FAKE_SOURCE_FIXTURE": str(audio_fixture)},
        )

        rendered = self.request("jobs.render_video", {"batch_id": batch["id"], "job_id": job["id"]})["result"]

        self.assertEqual(rendered["render_status"], "error")
        self.assertIn("libass", rendered["render_error"])
        self.request("jobs.skip_captions", {"job_id": job["id"]})
        retried = self.request("jobs.render_video", {"batch_id": batch["id"], "job_id": job["id"]})["result"]
        self.assertEqual(retried["render_status"], "complete")

    def test_subtitle_presets_can_be_created_duplicated_and_applied(self) -> None:
        channel = self.request("channels.create", {"name": "Kênh Preset"})["result"]
        style = {
            "font_family": "Arial", "bold": True, "font_size": 40, "text_color": "#FFF2A8",
            "background_enabled": True, "background_color": "#101820", "background_opacity": 0.65,
            "outline_color": "#000000", "outline_width": 2, "shadow": 1,
            "alignment": "bottom-center", "position_x": 50, "position_y": 88,
        }
        created = self.request(
            "subtitles.presets.create",
            {"channel_id": channel["id"], "name": "Warm captions", "style": style},
        )["result"]
        duplicate = self.request(
            "subtitles.presets.duplicate",
            {"preset_id": created["id"], "name": "Warm captions copy"},
        )["result"]
        changed_style = {**style, "font_size": 46}
        updated = self.request(
            "subtitles.presets.update",
            {"preset_id": duplicate["id"], "name": "Large warm captions", "style": changed_style},
        )["result"]
        self.request("channels.set_default_subtitle_preset", {"channel_id": channel["id"], "preset_id": created["id"]})

        self.add_backgrounds(channel["id"], 1)
        imported = self.request("batches.import_text", {"name": "Preset application", "channel_id": channel["id"], "content": "https://youtu.be/zyxwv123456"})["result"]
        self.lookup_batch_metadata(imported["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": imported["batch"]["id"]})["result"]
        applied = self.request("jobs.set_subtitle_preset", {"job_id": confirmed["jobs"][0]["id"], "preset_id": duplicate["id"]})["result"]

        self.assertEqual(updated["style"]["font_size"], 46)
        self.assertTrue(updated["style"]["bold"])
        self.assertEqual(applied["subtitle_style"]["font_size"], 46)
        self.assertEqual(self.request("subtitles.presets.list", {"channel_id": channel["id"]})["result"][0]["id"], duplicate["id"])

    def test_subtitle_font_catalog_is_sorted_and_unique(self) -> None:
        from worker import worker as worker_module

        fonts = worker_module.list_installed_subtitle_fonts()

        self.assertEqual(fonts, sorted(set(fonts), key=str.casefold))
        self.assertTrue(all(isinstance(font, str) and font for font in fonts))

    def test_ass_caption_wraps_long_lines_and_keeps_middle_center_anchor(self) -> None:
        from worker import worker as worker_module

        source = self.root / "center-caption.srt"
        destination = self.root / "center-caption.ass"
        source.write_text("1\n00:00:00,000 --> 00:00:02,000\nA long caption that should wrap and remain aligned around its center point.\n")
        style = {
            **worker_module.DEFAULT_SUBTITLE_STYLE,
            "alignment": "middle-center",
            "position_x": 50,
            "position_y": 50,
            "bold": True,
        }

        worker_module.write_ass_subtitle(source, destination, style, {"width": 1280, "height": 720})
        ass = destination.read_text(encoding="utf-8")

        self.assertIn("WrapStyle: 0", ass)
        self.assertIn(r"{\an5\pos(640,360)}", ass)
        style_line = next(line for line in ass.splitlines() if line.startswith("Style: Default,"))
        self.assertEqual(style_line.split(",")[7], "-1")
        self.assertEqual(style_line.split(",")[19:21], ["77", "77"])

    def test_media_probe_decodes_ffprobe_json_as_utf8(self) -> None:
        from unittest.mock import patch

        from worker import worker as worker_module

        command = ["ffprobe", "-of", "json", "D:/YT/nền/background.mp4"]
        probe_output = '{"streams": [], "format": {"filename": "D:/YT/nền/background.mp4"}}'
        completed = subprocess.CompletedProcess(command, 0, probe_output, "")
        with patch.dict(worker_module.os.environ, {"FFPROBE_BINARY": "ffprobe"}), \
                patch.object(worker_module.subprocess, "run", return_value=completed) as run:
            result = worker_module.media_probe("D:/YT/nền/background.mp4")

        self.assertEqual(result["format"]["filename"], "D:/YT/nền/background.mp4")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_subtitle_style_defaults_to_regular_font_and_supports_bold(self) -> None:
        from worker import worker as worker_module

        self.assertFalse(worker_module.validate_subtitle_style({})["bold"])
        self.assertTrue(worker_module.validate_subtitle_style({"bold": True})["bold"])

    def test_thumbnail_queue_runs_without_video_audio_and_resumes_after_text_review(self) -> None:
        from PIL import Image

        _, batch, job = self.create_confirmed_job("thumbq12345", [])
        source_image = self.root / "source-thumb.jpg"
        Image.new("RGB", (320, 180), "#263a31").save(source_image, format="JPEG")
        ocr = self.root / "fake-tesseract"
        ocr.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--list-langs' in sys.argv:\n"
            " print('List of available languages (1):\\neng')\n"
            "else:\n"
            " print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext')\n"
            " print('5\\t1\\t1\\t1\\t1\\t1\\t1\\t1\\t90\\t30\\t94\\tSOURCE_WORDS')\n"
        )
        ocr.chmod(0o755)
        fake_ytdlp = self.metadata_tool()
        started = self.request("queue.start", {
            "batch_id": batch["id"], "job_ids": [job["id"]], "output_root": str(self.root / "thumb-output"), "pipeline": "thumbnail",
        }, env={
            "YTDLP_BINARY": str(fake_ytdlp), "YTDLP_ARGS_LOG": str(self.root / "thumb-args.jsonl"),
            "FAKE_THUMBNAIL_FIXTURE": str(source_image), "TESSERACT_BINARY": str(ocr),
        })["result"]
        task = next(item for item in started["tasks"] if item["pipeline"] == "thumbnail")
        waiting = self.wait_for_queue_state(batch["id"], task["id"], {"waiting_for_thumbnail_review"})
        reviewed = self.request("batches.get", {"batch_id": batch["id"]})["result"]["jobs"][0]
        self.assertEqual(waiting["pipeline"], "thumbnail")
        self.assertEqual(reviewed["thumbnail_ocr_text"], "SOURCE_WORDS")
        self.assertEqual(reviewed["thumbnail_ocr_status"], "awaiting_confirmation")
        self.assertIsNone(reviewed["source_audio_path"], "Thumbnail processing must not download source audio.")
        arguments = json.loads((self.root / "thumb-args.jsonl").read_text().splitlines()[-1])
        self.assertIn("--skip-download", arguments)

        self.request("jobs.set_thumbnail_text", {"job_id": job["id"], "text": "EDITED WORDS"})
        self.request("queue.retry", {"task_id": task["id"]})
        complete = self.wait_for_queue_state(batch["id"], task["id"], {"complete"})
        final_job = self.request("batches.get", {"batch_id": batch["id"]})["result"]["jobs"][0]
        self.assertEqual(complete["progress"], 1)
        self.assertEqual(final_job["thumbnail_text"], "EDITED WORDS")
        self.assertTrue(Path(final_job["thumbnail_output_path"]).is_file())
        self.assertEqual(final_job["thumbnail_progress"], 1)

    def test_video_queue_failure_does_not_stop_the_next_job(self) -> None:
        background, audio = self.make_ffmpeg_fixtures()
        broken_background = self.root / "broken-background.mp4"
        broken_background.write_bytes(b"not a media file")
        first_channel = self.request("channels.create", {"name": "Broken render channel"})["result"]
        second_channel = self.request("channels.create", {"name": "Working render channel"})["result"]
        self.add_backgrounds(first_channel["id"], 0)
        self.request("backgrounds.add_to_channel", {"channel_id": first_channel["id"], "path": str(broken_background)})
        self.request("backgrounds.add_to_channel", {"channel_id": second_channel["id"], "path": str(background)})
        batch = self.request("batches.import_text", {
            "name": "Queue failure isolation", "content": f"Channel,URL\n{first_channel['name']},https://youtu.be/badvid12345\n{second_channel['name']},https://youtu.be/goodvid1234",
        })["result"]
        self.lookup_batch_metadata(batch["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": batch["batch"]["id"]})["result"]
        jobs = confirmed["jobs"]
        for job in jobs:
            self.request("jobs.skip_captions", {"job_id": job["id"]})
        source_tool = self.metadata_tool()
        args_log = self.root / "queue-download-args.jsonl"
        started = self.request("queue.start", {
            "batch_id": batch["batch"]["id"], "job_ids": [job["id"] for job in jobs], "output_root": str(self.root / "video-output"),
        }, env={
            "YTDLP_BINARY": str(source_tool), "YTDLP_ARGS_LOG": str(args_log), "FAKE_SOURCE_FIXTURE": str(audio),
        })["result"]
        tasks = {item["job_id"]: item["id"] for item in started["tasks"] if item["pipeline"] == "video"}
        states: dict[str, str] = {}
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline and len(states) < 2:
            result = self.request("queue.status", {"batch_id": batch["batch"]["id"]})["result"]
            states = {item["job_id"]: item["state"] for item in result["tasks"] if item["id"] in tasks.values() and item["state"] in {"complete", "failed", "cancelled", "interrupted"}}
            time.sleep(0.12)
        self.assertEqual(states.get(jobs[0]["id"]), "failed")
        self.assertEqual(states.get(jobs[1]["id"]), "complete")
        final_jobs = self.request("batches.get", {"batch_id": batch["batch"]["id"]})["result"]["jobs"]
        self.assertEqual(final_jobs[0]["render_status"], "error", final_jobs[0])
        self.assertEqual(final_jobs[1]["render_status"], "complete")

    def test_video_queue_cancel_and_retry_reuses_the_job_plan(self) -> None:
        background, audio = self.make_ffmpeg_fixtures()
        _, batch, job = self.create_confirmed_job("canceltry12", [], background_path=background)
        self.request("jobs.skip_captions", {"job_id": job["id"]})
        fake_ytdlp = self.metadata_tool()
        args_log = self.root / "cancel-retry-args.jsonl"
        started = self.request("queue.start", {
            "batch_id": batch["id"], "job_ids": [job["id"]], "output_root": str(self.root / "retry-output"),
        }, env={
            "YTDLP_BINARY": str(fake_ytdlp), "YTDLP_ARGS_LOG": str(args_log), "FAKE_SOURCE_FIXTURE": str(audio), "FAKE_YTDLP_SLEEP": "4",
        })["result"]
        task = next(item for item in started["tasks"] if item["pipeline"] == "video")
        self.wait_for_queue_state(batch["id"], task["id"], {"downloading"})
        self.request("queue.cancel", {"task_id": task["id"]})
        cancelled = self.wait_for_queue_state(batch["id"], task["id"], {"cancelled"})
        self.assertIn("cancel", (cancelled["error"] or "").lower())

        self.request("queue.retry", {"task_id": task["id"]}, env={
            "YTDLP_BINARY": str(fake_ytdlp), "YTDLP_ARGS_LOG": str(args_log), "FAKE_SOURCE_FIXTURE": str(audio), "FAKE_YTDLP_SLEEP": "0",
        })
        completed = self.wait_for_queue_state(batch["id"], task["id"], {"complete"})
        final_job = self.request("batches.get", {"batch_id": batch["id"]})["result"]["jobs"][0]
        self.assertEqual(completed["pipeline"], "video")
        self.assertEqual(final_job["background_asset_id"], job["background_asset_id"])
        self.assertEqual(final_job["render_status"], "complete")
        self.assertTrue(Path(final_job["output_video_path"]).is_file())

    def test_queued_queue_task_can_be_removed_without_removing_its_job(self) -> None:
        channel = self.request("channels.create", {"name": "Remove queued task"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Queued task removal",
            "channel_id": channel["id"],
            "content": "https://youtu.be/removequeued",
        })["result"]
        batch = imported["batch"]
        job = imported["jobs"][0]
        task_id = "queued-task-to-remove"
        created_at = datetime.now().isoformat()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, created_at, updated_at) VALUES (?, ?, ?, 'video', 'queued', 'queued', 0, ?, ?, ?)",
                (task_id, batch["id"], job["id"], str(self.root / "queued-output"), created_at, created_at),
            )
            connection.execute(
                "INSERT INTO queue_task_logs(id, task_id, level, message, created_at) VALUES (?, ?, 'info', 'queued', ?)",
                ("queued-task-log", task_id, created_at),
            )
            connection.commit()
        connection.close()

        removed = self.request("queue.remove", {"task_id": task_id})["result"]
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(removed["job_id"], job["id"])
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute("SELECT id FROM queue_tasks WHERE id = ?", (task_id,)).fetchone())
            self.assertIsNone(connection.execute("SELECT id FROM queue_task_logs WHERE task_id = ?", (task_id,)).fetchone())
        self.assertIsNotNone(connection.execute("SELECT id FROM video_jobs WHERE id = ?", (job["id"],)).fetchone())
        connection.close()

    def test_batch_delete_removes_history_but_keeps_downloaded_files(self) -> None:
        channel = self.request("channels.create", {"name": "Delete batch"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Batch to delete",
            "channel_id": channel["id"],
            "workflow_mode": "download_only",
            "content": "https://youtu.be/deletebatch1",
        })["result"]
        batch_id = imported["batch"]["id"]
        job_id = imported["jobs"][0]["id"]
        output_file = self.root / "saved-output" / "source.mp4"
        output_file.parent.mkdir()
        output_file.write_bytes(b"saved video")
        created_at = datetime.now().isoformat()
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, created_at, updated_at, completed_at) VALUES (?, ?, ?, 'download_only', 'complete', 'packaging', 1, ?, ?, ?, ?)",
            ("completed-delete-task", batch_id, job_id, str(output_file.parent), created_at, created_at, created_at),
        )
        connection.execute(
            "INSERT INTO queue_task_logs(id, task_id, level, message, created_at) VALUES (?, ?, 'info', 'complete', ?)",
            ("completed-delete-log", "completed-delete-task", created_at),
        )
        connection.execute(
            "INSERT INTO job_artifacts(id, job_id, kind, path, created_at) VALUES (?, ?, 'source_video', ?, ?)",
            ("delete-batch-artifact", job_id, str(output_file), created_at),
        )
        connection.commit()
        connection.close()

        deleted = self.request("batches.delete", {"batch_id": batch_id})["result"]
        self.assertTrue(deleted["deleted"])
        self.assertTrue(deleted["files_kept"])
        self.assertTrue(output_file.is_file())
        with sqlite3.connect(self.database) as connection:
            self.assertIsNone(connection.execute("SELECT id FROM batches WHERE id = ?", (batch_id,)).fetchone())
            self.assertIsNone(connection.execute("SELECT id FROM video_jobs WHERE id = ?", (job_id,)).fetchone())
            self.assertIsNone(connection.execute("SELECT id FROM queue_tasks WHERE id = ?", ("completed-delete-task",)).fetchone())
            self.assertIsNone(connection.execute("SELECT id FROM queue_task_logs WHERE id = ?", ("completed-delete-log",)).fetchone())
            self.assertIsNone(connection.execute("SELECT id FROM job_artifacts WHERE id = ?", ("delete-batch-artifact",)).fetchone())
        connection.close()

    def test_batch_delete_rejects_active_jobs(self) -> None:
        channel = self.request("channels.create", {"name": "Active batch"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Active batch to keep",
            "channel_id": channel["id"],
            "content": "https://youtu.be/activebatch1",
        })["result"]
        batch_id = imported["batch"]["id"]
        job_id = imported["jobs"][0]["id"]
        created_at = datetime.now().isoformat()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, created_at, updated_at) VALUES (?, ?, ?, 'video', 'downloading', 'downloading', 0.4, ?, ?, ?)",
                ("active-delete-task", batch_id, job_id, str(self.root / "active-output"), created_at, created_at),
            )
            connection.commit()
        connection.close()

        response = self.request("batches.delete", {"batch_id": batch_id})
        self.assertFalse(response["ok"])
        self.assertIn("active jobs", response["error"]["message"])
        with sqlite3.connect(self.database) as connection:
            self.assertIsNotNone(connection.execute("SELECT id FROM batches WHERE id = ?", (batch_id,)).fetchone())
        connection.close()

    def test_download_only_folders_use_channel_name_and_video_import_order(self) -> None:
        from worker import worker as worker_module

        channel = self.request("channels.create", {"name": "Kênh 1"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Folder order",
            "channel_id": channel["id"],
            "workflow_mode": "download_only",
            "content": "https://youtu.be/11111111111\nhttps://youtu.be/22222222222",
        })["result"]
        connection = worker_module.open_database(str(self.database))
        jobs = connection.execute(
            "SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position",
            (imported["batch"]["id"],),
        ).fetchall()
        directories = [
            worker_module.job_download_directory(connection, job, str(self.root / "ordered-output"))
            for job in jobs
        ]
        connection.close()

        self.assertEqual([directory.name for directory in directories], ["video 1", "video 2"])
        self.assertEqual([directory.parent.name for directory in directories], ["Kênh 1", "Kênh 1"])
        self.assertTrue(all(directory.parent.parent == (self.root / "ordered-output").resolve() for directory in directories))

    def test_download_only_audio_package_saves_video_title(self) -> None:
        from worker import worker as worker_module

        channel = self.request("channels.create", {"name": "Audio package title"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Audio package title",
            "channel_id": channel["id"],
            "workflow_mode": "download_only",
            "content": "https://youtu.be/titlepackage1",
        })["result"]
        job = imported["jobs"][0]
        package = self.root / "audio-output" / "Audio package title" / "video 1"
        package.mkdir(parents=True)
        audio = package / "source.m4a"
        thumbnail = package / "source.jpg"
        audio.write_bytes(b"audio")
        thumbnail.write_bytes(b"thumbnail")
        connection = worker_module.open_database(str(self.database))
        connection.execute(
            "UPDATE video_jobs SET metadata_status = 'ready', title = ?, subtitle_decision = 'skip', source_audio_path = ?, source_video_path = NULL, source_thumbnail_path = ? WHERE id = ?",
            ("Morning focus — música", str(audio), str(thumbnail), job["id"]),
        )
        connection.commit()

        worker_module.prepare_download_only_package(connection, {
            "job_id": job["id"],
            "include_video_source": 0,
        })
        connection.close()

        title_file = package / "title.txt"
        self.assertEqual(title_file.read_text(encoding="utf-8"), "Morning focus — música\n")
        with sqlite3.connect(self.database) as connection:
            artifact = connection.execute(
                "SELECT path FROM job_artifacts WHERE job_id = ? AND kind = 'video_title'",
                (job["id"],),
            ).fetchone()
        connection.close()
        self.assertEqual(artifact[0], str(title_file))

    def test_download_only_media_choice_and_resolution_build_ytdlp_formats(self) -> None:
        from unittest.mock import patch

        from worker import worker as worker_module

        channel = self.request("channels.create", {"name": "Download format options"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Download format options",
            "channel_id": channel["id"],
            "workflow_mode": "download_only",
            "content": "https://youtu.be/videoid0001\nhttps://youtu.be/audioid0001",
        })["result"]
        connection = worker_module.open_database(str(self.database))
        connection.execute(
            "UPDATE batches SET state = 'confirmed', confirmed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), imported["batch"]["id"]),
        )
        connection.execute(
            "UPDATE video_jobs SET metadata_status = 'ready', title = CASE position WHEN 0 THEN 'Video title' ELSE 'Audio title' END, subtitle_decision = 'skip' WHERE batch_id = ?",
            (imported["batch"]["id"],),
        )
        connection.commit()
        jobs = connection.execute(
            "SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position",
            (imported["batch"]["id"],),
        ).fetchall()
        commands = []

        def fake_run_ytdlp(command, **kwargs):
            commands.append(command)
            template = command[command.index("--output") + 1]
            extension = command[command.index("--merge-output-format") + 1] if "--merge-output-format" in command else "mp3"
            Path(template.replace("%(ext)s", extension)).write_bytes(b"media")
            if "--write-thumbnail" in command:
                Path(template.replace("%(ext)s", "jpg")).write_bytes(b"thumbnail")

        output_root = self.root / "format-output"
        output_root.mkdir()
        with patch.object(worker_module, "run_ytdlp", side_effect=fake_run_ytdlp), \
                patch.dict(worker_module.os.environ, {"YTDLP_BINARY": "fake-yt-dlp"}):
            video = worker_module.download_job_sources(
                connection, imported["batch"]["id"], jobs[0]["id"], str(output_root),
                True, download_only=True, max_video_height=720,
            )
            audio = worker_module.download_job_sources(
                connection, imported["batch"]["id"], jobs[1]["id"], str(output_root),
                False, download_only=True,
            )
            for job in jobs:
                worker_module.prepare_download_only_package(connection, {
                    "job_id": job["id"],
                    "include_video_source": int(job["position"] == 0),
                })
        connection.close()

        video_command = next(command for command in commands if "--merge-output-format" in command)
        audio_command = next(command for command in commands if "--merge-output-format" not in command)
        self.assertEqual(video_command[video_command.index("-f") + 1], "bestvideo[height<=720]+bestaudio/best[height<=720]")
        self.assertEqual(audio_command[audio_command.index("-f") + 1], "bestaudio")
        self.assertNotIn("--no-call-home", video_command)
        self.assertNotIn("--no-call-home", audio_command)
        self.assertEqual(video["download_status"], "complete")
        self.assertEqual(audio["download_status"], "complete")
        self.assertTrue(Path(video["source_video_path"]).is_file())
        self.assertTrue(Path(audio["source_audio_path"]).is_file())
        self.assertTrue((Path(video["source_video_path"]).parent / "title.txt").is_file())
        self.assertTrue((Path(audio["source_audio_path"]).parent / "title.txt").is_file())

    def test_youtube_karaoke_vtt_is_normalized_without_inline_timestamps_or_rollup_duplicates(self) -> None:
        from worker import worker as worker_module

        source = self.root / "youtube-captions.vtt"
        destination = self.root / "captions.srt"
        source.write_text(
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:00.050\n"
            "Hello <00:00:00.200><c>world</c>\n\n"
            "00:00:00.050 --> 00:00:02.000\n"
            "Hello <00:00:00.200><c>world </c><00:00:00.700><c>from </c>"
            "<00:00:01.200><c>YouTube.</c>\n\n"
            "00:00:02.000 --> 00:00:02.050\n"
            "world from YouTube.\n\n"
            "00:00:02.050 --> 00:00:03.500\n"
            "world from YouTube. This is <00:00:02.700><c>clean.</c>\n",
            encoding="utf-8",
        )

        worker_module.normalize_subtitle_to_srt(str(source), destination)
        normalized = destination.read_text(encoding="utf-8")

        self.assertEqual(normalized.count("Hello world from YouTube."), 1)
        self.assertIn("This is clean.", normalized)
        self.assertNotIn("<00:", normalized)
        self.assertNotIn("<c>", normalized)
        self.assertIn("00:00:03,500", normalized)

    def test_karaoke_caption_groups_do_not_split_into_instantaneous_cues(self) -> None:
        import re

        from worker import worker as worker_module

        source = self.root / "same-start-words.vtt"
        destination = self.root / "grouped-caption.srt"
        source.write_text(
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:03.000\n"
            "Get ready <00:00:00.100><c>what comes next will shift </c>"
            "<00:00:00.100><c>everything you thought you knew... </c>"
            "<00:00:01.500><c>another section begins here.</c>\n",
            encoding="utf-8",
        )

        worker_module.normalize_subtitle_to_srt(str(source), destination)
        blocks = re.split(r"\n\s*\n", destination.read_text(encoding="utf-8").strip())
        timings = [
            re.search(r"(\d{2}:\d{2}:\d{2}),(\d{3}) --> (\d{2}:\d{2}:\d{2}),(\d{3})", block)
            for block in blocks
        ]
        durations = []
        for match in filter(None, timings):
            start = sum(float(part) * factor for part, factor in zip(match.group(1).split(":"), (3600, 60, 1))) + int(match.group(2)) / 1000
            end = sum(float(part) * factor for part, factor in zip(match.group(3).split(":"), (3600, 60, 1))) + int(match.group(4)) / 1000
            durations.append(end - start)

        self.assertEqual(len(durations), 2)
        self.assertTrue(all(duration >= 1.2 for duration in durations))

    def test_audio_only_webm_source_converts_to_premiere_compatible_mp3(self) -> None:
        from unittest.mock import patch

        from worker import worker as worker_module

        source = self.root / "source.webm"
        source.write_bytes(b"opus source")
        probe_results = [
            {"streams": [{"codec_type": "audio", "codec_name": "opus"}]},
            {"streams": [{"codec_type": "audio", "codec_name": "mp3"}]},
        ]
        commands = []

        def fake_ffmpeg(command, **kwargs):
            commands.append(command)
            Path(command[-1]).write_bytes(b"mp3 source")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(worker_module, "media_probe", side_effect=probe_results), \
                patch.dict(worker_module.os.environ, {"FFMPEG_BINARY": "ffmpeg"}), \
                patch.object(worker_module.subprocess, "run", side_effect=fake_ffmpeg):
            converted = worker_module.ensure_premiere_compatible_audio(source)

        self.assertEqual(converted, source.with_suffix(".mp3"))
        self.assertTrue(source.is_file())
        self.assertEqual(converted.read_bytes(), b"mp3 source")
        self.assertIn("libmp3lame", commands[0])
        self.assertIn("192k", commands[0])
        self.assertIn("-vn", commands[0])

    def test_subtitle_downloads_are_paced_and_retried(self) -> None:
        from unittest.mock import patch

        from worker import worker as worker_module

        channel = self.request("channels.create", {"name": "Subtitle pacing"})["result"]
        self.request("channels.set_subtitle_languages", {"channel_id": channel["id"], "languages": ["en"]})
        imported = self.request("batches.import_text", {
            "name": "Subtitle pacing",
            "channel_id": channel["id"],
            "workflow_mode": "download_only",
            "content": "https://youtu.be/subtitlepace1",
        })["result"]
        job = imported["jobs"][0]
        connection = worker_module.open_database(str(self.database))
        connection.execute(
            "UPDATE batches SET state = 'confirmed', confirmed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), imported["batch"]["id"]),
        )
        connection.execute(
            "UPDATE video_jobs SET metadata_status = 'ready', title = 'Subtitle pacing video', subtitle_tracks_json = ? WHERE id = ?",
            (json.dumps({"creator": [{"language": "en", "formats": "vtt", "label": ""}], "automatic": []}), job["id"]),
        )
        connection.commit()
        commands = []
        subtitle_attempts = 0

        def fake_run_ytdlp(command, **kwargs):
            nonlocal subtitle_attempts
            commands.append(command)
            template = Path(command[command.index("--output") + 1])
            if "--skip-download" in command:
                subtitle_attempts += 1
                if subtitle_attempts == 1:
                    raise ValueError("HTTP Error 429: Too Many Requests")
                template.with_name("subtitle.en.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
            else:
                template.with_name("source.mp4").write_bytes(b"video")
                template.with_name("source.jpg").write_bytes(b"thumbnail")

        output_root = self.root / "subtitle-pacing-output"
        output_root.mkdir()
        with patch.object(worker_module, "run_ytdlp", side_effect=fake_run_ytdlp), \
                patch.object(worker_module, "YOUTUBE_SUBTITLE_MIN_GAP_SECONDS", 0), \
                patch.dict(worker_module.os.environ, {"YTDLP_BINARY": "fake-yt-dlp"}):
            failed = worker_module.download_job_sources(
                connection, imported["batch"]["id"], job["id"], str(output_root),
                True, download_only=True,
            )
            downloaded = worker_module.download_job_sources(
                connection, imported["batch"]["id"], job["id"], str(output_root),
                True, download_only=True,
            )
        connection.close()

        subtitle_command = next(command for command in commands if "--skip-download" in command)
        media_commands = [command for command in commands if "--merge-output-format" in command]
        self.assertEqual(failed["download_status"], "error")
        self.assertIn("rate-limiting", failed["download_error"])
        self.assertEqual(downloaded["download_status"], "complete")
        self.assertEqual(len(media_commands), 1)
        self.assertEqual(subtitle_command[subtitle_command.index("--sleep-requests") + 1], "1")
        self.assertEqual(subtitle_command[subtitle_command.index("--sleep-subtitles") + 1], "2")
        self.assertEqual(subtitle_command[subtitle_command.index("--retry-sleep") + 1], "http:exp=5:30")
        self.assertNotIn("--no-call-home", subtitle_command)

    def test_output_directory_settings_and_batch_override_are_persisted(self) -> None:
        channel = self.request("channels.create", {"name": "Output settings"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Output root batch",
            "channel_id": channel["id"],
            "content": "https://youtu.be/outputroot01",
        })["result"]
        default_root = self.root / "default-output"
        batch_root = self.root / "batch-output"
        default_root.mkdir()
        batch_root.mkdir()

        configured = self.request("settings.output_directory.set", {"path": str(default_root)})["result"]
        self.assertEqual(configured["path"], str(default_root.resolve()))
        self.assertTrue(configured["available"])
        batch = self.request("batches.set_output_root", {
            "batch_id": imported["batch"]["id"],
            "path": str(batch_root),
        })["result"]
        self.assertEqual(batch["output_root"], str(batch_root.resolve()))
        reset = self.request("batches.set_output_root", {
            "batch_id": imported["batch"]["id"],
            "path": None,
        })["result"]
        self.assertIsNone(reset["output_root"])
        cleared = self.request("settings.output_directory.set", {"path": None})["result"]
        self.assertFalse(cleared["configured"])

    def test_queue_allocates_ordered_video_folders_for_mixed_channels(self) -> None:
        from unittest.mock import patch

        from worker import worker as worker_module

        first_channel = self.request("channels.create", {"name": "Queue Channel A"})["result"]
        second_channel = self.request("channels.create", {"name": "Queue Channel B"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Mixed channel batch",
            "workflow_mode": "download_only",
            "content": (
                f"Channel,URL\n{first_channel['name']},https://youtu.be/firstchan01\n"
                f"{second_channel['name']},https://youtu.be/secondchan1\n"
                f"{first_channel['name']},https://youtu.be/firstchan02"
            ),
        })["result"]
        output_root = self.root / "multi-channel-output"
        output_root.mkdir()
        connection = worker_module.open_database(str(self.database))
        connection.execute(
            "UPDATE batches SET state = 'confirmed', confirmed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), imported["batch"]["id"]),
        )
        connection.execute(
            "UPDATE video_jobs SET metadata_status = 'ready', title = video_id, subtitle_decision = 'skip' WHERE batch_id = ?",
            (imported["batch"]["id"],),
        )
        connection.commit()
        selected_ids = [job["id"] for job in reversed(imported["jobs"])]
        with patch.object(worker_module, "launch_queue_worker", return_value=False):
            queued = worker_module.start_queue_tasks(connection, str(self.database), {
                "batch_id": imported["batch"]["id"],
                "job_ids": selected_ids,
                "output_root": str(output_root),
                "pipeline": "download_only",
                "include_video_source": True,
                "max_video_height": 720,
            })
        channel_names = {channel["id"]: channel["name"] for channel in (first_channel, second_channel)}
        job_channels = {job["id"]: job["channel_id"] for job in imported["jobs"]}
        folders = {
            job_channels[task["job_id"]]: task["output_folder_name"]
            for task in queued["tasks"]
            if task["pipeline"] == "download_only"
        }
        first_channel_folders = [
            task["output_folder_name"]
            for task in queued["tasks"]
            if task["pipeline"] == "download_only" and job_channels[task["job_id"]] == first_channel["id"]
        ]
        self.assertTrue(all(task["include_video_source"] for task in queued["tasks"]))
        self.assertTrue(all(task["max_video_height"] == 720 for task in queued["tasks"]))
        self.assertEqual(first_channel_folders, ["video 1", "video 2"])
        self.assertEqual(folders[second_channel["id"]], "video 1")
        self.assertEqual(channel_names[first_channel["id"]], "Queue Channel A")

        next_batch = self.request("batches.import_text", {
            "name": "Next mixed channel batch",
            "workflow_mode": "download_only",
            "content": f"Channel,URL\n{first_channel['name']},https://youtu.be/thirdvideo01",
        })["result"]
        connection.execute(
            "UPDATE batches SET state = 'confirmed', confirmed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), next_batch["batch"]["id"]),
        )
        connection.execute(
            "UPDATE video_jobs SET metadata_status = 'ready', title = video_id, subtitle_decision = 'skip' WHERE batch_id = ?",
            (next_batch["batch"]["id"],),
        )
        connection.commit()
        with patch.object(worker_module, "launch_queue_worker", return_value=False):
            next_queued = worker_module.start_queue_tasks(connection, str(self.database), {
                "batch_id": next_batch["batch"]["id"],
                "job_ids": [next_batch["jobs"][0]["id"]],
                "output_root": str(output_root),
                "pipeline": "download_only",
                "include_video_source": False,
                "max_video_height": None,
            })
        connection.close()
        self.assertEqual(next_queued["tasks"][0]["output_folder_name"], "video 3")
        self.assertFalse(next_queued["tasks"][0]["include_video_source"])
        self.assertIsNone(next_queued["tasks"][0]["max_video_height"])

    def test_queue_status_marks_work_interrupted_after_a_stale_worker_heartbeat(self) -> None:
        _, batch, job = self.create_confirmed_job("recover1234", [])
        task_id = "stale-queue-task"
        stale_time = "2000-01-01T00:00:00+00:00"
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, created_at, started_at, updated_at) VALUES (?, ?, ?, 'video', 'rendering', 'rendering', 0.4, ?, ?, ?, ?)",
                (task_id, batch["id"], job["id"], str(self.root / "recovery-output"), stale_time, stale_time, stale_time),
            )
            connection.execute("UPDATE queue_runtime SET state = 'running', pid = -1, token = 'dead-worker', heartbeat_at = ?, updated_at = ? WHERE id = 1", (stale_time, stale_time))
            connection.execute("UPDATE video_jobs SET render_status = 'rendering', render_progress = 0.4 WHERE id = ?", (job["id"],))
            connection.commit()

        recovered = self.request("queue.status", {"batch_id": batch["id"]})["result"]
        task = next(item for item in recovered["tasks"] if item["id"] == task_id)
        final_job = self.request("batches.get", {"batch_id": batch["id"]})["result"]["jobs"][0]
        self.assertEqual(task["state"], "interrupted")
        self.assertIn("heartbeat", task["error"].lower())
        self.assertEqual(final_job["render_status"], "interrupted")

    def test_queue_worker_refreshes_heartbeat_without_batch_polling(self) -> None:
        from worker import worker as worker_module

        channel = self.request("channels.create", {"name": "Queue worker heartbeat"})["result"]
        imported = self.request("batches.import_text", {
            "name": "Queue worker heartbeat",
            "channel_id": channel["id"],
            "content": "https://youtu.be/workerheartbeat",
        })["result"]
        task_id = "heartbeat-test-task"
        stale_time = "2000-01-01T00:00:00+00:00"
        connection = worker_module.open_database(str(self.database))
        connection.execute(
            "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, created_at, updated_at) VALUES (?, ?, ?, 'video', 'downloading', 'downloading', 0.2, ?, ?, ?)",
            (task_id, imported["batch"]["id"], imported["jobs"][0]["id"], str(self.root / "heartbeat-output"), stale_time, stale_time),
        )
        connection.execute(
            "UPDATE queue_runtime SET state = 'running', token = ?, pid = NULL, heartbeat_at = ?, updated_at = ? WHERE id = 1",
            ("heartbeat-test-token", stale_time, stale_time),
        )
        connection.commit()
        worker_module.queue_worker_heartbeat(connection, "heartbeat-test-token")
        heartbeat = worker_module.queue_heartbeat(connection)
        task = connection.execute("SELECT state FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
        connection.close()

        self.assertEqual(heartbeat["state"], "running")
        self.assertEqual(task["state"], "downloading")

    def test_process_is_alive_checks_current_windows_process(self) -> None:
        from worker import worker as worker_module

        self.assertTrue(worker_module.process_is_alive(os.getpid()))
        self.assertFalse(worker_module.process_is_alive(2**31 - 1))

    def test_queue_concurrency_setting_is_persisted_and_runs_two_independent_thumbnail_jobs(self) -> None:
        from PIL import Image

        channel = self.request("channels.create", {"name": "Parallel thumbnails"})["result"]
        self.add_backgrounds(channel["id"], 1)
        batch = self.request("batches.import_text", {
            "name": "Parallel thumbnail queue", "channel_id": channel["id"],
            "content": "https://youtu.be/parallel001\nhttps://youtu.be/parallel002",
        })["result"]
        self.lookup_batch_metadata(batch["batch"]["id"])
        confirmed = self.request("batches.confirm", {"batch_id": batch["batch"]["id"]})["result"]
        jobs = confirmed["jobs"]
        self.assertEqual(self.request("queue.status")["result"]["runtime"]["max_concurrency"], 1)
        configured = self.request("queue.configure", {"max_concurrency": 2})["result"]
        self.assertEqual(configured["max_concurrency"], 2)
        self.assertEqual(self.request("queue.status")["result"]["runtime"]["max_concurrency"], 2)

        source_image = self.root / "parallel-source.jpg"
        Image.new("RGB", (240, 135), "#314a3f").save(source_image, format="JPEG")
        ocr = self.root / "parallel-tesseract"
        ocr.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--list-langs' in sys.argv: print('List of available languages (1):\\neng')\n"
            "else:\n"
            " print('level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext')\n"
            " print('5\\t1\\t1\\t1\\t1\\t1\\t1\\t1\\t80\\t20\\t90\\tPARALLEL')\n"
        )
        ocr.chmod(0o755)
        started = self.request("queue.start", {
            "batch_id": batch["batch"]["id"], "job_ids": [job["id"] for job in jobs],
            "output_root": str(self.root / "parallel-output"), "pipeline": "thumbnail",
        }, env={
            "YTDLP_BINARY": str(self.metadata_tool()), "YTDLP_ARGS_LOG": str(self.root / "parallel-args.jsonl"),
            "FAKE_THUMBNAIL_FIXTURE": str(source_image), "FAKE_YTDLP_SLEEP": "1.2", "TESSERACT_BINARY": str(ocr),
        })["result"]
        tasks = [item for item in started["tasks"] if item["pipeline"] == "thumbnail"]
        for task in tasks:
            self.wait_for_queue_state(batch["batch"]["id"], task["id"], {"waiting_for_thumbnail_review"})
        tasks = self.request("queue.status", {"batch_id": batch["batch"]["id"]})["result"]["tasks"]
        relevant = [item for item in tasks if item["pipeline"] == "thumbnail"]
        start_times = [datetime.fromisoformat(item["started_at"]) for item in relevant]
        self.assertEqual(len(start_times), 2)
        self.assertLess(abs((start_times[0] - start_times[1]).total_seconds()), 1.0)


if __name__ == "__main__":
    unittest.main()
