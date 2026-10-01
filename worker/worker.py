from __future__ import annotations

import argparse
import csv
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import html
import json
import os
import platform
import queue as thread_queue
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SCHEMA_VERSION = 8

DEFAULT_SUBTITLE_STYLE = {
    "font_family": "Arial",
    "font_size": 40,
    "text_color": "#FFFFFF",
    "background_enabled": True,
    "background_color": "#000000",
    "background_opacity": 0.58,
    "outline_color": "#000000",
    "outline_width": 2,
    "shadow": 1,
    "alignment": "bottom-center",
    "position_x": 50,
    "position_y": 88,
}

DEFAULT_THUMBNAIL_STYLE = {
    "background_type": "gradient",
    "background_color": "#183F35",
    "gradient_end_color": "#A9B96B",
    "gradient_angle": 35,
    "font_family": "Arial",
    "font_size": 84,
    "text_color": "#FFFFFF",
    "outline_color": "#11221B",
    "outline_width": 3,
    "shadow": 4,
    "alignment": "center",
    "position_x": 50,
    "position_y": 54,
    "max_width_percent": 84,
    "fit_mode": "shrink",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_slug(value: str) -> str:
    value = value.replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "channel"


def open_database(database_path: str) -> sqlite3.Connection:
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            subtitle_languages_json TEXT NOT NULL DEFAULT '[]',
            default_subtitle_preset_id TEXT,
            thumbnail_mode TEXT NOT NULL DEFAULT 'auto',
            ocr_languages_json TEXT NOT NULL DEFAULT '["eng"]',
            default_thumbnail_preset_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_assets (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            duration_seconds REAL,
            width INTEGER,
            height INTEGER,
            frame_rate REAL,
            codec TEXT,
            probe_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS channel_backgrounds (
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            asset_id TEXT NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            PRIMARY KEY (channel_id, asset_id)
        );

        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            workflow_mode TEXT NOT NULL DEFAULT 'render',
            state TEXT NOT NULL DEFAULT 'draft',
            import_source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            thumbnail_mode_override TEXT
        );

        CREATE TABLE IF NOT EXISTS video_jobs (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
            channel_id TEXT REFERENCES channels(id) ON DELETE SET NULL,
            imported_channel_name TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL,
            canonical_url TEXT,
            video_id TEXT,
            title TEXT,
            duration_seconds REAL,
            thumbnail_url TEXT,
            metadata_status TEXT NOT NULL DEFAULT 'pending',
            metadata_error TEXT,
            row_number INTEGER NOT NULL,
            position INTEGER NOT NULL,
            validation_code TEXT NOT NULL,
            duplicate_of_job_id TEXT REFERENCES video_jobs(id) ON DELETE SET NULL,
            background_asset_id TEXT REFERENCES media_assets(id) ON DELETE SET NULL,
            background_locked INTEGER NOT NULL DEFAULT 0,
            subtitle_tracks_json TEXT NOT NULL DEFAULT '{"creator":[],"automatic":[]}',
            subtitle_language_override_json TEXT NOT NULL DEFAULT '[]',
            subtitle_language TEXT,
            subtitle_source TEXT,
            subtitle_decision TEXT NOT NULL DEFAULT 'unresolved',
            supplied_subtitle_path TEXT,
            subtitle_error TEXT,
            include_video_source INTEGER NOT NULL DEFAULT 0,
            source_audio_path TEXT,
            source_video_path TEXT,
            source_thumbnail_path TEXT,
            download_status TEXT NOT NULL DEFAULT 'not_started',
            download_error TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(batch_id, position)
        );
        CREATE INDEX IF NOT EXISTS video_jobs_batch_position ON video_jobs(batch_id, position);
        CREATE INDEX IF NOT EXISTS video_jobs_channel_history ON video_jobs(channel_id, background_asset_id);

        CREATE TABLE IF NOT EXISTS job_artifacts (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(job_id, kind, path)
        );

        CREATE TABLE IF NOT EXISTS queue_tasks (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
            job_id TEXT NOT NULL REFERENCES video_jobs(id) ON DELETE CASCADE,
            pipeline TEXT NOT NULL DEFAULT 'video',
            state TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress REAL NOT NULL DEFAULT 0,
            output_root TEXT NOT NULL,
            include_video_source INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS queue_tasks_state_created ON queue_tasks(state, created_at);
        CREATE INDEX IF NOT EXISTS queue_tasks_batch_created ON queue_tasks(batch_id, created_at);
        CREATE TABLE IF NOT EXISTS queue_task_logs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES queue_tasks(id) ON DELETE CASCADE,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS queue_runtime (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            state TEXT NOT NULL DEFAULT 'stopped',
            pid INTEGER,
            token TEXT,
            heartbeat_at TEXT,
            max_concurrency INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subtitle_presets (
            id TEXT PRIMARY KEY,
            channel_id TEXT REFERENCES channels(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            style_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS thumbnail_presets (
            id TEXT PRIMARY KEY,
            owner_channel_id TEXT REFERENCES channels(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            background_type TEXT NOT NULL,
            background_color TEXT NOT NULL,
            gradient_end_color TEXT NOT NULL,
            gradient_angle INTEGER NOT NULL,
            font_family TEXT NOT NULL,
            font_size INTEGER NOT NULL,
            text_color TEXT NOT NULL,
            outline_color TEXT NOT NULL,
            outline_width REAL NOT NULL,
            shadow REAL NOT NULL,
            alignment TEXT NOT NULL,
            position_x INTEGER NOT NULL,
            position_y INTEGER NOT NULL,
            max_width_percent INTEGER NOT NULL,
            fit_mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channel_thumbnail_presets (
            channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            preset_id TEXT NOT NULL REFERENCES thumbnail_presets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            PRIMARY KEY(channel_id, preset_id)
        );
        CREATE TABLE IF NOT EXISTS batch_thumbnail_presets (
            batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
            preset_id TEXT NOT NULL REFERENCES thumbnail_presets(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            PRIMARY KEY(batch_id, preset_id)
        );
        """
    )
    ensure_database_column(connection, "channels", "subtitle_languages_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_database_column(connection, "channels", "default_subtitle_preset_id", "TEXT")
    ensure_database_column(connection, "channels", "thumbnail_mode", "TEXT NOT NULL DEFAULT 'auto'")
    ensure_database_column(connection, "channels", "ocr_languages_json", "TEXT NOT NULL DEFAULT '[\"eng\"]'")
    ensure_database_column(connection, "channels", "default_thumbnail_preset_id", "TEXT")
    ensure_database_column(connection, "batches", "workflow_mode", "TEXT NOT NULL DEFAULT 'render'")
    ensure_database_column(connection, "batches", "thumbnail_mode_override", "TEXT")
    for column, declaration in (
        ("subtitle_tracks_json", "TEXT NOT NULL DEFAULT '{\"creator\":[],\"automatic\":[]}'"),
        ("subtitle_language_override_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("subtitle_language", "TEXT"),
        ("subtitle_source", "TEXT"),
        ("subtitle_decision", "TEXT NOT NULL DEFAULT 'unresolved'"),
        ("supplied_subtitle_path", "TEXT"),
        ("subtitle_error", "TEXT"),
        ("include_video_source", "INTEGER NOT NULL DEFAULT 0"),
        ("source_audio_path", "TEXT"),
        ("source_video_path", "TEXT"),
        ("source_thumbnail_path", "TEXT"),
        ("download_status", "TEXT NOT NULL DEFAULT 'not_started'"),
        ("download_error", "TEXT"),
        ("download_progress", "REAL"),
        ("subtitle_preset_id", "TEXT"),
        ("output_profile_json", "TEXT NOT NULL DEFAULT '{\"profile\":\"720p\",\"frame_preference\":null,\"fit_mode\":\"crop\"}'"),
        ("render_status", "TEXT NOT NULL DEFAULT 'not_started'"),
        ("render_error", "TEXT"),
        ("render_progress", "REAL"),
        ("output_video_path", "TEXT"),
        ("srt_sidecar_path", "TEXT"),
        ("encoder_used", "TEXT"),
        ("thumbnail_mode_override", "TEXT"),
        ("thumbnail_mode_snapshot", "TEXT NOT NULL DEFAULT 'auto'"),
        ("thumbnail_preset_id", "TEXT"),
        ("thumbnail_preset_locked", "INTEGER NOT NULL DEFAULT 0"),
        ("thumbnail_ocr_text", "TEXT NOT NULL DEFAULT ''"),
        ("thumbnail_ocr_confidence", "REAL"),
        ("thumbnail_ocr_status", "TEXT NOT NULL DEFAULT 'not_started'"),
        ("thumbnail_text", "TEXT NOT NULL DEFAULT ''"),
        ("thumbnail_output_path", "TEXT"),
        ("thumbnail_error", "TEXT"),
        ("thumbnail_progress", "REAL"),
        ("thumbnail_ocr_languages_json", "TEXT NOT NULL DEFAULT '[\"eng\"]'"),
    ):
        ensure_database_column(connection, "video_jobs", column, declaration)
    connection.execute(
        "INSERT OR IGNORE INTO queue_runtime(id, state, updated_at) VALUES (1, 'stopped', ?)",
        (utc_now(),),
    )
    ensure_database_column(connection, "queue_tasks", "pipeline", "TEXT NOT NULL DEFAULT 'video'")
    ensure_database_column(connection, "queue_runtime", "max_concurrency", "INTEGER NOT NULL DEFAULT 1")
    for row in connection.execute("SELECT id, name FROM channels WHERE default_subtitle_preset_id IS NULL").fetchall():
        preset = create_subtitle_preset(connection, row["id"], f"{row['name']} default", DEFAULT_SUBTITLE_STYLE)
        connection.execute("UPDATE channels SET default_subtitle_preset_id = ? WHERE id = ?", (preset["id"], row["id"]))
    for row in connection.execute("SELECT id, name FROM channels WHERE default_thumbnail_preset_id IS NULL").fetchall():
        preset = create_thumbnail_preset(connection, row["id"], f"{row['name']} default", DEFAULT_THUMBNAIL_STYLE)
        connection.execute("UPDATE channels SET default_thumbnail_preset_id = ? WHERE id = ?", (preset["id"], row["id"]))
        connection.execute("INSERT OR IGNORE INTO channel_thumbnail_presets(channel_id, preset_id, position) VALUES (?, ?, 0)", (row["id"], preset["id"]))
    connection.execute(
        "INSERT OR REPLACE INTO app_meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def ensure_database_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    declaration: str,
) -> None:
    columns = {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        try:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {declaration}")
        except sqlite3.OperationalError:
            refreshed_columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if column_name not in refreshed_columns:
                raise


def ensure_channel(connection: sqlite3.Connection, channel_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM channels WHERE id = ?",
        (channel_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Channel was not found.")
    return row


def validate_subtitle_style(style: Any) -> dict[str, Any]:
    if not isinstance(style, dict):
        raise ValueError("Subtitle style must be an object.")
    value = {**DEFAULT_SUBTITLE_STYLE, **style}
    color_fields = ("text_color", "background_color", "outline_color")
    for key in color_fields:
        if not isinstance(value[key], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value[key]):
            raise ValueError(f"{key} must be a six-digit hex color such as #FFFFFF.")
        value[key] = value[key].upper()
    value["font_family"] = str(value["font_family"]).strip()
    if not value["font_family"] or len(value["font_family"]) > 80 or any(ch in value["font_family"] for ch in "{},\n\r"):
        raise ValueError("Choose a valid installed font family.")
    try:
        value["font_size"] = int(value["font_size"])
        value["background_opacity"] = float(value["background_opacity"])
        value["outline_width"] = float(value["outline_width"])
        value["shadow"] = float(value["shadow"])
        value["position_x"] = int(value["position_x"])
        value["position_y"] = int(value["position_y"])
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Subtitle style values must be valid numbers.") from error
    if not 12 <= value["font_size"] <= 120:
        raise ValueError("Subtitle font size must be between 12 and 120.")
    if not 0 <= value["background_opacity"] <= 1:
        raise ValueError("Subtitle background opacity must be between 0 and 1.")
    if not 0 <= value["outline_width"] <= 12 or not 0 <= value["shadow"] <= 12:
        raise ValueError("Subtitle outline and shadow must be between 0 and 12.")
    if not 0 <= value["position_x"] <= 100 or not 0 <= value["position_y"] <= 100:
        raise ValueError("Subtitle position values must be between 0 and 100.")
    if value["alignment"] not in {"top-left", "top-center", "top-right", "middle-left", "middle-center", "middle-right", "bottom-left", "bottom-center", "bottom-right"}:
        raise ValueError("Choose one of the nine subtitle alignment positions.")
    value["background_enabled"] = bool(value["background_enabled"])
    return value


def inspect_font_family(font_family: str) -> dict[str, Any]:
    family = str(font_family).strip()
    if not family or len(family) > 80 or any(char in family for char in "{},\n\r"):
        raise ValueError("Enter a valid font family to check.")
    binary = shutil.which("fc-match")
    if binary:
        try:
            completed = subprocess.run(
                [binary, "--format", "%{family[0]}\\t%{file}\\n", family],
                capture_output=True, text=True, check=False, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"Font lookup failed: {error}") from error
        if completed.returncode == 0 and completed.stdout.strip():
            matched, _, path = completed.stdout.strip().partition("\t")
            available = matched.strip().casefold() == family.casefold()
            return {
                "font_family": family,
                "available": available,
                "matched_family": matched.strip() or None,
                "font_path": path.strip() or None,
                "warning": None if available else f"{family} is not installed; the subtitle renderer will use {matched.strip() or 'a fallback font'}.",
            }
    font_directories: list[Path] = []
    if sys.platform == "darwin":
        font_directories = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    elif os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        font_directories = [Path(windir) / "Fonts"]
    else:
        font_directories = [Path.home() / ".fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    expected = re.sub(r"[^a-z0-9]", "", family.casefold())
    for directory in font_directories:
        if not directory.is_dir():
            continue
        try:
            candidates = directory.rglob("*")
            for path in candidates:
                if path.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                    stem = re.sub(r"[^a-z0-9]", "", path.stem.casefold())
                    if stem == expected:
                        return {"font_family": family, "available": True, "matched_family": family, "font_path": str(path), "warning": None}
        except OSError:
            continue
    return {"font_family": family, "available": None, "matched_family": None, "font_path": None, "warning": "Could not verify this font on this platform; libass may substitute a system font during render."}


def validate_thumbnail_preset(style: Any) -> dict[str, Any]:
    if not isinstance(style, dict):
        raise ValueError("Thumbnail preset style must be an object.")
    value = {**DEFAULT_THUMBNAIL_STYLE, **style}
    for key in ("background_color", "gradient_end_color", "text_color", "outline_color"):
        if not isinstance(value[key], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value[key]):
            raise ValueError(f"{key} must be a six-digit hex color such as #FFFFFF.")
        value[key] = value[key].upper()
    value["font_family"] = str(value["font_family"]).strip()
    if not value["font_family"] or len(value["font_family"]) > 80 or any(char in value["font_family"] for char in "{},\n\r"):
        raise ValueError("Choose a valid thumbnail font family.")
    try:
        for key in ("gradient_angle", "font_size", "position_x", "position_y", "max_width_percent"):
            value[key] = int(value[key])
        for key in ("outline_width", "shadow"):
            value[key] = float(value[key])
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Thumbnail preset values must be valid numbers.") from error
    if value["background_type"] not in {"solid", "gradient"}:
        raise ValueError("Thumbnail background type must be solid or gradient.")
    if not 0 <= value["gradient_angle"] <= 360:
        raise ValueError("Gradient angle must be between 0 and 360 degrees.")
    if not 24 <= value["font_size"] <= 200:
        raise ValueError("Thumbnail font size must be between 24 and 200 pixels.")
    if not 0 <= value["outline_width"] <= 16 or not 0 <= value["shadow"] <= 32:
        raise ValueError("Thumbnail outline and shadow must be between 0 and 32.")
    if value["alignment"] not in {"left", "center", "right"}:
        raise ValueError("Thumbnail alignment must be left, center, or right.")
    if not 0 <= value["position_x"] <= 100 or not 0 <= value["position_y"] <= 100:
        raise ValueError("Thumbnail position must be between 0 and 100 percent.")
    if not 30 <= value["max_width_percent"] <= 95:
        raise ValueError("Thumbnail text width must be between 30 and 95 percent.")
    if value["fit_mode"] not in {"shrink", "wrap"}:
        raise ValueError("Thumbnail text fit mode must be shrink or wrap.")
    return value


def thumbnail_preset_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "owner_channel_id": row["owner_channel_id"], "name": row["name"],
        "style": {key: row[key] for key in (
            "background_type", "background_color", "gradient_end_color", "gradient_angle", "font_family",
            "font_size", "text_color", "outline_color", "outline_width", "shadow", "alignment",
            "position_x", "position_y", "max_width_percent", "fit_mode",
        )},
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def get_thumbnail_preset(connection: sqlite3.Connection, preset_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM thumbnail_presets WHERE id = ?", (preset_id,)).fetchone()
    if row is None:
        raise ValueError("Thumbnail preset was not found.")
    return row


def create_thumbnail_preset(
    connection: sqlite3.Connection,
    owner_channel_id: str | None,
    name: str,
    style: Any,
) -> dict[str, Any]:
    if owner_channel_id:
        ensure_channel(connection, owner_channel_id)
    normalized_name = str(name).strip()
    if not normalized_name or len(normalized_name) > 80:
        raise ValueError("Thumbnail preset name must be between 1 and 80 characters.")
    normalized_style = validate_thumbnail_preset(style)
    now = utc_now()
    preset_id = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO thumbnail_presets(
            id, owner_channel_id, name, background_type, background_color, gradient_end_color,
            gradient_angle, font_family, font_size, text_color, outline_color, outline_width,
            shadow, alignment, position_x, position_y, max_width_percent, fit_mode, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (preset_id, owner_channel_id, normalized_name, normalized_style["background_type"],
         normalized_style["background_color"], normalized_style["gradient_end_color"],
         normalized_style["gradient_angle"], normalized_style["font_family"], normalized_style["font_size"],
         normalized_style["text_color"], normalized_style["outline_color"], normalized_style["outline_width"],
         normalized_style["shadow"], normalized_style["alignment"], normalized_style["position_x"],
         normalized_style["position_y"], normalized_style["max_width_percent"], normalized_style["fit_mode"], now, now),
    )
    return thumbnail_preset_view(get_thumbnail_preset(connection, preset_id))


def thumbnail_preset_pool(connection: sqlite3.Connection, channel_id: str | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
    if batch_id:
        batch = connection.execute("SELECT id FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if batch is None:
            raise ValueError("Batch was not found.")
        batch_pool = connection.execute("SELECT preset_id FROM batch_thumbnail_presets WHERE batch_id = ? ORDER BY position", (batch_id,)).fetchall()
        if batch_pool:
            ids = [item["preset_id"] for item in batch_pool]
        else:
            channel_ids = [item[0] for item in connection.execute("SELECT DISTINCT channel_id FROM video_jobs WHERE batch_id = ? AND channel_id IS NOT NULL", (batch_id,)).fetchall()]
            ids = []
            for current_channel_id in channel_ids:
                ids.extend(item["preset_id"] for item in connection.execute("SELECT preset_id FROM channel_thumbnail_presets WHERE channel_id = ? ORDER BY position", (current_channel_id,)).fetchall())
        ids = list(dict.fromkeys(ids))
        if not ids:
            return []
        by_id = {row["id"]: row for row in connection.execute(f"SELECT * FROM thumbnail_presets WHERE id IN ({','.join('?' for _ in ids)})", ids).fetchall()}
        rows = [by_id[preset_id] for preset_id in ids if preset_id in by_id]
    elif channel_id:
        ensure_channel(connection, channel_id)
        rows = connection.execute(
            "SELECT presets.* FROM channel_thumbnail_presets AS links JOIN thumbnail_presets AS presets ON presets.id = links.preset_id WHERE links.channel_id = ? ORDER BY links.position, presets.name COLLATE NOCASE",
            (channel_id,),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM thumbnail_presets WHERE owner_channel_id IS NULL ORDER BY name COLLATE NOCASE").fetchall()
    return [thumbnail_preset_view(row) for row in rows]


def list_thumbnail_presets(connection: sqlite3.Connection, params: dict[str, Any]) -> list[dict[str, Any]]:
    channel_id = params.get("channel_id")
    batch_id = params.get("batch_id")
    if params.get("all"):
        rows = connection.execute("SELECT * FROM thumbnail_presets ORDER BY name COLLATE NOCASE, id").fetchall()
        return [thumbnail_preset_view(row) for row in rows]
    return thumbnail_preset_pool(connection, str(channel_id) if channel_id else None, str(batch_id) if batch_id else None)


def link_thumbnail_preset_to_channel(connection: sqlite3.Connection, channel_id: str, preset_id: str) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    preset = get_thumbnail_preset(connection, preset_id)
    position = connection.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM channel_thumbnail_presets WHERE channel_id = ?", (channel_id,)).fetchone()[0]
    connection.execute("INSERT OR IGNORE INTO channel_thumbnail_presets(channel_id, preset_id, position) VALUES (?, ?, ?)", (channel_id, preset_id, position))
    connection.commit()
    return {"channel_id": channel_id, "preset_id": preset["id"], "presets": thumbnail_preset_pool(connection, channel_id)}


def set_channel_thumbnail_settings(connection: sqlite3.Connection, channel_id: str, mode: str, languages: Any) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    if mode not in {"auto", "manual", "skip"}:
        raise ValueError("Thumbnail mode must be Auto, Manual, or Skip.")
    if not isinstance(languages, list):
        raise ValueError("OCR language preferences must be a list of Tesseract language codes.")
    normalized: list[str] = []
    seen: set[str] = set()
    for supplied in languages:
        language = str(supplied).strip()
        if not language:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_]{2,20}", language):
            raise ValueError(f"Invalid Tesseract language code: {language}")
        if language.casefold() not in seen:
            seen.add(language.casefold())
            normalized.append(language)
    if not normalized:
        normalized = ["eng"]
    if len(normalized) > 8:
        raise ValueError("Choose no more than eight OCR languages.")
    connection.execute("UPDATE channels SET thumbnail_mode = ?, ocr_languages_json = ?, updated_at = ? WHERE id = ?", (mode, json.dumps(normalized), utc_now(), channel_id))
    connection.commit()
    return channel_view(connection, ensure_channel(connection, channel_id))


def update_thumbnail_preset(connection: sqlite3.Connection, preset_id: str, name: str, style: Any) -> dict[str, Any]:
    current = get_thumbnail_preset(connection, preset_id)
    normalized_name = str(name).strip()
    if not normalized_name or len(normalized_name) > 80:
        raise ValueError("Thumbnail preset name must be between 1 and 80 characters.")
    normalized = validate_thumbnail_preset(style)
    assignments = ", ".join(f"{key} = ?" for key in normalized)
    connection.execute(f"UPDATE thumbnail_presets SET name = ?, {assignments}, updated_at = ? WHERE id = ?", (normalized_name, *normalized.values(), utc_now(), preset_id))
    stale_jobs = [row["id"] for row in connection.execute("SELECT id FROM video_jobs WHERE thumbnail_preset_id = ? AND thumbnail_ocr_status = 'complete'", (preset_id,)).fetchall()]
    connection.execute("UPDATE video_jobs SET thumbnail_output_path = NULL, thumbnail_ocr_status = 'confirmed' WHERE thumbnail_preset_id = ? AND thumbnail_ocr_status = 'complete'", (preset_id,))
    connection.executemany("DELETE FROM job_artifacts WHERE job_id = ? AND kind = 'thumbnail_output'", [(job_id,) for job_id in stale_jobs])
    return thumbnail_preset_view(get_thumbnail_preset(connection, current["id"]))


def set_channel_default_thumbnail_preset(connection: sqlite3.Connection, channel_id: str, preset_id: str) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    get_thumbnail_preset(connection, preset_id)
    membership = connection.execute("SELECT 1 FROM channel_thumbnail_presets WHERE channel_id = ? AND preset_id = ?", (channel_id, preset_id)).fetchone()
    if not membership:
        link_thumbnail_preset_to_channel(connection, channel_id, preset_id)
    connection.execute("UPDATE channels SET default_thumbnail_preset_id = ?, updated_at = ? WHERE id = ?", (preset_id, utc_now(), channel_id))
    connection.execute("UPDATE video_jobs SET thumbnail_preset_id = ?, thumbnail_preset_locked = 0 WHERE channel_id = ? AND thumbnail_preset_locked = 0 AND thumbnail_ocr_status NOT IN ('complete', 'skipped', 'manual') AND batch_id IN (SELECT id FROM batches WHERE state = 'draft')", (preset_id, channel_id))
    connection.commit()
    return channel_view(connection, ensure_channel(connection, channel_id))


def assign_thumbnail_presets_to_channels(connection: sqlite3.Connection, preset_id: str, channel_ids: Any) -> dict[str, Any]:
    get_thumbnail_preset(connection, preset_id)
    if not isinstance(channel_ids, list):
        raise ValueError("Channel assignments must be a list of Channel ids.")
    normalized_ids = list(dict.fromkeys(str(channel_id) for channel_id in channel_ids))
    for channel_id in normalized_ids:
        ensure_channel(connection, channel_id)
    existing = [row["channel_id"] for row in connection.execute("SELECT channel_id FROM channel_thumbnail_presets WHERE preset_id = ?", (preset_id,)).fetchall()]
    changed_channels = set(existing) | set(normalized_ids)
    preset = get_thumbnail_preset(connection, preset_id)
    for channel_id in normalized_ids:
        link_thumbnail_preset_to_channel(connection, channel_id, preset_id)
    removed = set(existing) - set(normalized_ids)
    for channel_id in removed:
        channel = ensure_channel(connection, channel_id)
        connection.execute("DELETE FROM channel_thumbnail_presets WHERE channel_id = ? AND preset_id = ?", (channel_id, preset_id))
        if channel["default_thumbnail_preset_id"] == preset_id:
            next_default = connection.execute("SELECT preset_id FROM channel_thumbnail_presets WHERE channel_id = ? ORDER BY position LIMIT 1", (channel_id,)).fetchone()
            if next_default:
                connection.execute("UPDATE channels SET default_thumbnail_preset_id = ?, updated_at = ? WHERE id = ?", (next_default["preset_id"], utc_now(), channel_id))
            else:
                replacement = create_thumbnail_preset(connection, channel_id, f"{channel['name']} default", {key: preset[key] for key in DEFAULT_THUMBNAIL_STYLE})
                connection.execute("UPDATE channels SET default_thumbnail_preset_id = ? WHERE id = ?", (replacement["id"], channel_id))
                connection.execute("INSERT INTO channel_thumbnail_presets(channel_id, preset_id, position) VALUES (?, ?, 0)", (channel_id, replacement["id"]))
    for affected_channel_id in changed_channels:
        draft_ids = [row["id"] for row in connection.execute(
            "SELECT DISTINCT batches.id FROM batches JOIN video_jobs ON video_jobs.batch_id = batches.id WHERE batches.state = 'draft' AND video_jobs.channel_id = ?",
            (affected_channel_id,),
        ).fetchall()]
        for draft_id in draft_ids:
            plan_batch_thumbnails(connection, draft_id)
    connection.commit()
    return {"preset_id": preset_id, "channel_ids": normalized_ids}


def thumbnail_preset_channels(connection: sqlite3.Connection, preset_id: str) -> list[str]:
    get_thumbnail_preset(connection, preset_id)
    return [row["channel_id"] for row in connection.execute("SELECT channel_id FROM channel_thumbnail_presets WHERE preset_id = ? ORDER BY channel_id", (preset_id,)).fetchall()]


def set_batch_thumbnail_mode(connection: sqlite3.Connection, batch_id: str, mode: str | None) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Batch thumbnail defaults are fixed after confirmation; use per-job overrides instead.")
    if mode is not None and mode not in {"auto", "manual", "skip"}:
        raise ValueError("Thumbnail mode must be Auto, Manual, Skip, or inherit from each Channel.")
    connection.execute("UPDATE batches SET thumbnail_mode_override = ? WHERE id = ?", (mode, batch_id))
    connection.commit()
    return plan_batch_thumbnails(connection, batch_id)


def set_batch_thumbnail_pool(connection: sqlite3.Connection, batch_id: str, preset_ids: Any) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Batch thumbnail pools are fixed after confirmation.")
    if not isinstance(preset_ids, list):
        raise ValueError("Batch thumbnail presets must be a list of preset ids.")
    normalized = list(dict.fromkeys(str(preset_id) for preset_id in preset_ids))
    if len(normalized) > 100:
        raise ValueError("A Batch can use no more than 100 thumbnail presets.")
    for preset_id in normalized:
        get_thumbnail_preset(connection, preset_id)
    connection.execute("DELETE FROM batch_thumbnail_presets WHERE batch_id = ?", (batch_id,))
    connection.executemany("INSERT INTO batch_thumbnail_presets(batch_id, preset_id, position) VALUES (?, ?, ?)", [(batch_id, preset_id, position) for position, preset_id in enumerate(normalized)])
    connection.commit()
    return plan_batch_thumbnails(connection, batch_id)


def set_job_thumbnail_mode(connection: sqlite3.Connection, job_id: str, mode: str | None) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if mode is not None and mode not in {"auto", "manual", "skip"}:
        raise ValueError("Thumbnail mode must be Auto, Manual, Skip, or inherit.")
    connection.execute("UPDATE video_jobs SET thumbnail_mode_override = ?, thumbnail_ocr_status = CASE WHEN ? = 'skip' THEN 'skipped' ELSE 'not_started' END, thumbnail_error = NULL, thumbnail_output_path = NULL WHERE id = ?", (mode, mode, job_id))
    connection.commit()
    return job_view(connection, connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone())


def set_job_thumbnail_preset(connection: sqlite3.Connection, job_id: str, preset_id: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    preset = get_thumbnail_preset(connection, preset_id)
    if not job["channel_id"]:
        raise ValueError("Assign this job to a Channel before choosing a thumbnail preset.")
    available = {item["id"] for item in thumbnail_preset_pool(connection, job["channel_id"])}
    available.update(item["id"] for item in thumbnail_preset_pool(connection, batch_id=job["batch_id"]))
    if preset["id"] not in available:
        raise ValueError("Add this preset to the job's Channel or Batch pool before selecting it.")
    connection.execute("UPDATE video_jobs SET thumbnail_preset_id = ?, thumbnail_preset_locked = 1, thumbnail_output_path = NULL, thumbnail_ocr_status = CASE WHEN thumbnail_ocr_text != '' THEN 'confirmed' ELSE thumbnail_ocr_status END WHERE id = ?", (preset_id, job_id))
    connection.execute("DELETE FROM job_artifacts WHERE job_id = ? AND kind = 'thumbnail_output'", (job_id,))
    connection.commit()
    return job_view(connection, connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone())


def effective_thumbnail_mode(connection: sqlite3.Connection, row: sqlite3.Row) -> str:
    if row["thumbnail_mode_override"]:
        return row["thumbnail_mode_override"]
    batch = connection.execute("SELECT state, thumbnail_mode_override FROM batches WHERE id = ?", (row["batch_id"],)).fetchone()
    if batch and batch["state"] == "confirmed":
        return row["thumbnail_mode_snapshot"] or "auto"
    if batch and batch["thumbnail_mode_override"]:
        return batch["thumbnail_mode_override"]
    if row["channel_id"]:
        channel = connection.execute("SELECT thumbnail_mode FROM channels WHERE id = ?", (row["channel_id"],)).fetchone()
        if channel:
            return channel["thumbnail_mode"]
    return "auto"


def effective_thumbnail_languages(connection: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
    batch = connection.execute("SELECT state FROM batches WHERE id = ?", (row["batch_id"],)).fetchone()
    if batch and batch["state"] == "confirmed":
        return json.loads(row["thumbnail_ocr_languages_json"])
    if row["channel_id"]:
        channel = connection.execute("SELECT ocr_languages_json FROM channels WHERE id = ?", (row["channel_id"],)).fetchone()
        if channel:
            return json.loads(channel["ocr_languages_json"] or '["eng"]')
    return ["eng"]


def plan_batch_thumbnails(connection: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        return get_batch(connection, batch_id)
    rows = connection.execute("SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position", (batch_id,)).fetchall()
    batch_pool_rows = connection.execute("SELECT preset_id FROM batch_thumbnail_presets WHERE batch_id = ? ORDER BY position", (batch_id,)).fetchall()
    batch_pool = [item["preset_id"] for item in batch_pool_rows]
    channel_ids = sorted({row["channel_id"] for row in rows if row["channel_id"]})
    plans: dict[str, tuple[dict[str, int], str | None, random.Random, list[str]]] = {}
    for channel_id in channel_ids:
        pool = batch_pool or [item["preset_id"] for item in connection.execute(
            "SELECT preset_id FROM channel_thumbnail_presets WHERE channel_id = ? ORDER BY position", (channel_id,)
        ).fetchall()]
        available_ids = list(dict.fromkeys(pool))
        historical = connection.execute(
            """
            SELECT jobs.thumbnail_preset_id, COUNT(*) AS uses
            FROM video_jobs AS jobs JOIN batches ON batches.id = jobs.batch_id
            WHERE jobs.channel_id = ? AND jobs.thumbnail_preset_id IS NOT NULL
              AND batches.state = 'confirmed'
              AND COALESCE(jobs.thumbnail_mode_override, jobs.thumbnail_mode_snapshot) = 'auto'
            GROUP BY jobs.thumbnail_preset_id
            """, (channel_id,),
        ).fetchall()
        usage = {item["thumbnail_preset_id"]: int(item["uses"]) for item in historical}
        latest = connection.execute(
            """
            SELECT jobs.thumbnail_preset_id FROM video_jobs AS jobs JOIN batches ON batches.id = jobs.batch_id
            WHERE jobs.channel_id = ? AND jobs.thumbnail_preset_id IS NOT NULL AND batches.state = 'confirmed'
              AND COALESCE(jobs.thumbnail_mode_override, jobs.thumbnail_mode_snapshot) = 'auto'
            ORDER BY batches.confirmed_at DESC, jobs.position DESC LIMIT 1
            """, (channel_id,),
        ).fetchone()
        for preset_id in available_ids:
            usage.setdefault(preset_id, 0)
        for current_job in rows:
            selected = current_job["thumbnail_preset_id"]
            if current_job["channel_id"] == channel_id and effective_thumbnail_mode(connection, current_job) == "auto" and current_job["thumbnail_preset_locked"] and selected in available_ids and current_job["validation_code"] == "valid" and not current_job["duplicate_of_job_id"]:
                usage[selected] = usage.get(selected, 0) + 1
        plans[channel_id] = usage, latest["thumbnail_preset_id"] if latest else None, random.Random(f"thumb:{batch_id}:{channel_id}"), available_ids

    for row in rows:
        channel_id = row["channel_id"]
        if not channel_id or row["validation_code"] != "valid" or row["duplicate_of_job_id"]:
            continue
        if effective_thumbnail_mode(connection, row) != "auto":
            continue
        usage, previous, randomizer, available_ids = plans[channel_id]
        selected = row["thumbnail_preset_id"]
        if row["thumbnail_preset_locked"]:
            if selected in available_ids:
                plans[channel_id] = usage, selected, randomizer, available_ids
            continue
        if not available_ids:
            continue
        minimum = min(usage.get(preset_id, 0) for preset_id in available_ids)
        candidates = [preset_id for preset_id in available_ids if usage.get(preset_id, 0) == minimum]
        without_repeat = [preset_id for preset_id in candidates if preset_id != previous]
        if without_repeat:
            candidates = without_repeat
        randomizer.shuffle(candidates)
        selected = candidates[0]
        connection.execute("UPDATE video_jobs SET thumbnail_preset_id = ? WHERE id = ?", (selected, row["id"]))
        usage[selected] = usage.get(selected, 0) + 1
        plans[channel_id] = usage, selected, randomizer, available_ids
    connection.commit()
    return get_batch(connection, batch_id)


def download_source_thumbnail(
    connection: sqlite3.Connection,
    job_id: str,
    output_root: str | None = None,
    queue_task_id: str | None = None,
) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if not job["canonical_url"]:
        raise ValueError("Fix this video's YouTube URL before downloading its thumbnail.")
    if effective_thumbnail_mode(connection, job) == "skip":
        raise ValueError("Thumbnail handling is set to Skip for this job.")
    binary = os.environ.get("YTDLP_BINARY") or shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if not binary:
        raise ValueError("yt-dlp was not found. Install it or configure YTDLP_BINARY.")
    if output_root:
        batch = connection.execute("SELECT state FROM batches WHERE id = ?", (job["batch_id"],)).fetchone()
        if not batch or batch["state"] != "confirmed":
            raise ValueError("Confirm the Batch before queueing thumbnail work.")
        directory = job_download_directory(connection, job, output_root)
    elif job["source_audio_path"] or job["source_video_path"]:
        directory = Path(job["source_audio_path"] or job["source_video_path"]).parent
    else:
        raise ValueError("Choose an output folder to save the source thumbnail.")
    template = str(directory / "source.%(ext)s")
    command = [binary, "--no-warnings", "--no-call-home", "--no-playlist", "--skip-download", "--output", template, "--write-thumbnail", "--convert-thumbnails", "jpg", job["canonical_url"]]
    if queue_task_id:
        queue_set_stage(connection, queue_task_id, "thumbnail_downloading", 0.05)
    run_ytdlp(command, connection=connection, queue_task_id=queue_task_id, progress_base=0.05, progress_span=0.55)
    thumbnail_file = next((path for path in directory.glob("source.*") if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}), None)
    if not thumbnail_file:
        raise ValueError("yt-dlp could not save a thumbnail for this video.")
    connection.execute("UPDATE video_jobs SET source_thumbnail_path = ?, thumbnail_error = NULL WHERE id = ?", (str(thumbnail_file), job_id))
    connection.execute("DELETE FROM job_artifacts WHERE job_id = ? AND kind = 'source_thumbnail'", (job_id,))
    add_job_artifact(connection, job_id, "source_thumbnail", str(thumbnail_file))
    mode = effective_thumbnail_mode(connection, job)
    if mode == "auto":
        if queue_task_id:
            queue_set_stage(connection, queue_task_id, "thumbnail_ocr", 0.62)
        text, confidence, error = recognize_thumbnail_text(str(thumbnail_file), effective_thumbnail_languages(connection, job))
        status = "awaiting_confirmation" if text and confidence is not None and confidence >= 0.55 and not error else "needs_review"
        connection.execute("UPDATE video_jobs SET thumbnail_ocr_text = ?, thumbnail_ocr_confidence = ?, thumbnail_text = ?, thumbnail_ocr_status = ?, thumbnail_error = ? WHERE id = ?", (text, confidence, text, status, error, job_id))
    else:
        connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'manual', thumbnail_error = NULL WHERE id = ?", (job_id,))
    if queue_task_id:
        connection.execute("UPDATE video_jobs SET thumbnail_progress = 0.68 WHERE id = ?", (job_id,))
    connection.commit()
    return job_view(connection, connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone())


def set_job_thumbnail_text(connection: sqlite3.Connection, job_id: str, text: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    normalized = str(text).strip()
    if len(normalized) > 1000:
        raise ValueError("Thumbnail text can contain at most 1,000 characters.")
    if effective_thumbnail_mode(connection, job) != "auto":
        raise ValueError("Thumbnail text editing is available in Auto mode.")
    if not job["source_thumbnail_path"] or not Path(job["source_thumbnail_path"]).is_file():
        raise ValueError("Download the source thumbnail before generating an edited thumbnail.")
    if not normalized:
        raise ValueError("Enter or confirm the text recognized from the source thumbnail.")
    connection.execute(
        "UPDATE video_jobs SET thumbnail_text = ?, thumbnail_ocr_status = 'confirmed', thumbnail_error = NULL, thumbnail_output_path = NULL WHERE id = ?",
        (normalized, job_id),
    )
    connection.commit()
    return job_view(connection, connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone())


def tesseract_binary() -> str | None:
    return os.environ.get("TESSERACT_BINARY") or shutil.which("tesseract")


def list_ocr_languages() -> list[dict[str, str]]:
    binary = tesseract_binary()
    if not binary:
        return []
    try:
        command = [binary]
        tessdata = os.environ.get("TESSDATA_DIR")
        if tessdata:
            command.extend(["--tessdata-dir", tessdata])
        command.append("--list-langs")
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    labels = {"eng": "English", "vie": "Vietnamese", "jpn": "Japanese", "kor": "Korean", "chi_sim": "Chinese (Simplified)", "chi_tra": "Chinese (Traditional)", "spa": "Spanish", "fra": "French", "deu": "German", "por": "Portuguese", "rus": "Russian", "ara": "Arabic", "tha": "Thai", "hin": "Hindi"}
    return [{"code": code, "name": labels.get(code, code)} for code in completed.stdout.splitlines()[1:] if re.fullmatch(r"[A-Za-z0-9_]+", code.strip()) for code in [code.strip()]]


def recognize_thumbnail_text(image_path: str, languages: list[str]) -> tuple[str, float | None, str | None]:
    binary = tesseract_binary()
    if not binary:
        return "", None, "Tesseract was not found. Install it or configure TESSERACT_BINARY; you can still edit the thumbnail manually."
    installed = {item["code"] for item in list_ocr_languages()}
    selected = [language for language in languages if language in installed]
    missing = [language for language in languages if language not in installed]
    if not selected:
        return "", None, f"None of the selected OCR languages are installed ({', '.join(languages)}). Install the matching Tesseract language data or change this Channel's OCR preferences."
    language_note = f" OCR skipped unavailable language data: {', '.join(missing)}." if missing else ""
    try:
        command = [binary, image_path, "stdout"]
        tessdata = os.environ.get("TESSDATA_DIR")
        if tessdata:
            command.extend(["--tessdata-dir", tessdata])
        command.extend(["-l", "+".join(selected), "tsv"])
        completed = subprocess.run(
            command,
            capture_output=True, text=True, check=False, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", None, f"Thumbnail OCR could not finish: {error}"
    if completed.returncode != 0:
        return "", None, (completed.stderr.strip() or "Tesseract could not read the source thumbnail.")[-1000:]
    reader = csv.DictReader(completed.stdout.splitlines(), delimiter="\t")
    words: list[str] = []
    confidences: list[float] = []
    for item in reader:
        word = (item.get("text") or "").strip()
        try:
            confidence = float(item.get("conf", "-1"))
        except (TypeError, ValueError):
            confidence = -1
        if word and confidence >= 0:
            words.append(word)
            confidences.append(confidence / 100)
    text = " ".join(words)
    confidence = sum(confidences) / len(confidences) if confidences else None
    error = (f"No readable text was found in the source thumbnail. Edit the text manually or leave thumbnail handling to a manual workflow.{language_note}" if not text else f"OCR completed with limited language data.{language_note}" if missing else None)
    return text, confidence, error


def render_thumbnail_image(source_path: str, output_path: str, text: str, preset: sqlite3.Row) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as error:
        raise ValueError("Pillow is missing from the local worker. Reinstall the app dependencies and try again.") from error

    width, height = 1280, 720
    style = {key: preset[key] for key in DEFAULT_THUMBNAIL_STYLE}
    background_color = style["background_color"]
    if style["background_type"] == "solid":
        canvas = Image.new("RGB", (width, height), background_color)
    else:
        start = tuple(bytes.fromhex(background_color[1:]))
        end = tuple(bytes.fromhex(style["gradient_end_color"][1:]))
        strip = Image.new("RGB", (1024, 1))
        strip.putdata([tuple(round(start[index] + (end[index] - start[index]) * offset / 1023) for index in range(3)) for offset in range(1024)])
        gradient = strip.resize((width * 2, height * 2), Image.Resampling.BICUBIC).rotate(style["gradient_angle"], resample=Image.Resampling.BICUBIC, expand=False)
        left = (gradient.width - width) // 2
        top = (gradient.height - height) // 2
        canvas = gradient.crop((left, top, left + width, top + height))

    font_info = inspect_font_family(style["font_family"])
    font_path = font_info.get("font_path")
    if not font_path:
        try:
            import PIL
            fallback = Path(PIL.__file__).parent / "fonts" / "DejaVuSans.ttf"
            font_path = str(fallback) if fallback.is_file() else None
        except (ImportError, OSError):
            font_path = None
    if font_path:
        font = ImageFont.truetype(font_path, style["font_size"])
    else:
        font = ImageFont.load_default()
    max_width = round(width * style["max_width_percent"] / 100)
    max_height = round(height * 0.78)
    words = [part for line in str(text).splitlines() for part in ([line] if line == "" else line.split(" "))]

    def wrap_lines(candidate_font: Any) -> list[str]:
        lines: list[str] = []
        current = ""
        draw = ImageDraw.Draw(canvas)
        for word in words:
            trial = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), trial, font=candidate_font, stroke_width=0)[2] > max_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current or not lines:
            lines.append(current)
        return lines

    lines = wrap_lines(font)
    draw = ImageDraw.Draw(canvas)
    spacing = max(4, round(style["font_size"] * 0.12))
    if style["fit_mode"] == "shrink":
        size = style["font_size"]
        while size > 24:
            font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
            lines = wrap_lines(font)
            bounds = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=round(style["outline_width"])) for line in lines]
            block_height = sum(box[3] - box[1] for box in bounds) + spacing * (len(lines) - 1)
            if max(box[2] - box[0] for box in bounds) <= max_width and block_height <= max_height:
                break
            size -= 2
    bounds = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=round(style["outline_width"])) for line in lines]
    block_height = sum(box[3] - box[1] for box in bounds) + spacing * (len(lines) - 1)
    if block_height > max_height or any(box[2] - box[0] > max_width for box in bounds):
        raise ValueError("Thumbnail text is too long for this preset. Shorten the text or choose a smaller font/fit mode.")
    x_anchor = round(width * style["position_x"] / 100)
    y = round(height * style["position_y"] / 100 - block_height / 2)
    shadow = round(style["shadow"])
    stroke = round(style["outline_width"])
    for line, box in zip(lines, bounds):
        line_width = box[2] - box[0]
        x = x_anchor - line_width // 2 if style["alignment"] == "center" else x_anchor if style["alignment"] == "left" else x_anchor - line_width
        if shadow:
            draw.text((x + shadow, y + shadow), line, font=font, fill="#000000", stroke_width=stroke, stroke_fill="#000000")
        draw.text((x, y), line, font=font, fill=style["text_color"], stroke_width=stroke, stroke_fill=style["outline_color"])
        y += box[3] - box[1] + spacing
    canvas.save(output_path, format="PNG", optimize=True)


def render_job_thumbnail(connection: sqlite3.Connection, job_id: str, text: str | None = None) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if effective_thumbnail_mode(connection, job) != "auto":
        raise ValueError("Thumbnail export is available only in Auto mode.")
    if not job["source_thumbnail_path"] or not Path(job["source_thumbnail_path"]).is_file():
        raise ValueError("Download the source thumbnail before exporting the edited thumbnail.")
    selected_text = str(text if text is not None else job["thumbnail_text"]).strip()
    if not selected_text:
        raise ValueError("Confirm or edit the text recognized from the source thumbnail first.")
    preset_id = job["thumbnail_preset_id"]
    if not preset_id:
        raise ValueError("Assign a thumbnail preset before exporting.")
    preset = get_thumbnail_preset(connection, preset_id)
    output_path = str(Path(job["source_thumbnail_path"]).with_name("thumbnail.png"))
    try:
        render_thumbnail_image(job["source_thumbnail_path"], output_path, selected_text, preset)
    except (OSError, ValueError) as error:
        connection.execute("UPDATE video_jobs SET thumbnail_error = ?, thumbnail_ocr_status = 'error' WHERE id = ?", (str(error), job_id))
        connection.commit()
        raise
    connection.execute(
        "UPDATE video_jobs SET thumbnail_text = ?, thumbnail_output_path = ?, thumbnail_error = NULL, thumbnail_ocr_status = 'complete' WHERE id = ?",
        (selected_text, output_path, job_id),
    )
    connection.execute("DELETE FROM job_artifacts WHERE job_id = ? AND kind = 'thumbnail_output'", (job_id,))
    add_job_artifact(connection, job_id, "thumbnail_output", output_path)
    connection.commit()
    return job_view(connection, connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone())


def subtitle_preset_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "name": row["name"],
        "style": json.loads(row["style_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_subtitle_preset(
    connection: sqlite3.Connection,
    channel_id: str | None,
    name: str,
    style: Any,
) -> dict[str, Any]:
    if channel_id:
        ensure_channel(connection, channel_id)
    normalized_name = str(name).strip()
    if not normalized_name:
        raise ValueError("Subtitle preset name is required.")
    if len(normalized_name) > 80:
        raise ValueError("Subtitle preset names can be at most 80 characters.")
    normalized_style = validate_subtitle_style(style)
    now = utc_now()
    preset_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO subtitle_presets(id, channel_id, name, style_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (preset_id, channel_id, normalized_name, json.dumps(normalized_style), now, now),
    )
    row = connection.execute("SELECT * FROM subtitle_presets WHERE id = ?", (preset_id,)).fetchone()
    return subtitle_preset_view(row)


def get_subtitle_preset(connection: sqlite3.Connection, preset_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM subtitle_presets WHERE id = ?", (preset_id,)).fetchone()
    if row is None:
        raise ValueError("Subtitle preset was not found.")
    return row


def update_subtitle_preset(
    connection: sqlite3.Connection,
    preset_id: str,
    name: str,
    style: Any,
) -> dict[str, Any]:
    preset = get_subtitle_preset(connection, preset_id)
    normalized_name = str(name).strip()
    if not normalized_name or len(normalized_name) > 80:
        raise ValueError("Subtitle preset name must be between 1 and 80 characters.")
    normalized_style = validate_subtitle_style(style)
    connection.execute(
        "UPDATE subtitle_presets SET name = ?, style_json = ?, updated_at = ? WHERE id = ?",
        (normalized_name, json.dumps(normalized_style), utc_now(), preset_id),
    )
    connection.execute(
        """
        UPDATE video_jobs SET render_status = 'not_started', render_error = NULL,
            render_progress = NULL, output_video_path = NULL, srt_sidecar_path = NULL, encoder_used = NULL
        WHERE subtitle_preset_id = ? OR (subtitle_preset_id IS NULL AND channel_id IN
            (SELECT id FROM channels WHERE default_subtitle_preset_id = ?))
        """,
        (preset_id, preset_id),
    )
    return subtitle_preset_view(get_subtitle_preset(connection, preset_id))


def set_channel_default_subtitle_preset(
    connection: sqlite3.Connection,
    channel_id: str,
    preset_id: str,
) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    preset = get_subtitle_preset(connection, preset_id)
    if preset["channel_id"] not in {None, channel_id}:
        raise ValueError("Choose a global preset or one owned by this Channel.")
    connection.execute(
        "UPDATE channels SET default_subtitle_preset_id = ?, updated_at = ? WHERE id = ?",
        (preset_id, utc_now(), channel_id),
    )
    connection.execute(
        """
        UPDATE video_jobs SET render_status = 'not_started', render_error = NULL,
            render_progress = NULL, output_video_path = NULL, srt_sidecar_path = NULL, encoder_used = NULL
        WHERE channel_id = ? AND subtitle_preset_id IS NULL
        """,
        (channel_id,),
    )
    connection.commit()
    return channel_view(connection, ensure_channel(connection, channel_id))


def set_job_subtitle_preset(connection: sqlite3.Connection, job_id: str, preset_id: str | None) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if preset_id:
        preset = get_subtitle_preset(connection, preset_id)
        if preset["channel_id"] not in {None, job["channel_id"]}:
            raise ValueError("Choose a global preset or one owned by this job's Channel.")
    connection.execute(
        "UPDATE video_jobs SET subtitle_preset_id = ?, render_status = 'not_started', render_error = NULL, render_progress = NULL, output_video_path = NULL, srt_sidecar_path = NULL, encoder_used = NULL WHERE id = ?",
        (preset_id, job_id),
    )
    connection.commit()
    fresh = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    return job_view(connection, fresh)


def list_subtitle_presets(connection: sqlite3.Connection, channel_id: str | None) -> list[dict[str, Any]]:
    if channel_id:
        ensure_channel(connection, channel_id)
        rows = connection.execute(
            "SELECT * FROM subtitle_presets WHERE channel_id IS NULL OR channel_id = ? ORDER BY updated_at DESC, name COLLATE NOCASE",
            (channel_id,),
        ).fetchall()
    else:
        rows = connection.execute("SELECT * FROM subtitle_presets WHERE channel_id IS NULL ORDER BY updated_at DESC, name COLLATE NOCASE").fetchall()
    return [subtitle_preset_view(row) for row in rows]


def unique_slug(
    connection: sqlite3.Connection,
    name: str,
    excluding_channel_id: str | None = None,
) -> str:
    base = normalize_slug(name)
    candidate = base
    counter = 2
    while True:
        query = "SELECT id FROM channels WHERE slug = ?"
        parameters: tuple[Any, ...] = (candidate,)
        if excluding_channel_id:
            query += " AND id != ?"
            parameters = (candidate, excluding_channel_id)
        if connection.execute(query, parameters).fetchone() is None:
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def channel_view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    count = connection.execute(
        "SELECT COUNT(*) FROM channel_backgrounds WHERE channel_id = ?",
        (row["id"],),
    ).fetchone()[0]
    preset = connection.execute("SELECT * FROM subtitle_presets WHERE id = ?", (row["default_subtitle_preset_id"],)).fetchone() if row["default_subtitle_preset_id"] else None
    thumbnail_preset = connection.execute("SELECT * FROM thumbnail_presets WHERE id = ?", (row["default_thumbnail_preset_id"],)).fetchone() if row["default_thumbnail_preset_id"] else None
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "active": bool(row["active"]),
        "background_count": count,
        "subtitle_languages": json.loads(row["subtitle_languages_json"] or "[]"),
        "default_subtitle_preset_id": row["default_subtitle_preset_id"],
        "default_subtitle_preset": subtitle_preset_view(preset) if preset else None,
        "thumbnail_mode": row["thumbnail_mode"],
        "ocr_languages": json.loads(row["ocr_languages_json"] or '["eng"]'),
        "default_thumbnail_preset_id": row["default_thumbnail_preset_id"],
        "default_thumbnail_preset": thumbnail_preset_view(thumbnail_preset) if thumbnail_preset else None,
        "thumbnail_preset_count": connection.execute("SELECT COUNT(*) FROM channel_thumbnail_presets WHERE channel_id = ?", (row["id"],)).fetchone()[0],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_channel(connection: sqlite3.Connection, name: str) -> dict[str, Any]:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Channel name is required.")
    now = utc_now()
    channel_id = str(uuid.uuid4())
    slug = unique_slug(connection, normalized_name)
    connection.execute(
        """
        INSERT INTO channels(id, name, slug, active, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        (channel_id, normalized_name, slug, now, now),
    )
    preset = create_subtitle_preset(connection, channel_id, f"{normalized_name} default", DEFAULT_SUBTITLE_STYLE)
    connection.execute("UPDATE channels SET default_subtitle_preset_id = ? WHERE id = ?", (preset["id"], channel_id))
    thumbnail = create_thumbnail_preset(connection, channel_id, f"{normalized_name} default", DEFAULT_THUMBNAIL_STYLE)
    connection.execute("UPDATE channels SET default_thumbnail_preset_id = ? WHERE id = ?", (thumbnail["id"], channel_id))
    connection.execute("INSERT INTO channel_thumbnail_presets(channel_id, preset_id, position) VALUES (?, ?, 0)", (channel_id, thumbnail["id"]))
    connection.commit()
    row = ensure_channel(connection, channel_id)
    return channel_view(connection, row)


def set_channel_subtitle_languages(
    connection: sqlite3.Connection,
    channel_id: str,
    supplied_languages: Any,
) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    if not isinstance(supplied_languages, list):
        raise ValueError("Subtitle language preferences must be a list of language codes.")
    languages = []
    seen = set()
    for supplied in supplied_languages:
        language = str(supplied).strip().replace("_", "-")
        if not language:
            continue
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
            raise ValueError(f"Invalid subtitle language code: {language}")
        key = language.lower()
        if key not in seen:
            seen.add(key)
            languages.append(language)
    if len(languages) > 20:
        raise ValueError("Choose no more than 20 preferred subtitle languages.")
    connection.execute(
        "UPDATE channels SET subtitle_languages_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(languages, ensure_ascii=False), utc_now(), channel_id),
    )
    connection.commit()
    return channel_view(connection, ensure_channel(connection, channel_id))


def parse_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return None
        return float(numerator) / denominator_value
    except (ValueError, TypeError):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def probe_video(path: str) -> dict[str, Any]:
    binary = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
    if not binary:
        return {
            "duration_seconds": None,
            "width": None,
            "height": None,
            "frame_rate": None,
            "codec": None,
            "probe_status": "tool_missing",
        }
    command = [
        binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        path,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "duration_seconds": None,
            "width": None,
            "height": None,
            "frame_rate": None,
            "codec": None,
            "probe_status": "probe_failed",
        }
    if completed.returncode != 0:
        return {
            "duration_seconds": None,
            "width": None,
            "height": None,
            "frame_rate": None,
            "codec": None,
            "probe_status": "probe_failed",
        }
    try:
        details = json.loads(completed.stdout)
    except json.JSONDecodeError:
        details = {}
    stream = next(iter(details.get("streams", [])), {})
    duration = stream.get("duration") or details.get("format", {}).get("duration")
    rate = parse_rate(stream.get("avg_frame_rate")) or parse_rate(
        stream.get("r_frame_rate")
    )
    return {
        "duration_seconds": float(duration) if duration not in (None, "N/A") else None,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "frame_rate": rate,
        "codec": stream.get("codec_name"),
        "probe_status": "ready",
    }


def asset_view(row: sqlite3.Row) -> dict[str, Any]:
    path = row["path"]
    return {
        "id": row["id"],
        "kind": row["kind"],
        "path": path,
        "name": Path(path).name,
        "duration_seconds": row["duration_seconds"],
        "width": row["width"],
        "height": row["height"],
        "frame_rate": row["frame_rate"],
        "codec": row["codec"],
        "probe_status": row["probe_status"],
        "available": Path(path).is_file(),
        "created_at": row["created_at"],
    }


def add_background_to_channel(
    connection: sqlite3.Connection,
    channel_id: str,
    supplied_path: str,
) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    try:
        path = str(Path(supplied_path).expanduser().resolve(strict=True))
    except (OSError, RuntimeError) as error:
        raise ValueError("The selected background file could not be found.") from error
    if not Path(path).is_file():
        raise ValueError("The selected background path is not a file.")

    row = connection.execute(
        "SELECT * FROM media_assets WHERE kind = 'background' AND path = ?",
        (path,),
    ).fetchone()
    if row is None:
        metadata = probe_video(path)
        asset_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO media_assets(
                id, kind, path, duration_seconds, width, height, frame_rate, codec,
                probe_status, created_at
            ) VALUES (?, 'background', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                path,
                metadata["duration_seconds"],
                metadata["width"],
                metadata["height"],
                metadata["frame_rate"],
                metadata["codec"],
                metadata["probe_status"],
                utc_now(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM media_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()

    existing = connection.execute(
        """
        SELECT 1 FROM channel_backgrounds
        WHERE channel_id = ? AND asset_id = ?
        """,
        (channel_id, row["id"]),
    ).fetchone()
    if existing is None:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM channel_backgrounds WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO channel_backgrounds(channel_id, asset_id, position)
            VALUES (?, ?, ?)
            """,
            (channel_id, row["id"], position),
        )
    connection.commit()
    return asset_view(row)


def list_channels(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM channels ORDER BY active DESC, name COLLATE NOCASE"
    ).fetchall()
    return [channel_view(connection, row) for row in rows]


def list_backgrounds(
    connection: sqlite3.Connection,
    channel_id: str,
) -> list[dict[str, Any]]:
    ensure_channel(connection, channel_id)
    rows = connection.execute(
        """
        SELECT assets.*
        FROM media_assets AS assets
        JOIN channel_backgrounds AS links ON links.asset_id = assets.id
        WHERE links.channel_id = ?
        ORDER BY links.position, assets.created_at
        """,
        (channel_id,),
    ).fetchall()
    return [asset_view(row) for row in rows]


def list_background_library(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM media_assets WHERE kind = 'background' ORDER BY created_at DESC, id"
    ).fetchall()
    library = []
    for row in rows:
        item = asset_view(row)
        item["channel_ids"] = [
            assignment[0]
            for assignment in connection.execute(
                "SELECT channel_id FROM channel_backgrounds WHERE asset_id = ? ORDER BY position",
                (row["id"],),
            ).fetchall()
        ]
        library.append(item)
    return library


def assign_background_to_channel(
    connection: sqlite3.Connection,
    channel_id: str,
    asset_id: str,
) -> dict[str, Any]:
    ensure_channel(connection, channel_id)
    asset = connection.execute(
        "SELECT * FROM media_assets WHERE id = ? AND kind = 'background'",
        (asset_id,),
    ).fetchone()
    if asset is None:
        raise ValueError("Background asset was not found.")
    exists = connection.execute(
        "SELECT 1 FROM channel_backgrounds WHERE channel_id = ? AND asset_id = ?",
        (channel_id, asset_id),
    ).fetchone()
    if exists is None:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM channel_backgrounds WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO channel_backgrounds(channel_id, asset_id, position) VALUES (?, ?, ?)",
            (channel_id, asset_id, position),
        )
        connection.commit()
    return asset_view(asset)


def remove_background_from_channel(
    connection: sqlite3.Connection,
    channel_id: str,
    asset_id: str,
) -> dict[str, bool]:
    ensure_channel(connection, channel_id)
    connection.execute(
        "DELETE FROM channel_backgrounds WHERE channel_id = ? AND asset_id = ?",
        (channel_id, asset_id),
    )
    connection.commit()
    return {"removed": True}


def relink_background_asset(
    connection: sqlite3.Connection,
    asset_id: str,
    supplied_path: str,
) -> dict[str, Any]:
    asset = connection.execute(
        "SELECT * FROM media_assets WHERE id = ? AND kind = 'background'",
        (asset_id,),
    ).fetchone()
    if asset is None:
        raise ValueError("Background asset was not found.")
    try:
        path = str(Path(supplied_path).expanduser().resolve(strict=True))
    except (OSError, RuntimeError) as error:
        raise ValueError("The replacement background file could not be found.") from error
    if not Path(path).is_file():
        raise ValueError("The selected replacement path is not a file.")
    conflicting = connection.execute(
        "SELECT id FROM media_assets WHERE kind = 'background' AND path = ? AND id != ?",
        (path, asset_id),
    ).fetchone()
    if conflicting:
        raise ValueError("This file is already in the library. Assign the existing background instead.")
    metadata = probe_video(path)
    connection.execute(
        """
        UPDATE media_assets
        SET path = ?, duration_seconds = ?, width = ?, height = ?, frame_rate = ?,
            codec = ?, probe_status = ?
        WHERE id = ?
        """,
        (
            path,
            metadata["duration_seconds"],
            metadata["width"],
            metadata["height"],
            metadata["frame_rate"],
            metadata["codec"],
            metadata["probe_status"],
            asset_id,
        ),
    )
    connection.commit()
    updated = connection.execute("SELECT * FROM media_assets WHERE id = ?", (asset_id,)).fetchone()
    return asset_view(updated)


YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_youtube_url(value: str) -> tuple[str | None, str | None]:
    supplied = value.strip()
    if not supplied:
        return None, None
    parsed = urlparse(supplied if "://" in supplied else f"https://{supplied}")
    if parsed.scheme not in {"http", "https"}:
        return None, None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    video_id: str | None = None
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = path_parts[1]
    if not video_id or not YOUTUBE_VIDEO_ID.fullmatch(video_id):
        return None, None
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def channel_by_imported_value(connection: sqlite3.Connection, value: str) -> sqlite3.Row | None:
    supplied = value.strip()
    if not supplied:
        return None
    by_id = connection.execute("SELECT * FROM channels WHERE id = ?", (supplied,)).fetchone()
    if by_id:
        return by_id
    folded = supplied.casefold()
    return next(
        (row for row in connection.execute("SELECT * FROM channels").fetchall() if row["name"].casefold() == folded),
        None,
    )


def parse_import_rows(content: str, channel_id: str | None) -> tuple[list[dict[str, Any]], str]:
    if not content.strip():
        raise ValueError("Paste at least one YouTube URL or import a CSV/TSV file.")
    if channel_id:
        rows = [
            {"channel": channel_id, "url": line.strip(), "row_number": number}
            for number, line in enumerate(content.splitlines(), start=1)
            if line.strip()
        ]
        return rows, "pasted_urls"

    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=",\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(content.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("The import file needs a header row with Channel and URL columns.")
    normalized_headers = {
        re.sub(r"[^a-z0-9]+", "_", (header or "").strip().lower()).strip("_"): header
        for header in reader.fieldnames
    }
    channel_header = next(
        (normalized_headers[key] for key in ("channel", "channel_name", "channel_id") if key in normalized_headers),
        None,
    )
    url_header = next(
        (normalized_headers[key] for key in ("url", "video_url", "youtube_url", "link") if key in normalized_headers),
        None,
    )
    if not channel_header or not url_header:
        raise ValueError("The import file needs Channel and URL columns.")
    rows = []
    for number, row in enumerate(reader, start=2):
        channel_value = (row.get(channel_header) or "").strip()
        url_value = (row.get(url_header) or "").strip()
        if channel_value or url_value:
            rows.append({"channel": channel_value, "url": url_value, "row_number": number})
    if not rows:
        raise ValueError("The import file has a header but no video rows.")
    return rows, "csv_tsv"


def batch_summary(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    job_count = connection.execute(
        "SELECT COUNT(*) FROM video_jobs WHERE batch_id = ?", (row["id"],)
    ).fetchone()[0]
    ready_count = 0
    unresolved_count = 0
    queued_count = 0
    running_count = 0
    failed_count = 0
    for job in connection.execute(
        "SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position", (row["id"],)
    ).fetchall():
        view = job_view(connection, job)
        if view["readiness"] == "ready":
            ready_count += 1
        else:
            unresolved_count += 1
    for task in connection.execute("SELECT state, COUNT(*) AS count FROM queue_tasks WHERE batch_id = ? GROUP BY state", (row["id"],)).fetchall():
        if task["state"] in {"queued", "starting"}:
            queued_count += int(task["count"])
        elif task["state"] in {"downloading", "rendering", "cancel_requested"}:
            running_count += int(task["count"])
        elif task["state"] == "failed":
            failed_count += int(task["count"])
    return {
        "id": row["id"],
        "name": row["name"],
        "workflow_mode": row["workflow_mode"],
        "state": row["state"],
        "import_source": row["import_source"],
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"],
        "job_count": job_count,
        "ready_count": ready_count,
        "unresolved_count": unresolved_count,
        "thumbnail_mode_override": row["thumbnail_mode_override"],
        "thumbnail_preset_ids": [item["preset_id"] for item in connection.execute("SELECT preset_id FROM batch_thumbnail_presets WHERE batch_id = ? ORDER BY position", (row["id"],)).fetchall()],
        "queue_queued_count": queued_count,
        "queue_running_count": running_count,
        "queue_failed_count": failed_count,
    }


def simplify_subtitle_tracks(metadata: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    simplified: dict[str, list[dict[str, str]]] = {"creator": [], "automatic": []}
    for source_key, output_key in (("subtitles", "creator"), ("automatic_captions", "automatic")):
        track_map = metadata.get(source_key) or {}
        if not isinstance(track_map, dict):
            continue
        for language, variants in track_map.items():
            if isinstance(variants, dict):
                variants = [variants]
            if not isinstance(variants, list) or not variants:
                continue
            labels = [
                str(track.get("name") or track.get("ext") or "")
                for track in variants
                if isinstance(track, dict)
            ]
            extensions = [
                str(track.get("ext") or "")
                for track in variants
                if isinstance(track, dict)
            ]
            simplified[output_key].append(
                {
                    "language": str(language),
                    "formats": ", ".join(dict.fromkeys(value for value in extensions if value)),
                    "label": next((value for value in labels if value), ""),
                }
            )
    for source_key in simplified:
        simplified[source_key].sort(key=lambda track: track["language"].lower())
    return simplified


def select_subtitle_track(
    preferences: list[str],
    tracks: dict[str, list[dict[str, str]]],
) -> dict[str, str] | None:
    for preferred in preferences:
        preferred_normalized = preferred.lower().replace("_", "-")
        all_candidates = tracks.get("creator", []) + tracks.get("automatic", [])
        exact_languages = [
            track["language"] for track in all_candidates
            if track["language"].lower().replace("_", "-") == preferred_normalized
        ]
        base_language = preferred_normalized.split("-", 1)[0]
        base_languages = [
            track["language"] for track in all_candidates
            if track["language"].lower().replace("_", "-").split("-", 1)[0] == base_language
        ]
        if "-" in preferred_normalized:
            candidate_groups = [
                exact_languages,
                [language for language in base_languages if language not in exact_languages],
            ]
        else:
            candidate_groups = [base_languages]
        for candidates in candidate_groups:
            for origin in ("creator", "automatic"):
                for candidate_language in candidates:
                    selected = next(
                        (track for track in tracks.get(origin, []) if track["language"].lower() == candidate_language.lower()),
                        None,
                    )
                    if selected:
                        return {"language": selected["language"], "source": origin}
    return None


def job_view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    batch = connection.execute("SELECT workflow_mode FROM batches WHERE id = ?", (row["batch_id"],)).fetchone()
    download_only = bool(batch and batch["workflow_mode"] == "download_only")
    channel = connection.execute("SELECT id, name, subtitle_languages_json, default_subtitle_preset_id, thumbnail_mode, ocr_languages_json, default_thumbnail_preset_id FROM channels WHERE id = ?", (row["channel_id"],)).fetchone() if row["channel_id"] else None
    active_preset_id = row["subtitle_preset_id"] or (channel["default_subtitle_preset_id"] if channel else None)
    active_preset = connection.execute("SELECT * FROM subtitle_presets WHERE id = ?", (active_preset_id,)).fetchone() if active_preset_id else None
    asset = connection.execute("SELECT * FROM media_assets WHERE id = ?", (row["background_asset_id"],)).fetchone() if row["background_asset_id"] else None
    channel_preferences = json.loads(channel["subtitle_languages_json"] or "[]") if row["channel_id"] else []
    subtitle_preferences = json.loads(row["subtitle_language_override_json"] or "[]") or channel_preferences
    subtitle_tracks = json.loads(row["subtitle_tracks_json"] or '{"creator":[],"automatic":[]}')
    selected_subtitle = select_subtitle_track(subtitle_preferences, subtitle_tracks)
    selected_thumbnail_preset_id = row["thumbnail_preset_id"] or (channel["default_thumbnail_preset_id"] if channel else None)
    selected_thumbnail_preset = connection.execute("SELECT * FROM thumbnail_presets WHERE id = ?", (selected_thumbnail_preset_id,)).fetchone() if selected_thumbnail_preset_id else None
    thumbnail_presets = thumbnail_preset_pool(connection, channel["id"] if channel else None, row["batch_id"])
    queue_task = connection.execute("SELECT * FROM queue_tasks WHERE job_id = ? AND pipeline = 'video' ORDER BY created_at DESC, id DESC LIMIT 1", (row["id"],)).fetchone()
    thumbnail_queue_task = connection.execute("SELECT * FROM queue_tasks WHERE job_id = ? AND pipeline = 'thumbnail' ORDER BY created_at DESC, id DESC LIMIT 1", (row["id"],)).fetchone()
    download_queue_task = connection.execute("SELECT * FROM queue_tasks WHERE job_id = ? AND pipeline = 'download_only' ORDER BY created_at DESC, id DESC LIMIT 1", (row["id"],)).fetchone()
    artifacts = [
        {"kind": item["kind"], "path": item["path"], "available": Path(item["path"]).is_file()}
        for item in connection.execute(
            "SELECT kind, path FROM job_artifacts WHERE job_id = ? ORDER BY created_at, kind",
            (row["id"],),
        ).fetchall()
    ]
    pool_count = connection.execute(
        "SELECT COUNT(*) FROM channel_backgrounds WHERE channel_id = ?",
        (row["channel_id"],),
    ).fetchone()[0] if row["channel_id"] else 0
    pool_assets = connection.execute(
        """
        SELECT assets.path FROM channel_backgrounds AS links
        JOIN media_assets AS assets ON assets.id = links.asset_id
        WHERE links.channel_id = ? AND assets.kind = 'background'
        """,
        (row["channel_id"],),
    ).fetchall() if row["channel_id"] else []
    available_pool_count = sum(1 for pool_asset in pool_assets if Path(pool_asset["path"]).is_file())
    flags = []
    if row["validation_code"] != "valid":
        flags.append("invalid_url")
    if not row["channel_id"]:
        flags.append("unknown_channel")
    if row["duplicate_of_job_id"]:
        flags.append("duplicate_url")
    if not download_only and row["channel_id"] and available_pool_count == 0:
        flags.append("no_background_pool")
    if not download_only and row["channel_id"] and not row["background_asset_id"] and available_pool_count:
        flags.append("background_unassigned")
    if not download_only and asset and not Path(asset["path"]).is_file():
        flags.append("missing_background_file")
    if row["metadata_status"] == "pending":
        flags.append("needs_metadata")
    elif row["metadata_status"] == "error":
        flags.append("metadata_error")
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "channel_id": row["channel_id"],
        "channel_name": channel["name"] if channel else row["imported_channel_name"],
        "imported_channel_name": row["imported_channel_name"],
        "url": row["url"],
        "canonical_url": row["canonical_url"],
        "video_id": row["video_id"],
        "title": row["title"],
        "duration_seconds": row["duration_seconds"],
        "thumbnail_url": row["thumbnail_url"],
        "metadata_status": row["metadata_status"],
        "metadata_error": row["metadata_error"],
        "row_number": row["row_number"],
        "position": row["position"],
        "duplicate_of_job_id": row["duplicate_of_job_id"],
        "background_asset_id": row["background_asset_id"],
        "background_name": Path(asset["path"]).name if asset else None,
        "background_locked": bool(row["background_locked"]),
        "background_available": Path(asset["path"]).is_file() if asset else False,
        "background_pool_count": pool_count,
        "subtitle_languages": channel_preferences,
        "subtitle_language_override": json.loads(row["subtitle_language_override_json"] or "[]"),
        "subtitle_tracks": subtitle_tracks,
        "selected_subtitle_language": row["subtitle_language"] or (selected_subtitle["language"] if selected_subtitle else None),
        "selected_subtitle_source": row["subtitle_source"] or (selected_subtitle["source"] if selected_subtitle else None),
        "subtitle_source": row["subtitle_source"] or (selected_subtitle["source"] if selected_subtitle else None),
        "subtitle_decision": row["subtitle_decision"],
        "supplied_subtitle_path": row["supplied_subtitle_path"],
        "subtitle_error": row["subtitle_error"],
        "subtitle_preset_id": row["subtitle_preset_id"],
        "subtitle_style": json.loads(active_preset["style_json"]) if active_preset else dict(DEFAULT_SUBTITLE_STYLE),
        "subtitle_preset_name": active_preset["name"] if active_preset else "Built-in default",
        "available_subtitle_presets": [
            subtitle_preset_view(preset) for preset in connection.execute(
                "SELECT * FROM subtitle_presets WHERE channel_id IS NULL OR channel_id = ? ORDER BY name COLLATE NOCASE",
                (row["channel_id"],),
            ).fetchall()
        ] if row["channel_id"] else [],
        "include_video_source": bool(row["include_video_source"]),
        "source_audio_path": row["source_audio_path"],
        "source_video_path": row["source_video_path"],
        "source_thumbnail_path": row["source_thumbnail_path"],
        "thumbnail_mode": effective_thumbnail_mode(connection, row),
        "thumbnail_mode_override": row["thumbnail_mode_override"],
        "channel_thumbnail_mode": channel["thumbnail_mode"] if channel else "auto",
        "thumbnail_preset_id": selected_thumbnail_preset_id,
        "thumbnail_preset_locked": bool(row["thumbnail_preset_locked"]),
        "thumbnail_preset": thumbnail_preset_view(selected_thumbnail_preset) if selected_thumbnail_preset else None,
        "available_thumbnail_presets": thumbnail_presets,
        "thumbnail_ocr_text": row["thumbnail_ocr_text"],
        "thumbnail_ocr_confidence": row["thumbnail_ocr_confidence"],
        "thumbnail_ocr_languages": effective_thumbnail_languages(connection, row),
        "thumbnail_ocr_status": row["thumbnail_ocr_status"],
        "thumbnail_progress": row["thumbnail_progress"],
        "thumbnail_text": row["thumbnail_text"],
        "thumbnail_output_path": row["thumbnail_output_path"],
        "thumbnail_error": row["thumbnail_error"],
        "download_status": row["download_status"],
        "download_progress": row["download_progress"],
        "download_error": row["download_error"],
        "queue_task": {
            "id": queue_task["id"], "state": queue_task["state"], "stage": queue_task["stage"],
            "progress": queue_task["progress"], "error": queue_task["error"],
            "created_at": queue_task["created_at"], "updated_at": queue_task["updated_at"],
        } if queue_task else None,
        "download_queue_task": {
            "id": download_queue_task["id"], "state": download_queue_task["state"], "stage": download_queue_task["stage"],
            "progress": download_queue_task["progress"], "error": download_queue_task["error"],
            "created_at": download_queue_task["created_at"], "updated_at": download_queue_task["updated_at"],
        } if download_queue_task else None,
        "thumbnail_queue_task": {
            "id": thumbnail_queue_task["id"], "state": thumbnail_queue_task["state"], "stage": thumbnail_queue_task["stage"],
            "progress": thumbnail_queue_task["progress"], "error": thumbnail_queue_task["error"],
            "created_at": thumbnail_queue_task["created_at"], "updated_at": thumbnail_queue_task["updated_at"],
        } if thumbnail_queue_task else None,
        "output_profile": json.loads(row["output_profile_json"] or '{"profile":"720p","frame_preference":null,"fit_mode":"crop"}'),
        "render_status": row["render_status"],
        "render_error": row["render_error"],
        "render_progress": row["render_progress"],
        "output_video_path": row["output_video_path"],
        "srt_sidecar_path": row["srt_sidecar_path"],
        "encoder_used": row["encoder_used"],
        "artifacts": artifacts,
        "flags": flags,
        "readiness": flags[0] if flags else "ready",
    }


def batch_jobs(connection: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position", (batch_id,)
    ).fetchall()
    return [job_view(connection, row) for row in rows]


def get_batch(connection: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if row is None:
        raise ValueError("Batch was not found.")
    return {"batch": batch_summary(connection, row), "jobs": batch_jobs(connection, batch_id)}


def refresh_duplicate_flags(connection: sqlite3.Connection, batch_id: str) -> None:
    connection.execute(
        "UPDATE video_jobs SET duplicate_of_job_id = NULL WHERE batch_id = ?", (batch_id,)
    )
    first_by_video_id: dict[str, str] = {}
    rows = connection.execute(
        "SELECT id, video_id FROM video_jobs WHERE batch_id = ? ORDER BY position", (batch_id,)
    ).fetchall()
    for row in rows:
        video_id = row["video_id"]
        if not video_id:
            continue
        if video_id in first_by_video_id:
            connection.execute(
                "UPDATE video_jobs SET duplicate_of_job_id = ? WHERE id = ?",
                (first_by_video_id[video_id], row["id"]),
            )
        else:
            first_by_video_id[video_id] = row["id"]


def plan_batch_backgrounds(connection: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        return get_batch(connection, batch_id)

    connection.execute(
        "UPDATE video_jobs SET background_asset_id = NULL WHERE batch_id = ? AND background_locked = 0",
        (batch_id,),
    )
    rows = connection.execute(
        "SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position", (batch_id,)
    ).fetchall()
    channel_ids = sorted({row["channel_id"] for row in rows if row["channel_id"]})
    plans: dict[str, tuple[dict[str, int], str | None, random.Random, list[str]]] = {}
    for channel_id in channel_ids:
        historical = connection.execute(
            """
            SELECT jobs.background_asset_id, COUNT(*) AS uses
            FROM video_jobs AS jobs JOIN batches ON batches.id = jobs.batch_id
            WHERE jobs.channel_id = ? AND jobs.background_asset_id IS NOT NULL
              AND batches.state = 'confirmed'
            GROUP BY jobs.background_asset_id
            """,
            (channel_id,),
        ).fetchall()
        usage = {item["background_asset_id"]: int(item["uses"]) for item in historical}
        latest = connection.execute(
            """
            SELECT jobs.background_asset_id
            FROM video_jobs AS jobs JOIN batches ON batches.id = jobs.batch_id
            WHERE jobs.channel_id = ? AND jobs.background_asset_id IS NOT NULL
              AND batches.state = 'confirmed'
            ORDER BY batches.confirmed_at DESC, jobs.position DESC LIMIT 1
            """,
            (channel_id,),
        ).fetchone()
        last_asset = latest["background_asset_id"] if latest else None
        pool = connection.execute(
            """
            SELECT assets.id, assets.path FROM channel_backgrounds AS links
            JOIN media_assets AS assets ON assets.id = links.asset_id
            WHERE links.channel_id = ? ORDER BY links.position, assets.id
            """,
            (channel_id,),
        ).fetchall()
        available_ids = [item["id"] for item in pool if Path(item["path"]).is_file()]
        for asset_id in available_ids:
            usage.setdefault(asset_id, 0)
        for current_job in rows:
            selected = current_job["background_asset_id"]
            if (
                current_job["channel_id"] == channel_id
                and current_job["background_locked"]
                and current_job["validation_code"] == "valid"
                and not current_job["duplicate_of_job_id"]
                and selected in available_ids
            ):
                usage[selected] = usage.get(selected, 0) + 1
        randomizer = random.Random(f"{batch_id}:{channel_id}")
        plans[channel_id] = usage, last_asset, randomizer, available_ids

    for row in rows:
        channel_id = row["channel_id"]
        if not channel_id or row["validation_code"] != "valid" or row["duplicate_of_job_id"]:
            continue
        usage, previous, randomizer, available_ids = plans[channel_id]
        if row["background_locked"]:
            selected = row["background_asset_id"]
            if selected in available_ids:
                plans[channel_id] = usage, selected, randomizer, available_ids
            continue
        if not available_ids:
            continue
        minimum = min(usage.get(asset_id, 0) for asset_id in available_ids)
        candidates = [asset_id for asset_id in available_ids if usage.get(asset_id, 0) == minimum]
        without_repeat = [asset_id for asset_id in candidates if asset_id != previous]
        if without_repeat:
            candidates = without_repeat
        randomizer.shuffle(candidates)
        selected = candidates[0]
        connection.execute(
            "UPDATE video_jobs SET background_asset_id = ? WHERE id = ?",
            (selected, row["id"]),
        )
        usage[selected] = usage.get(selected, 0) + 1
        plans[channel_id] = usage, selected, randomizer, available_ids
    connection.commit()
    plan_batch_thumbnails(connection, batch_id)
    return get_batch(connection, batch_id)


def import_batch_text(
    connection: sqlite3.Connection,
    name: str,
    content: str,
    default_channel_id: str | None,
    workflow_mode: str = "render",
) -> dict[str, Any]:
    if workflow_mode not in {"render", "download_only"}:
        raise ValueError("Batch workflow mode must be 'render' or 'download_only'.")
    if default_channel_id:
        ensure_channel(connection, default_channel_id)
    rows, import_source = parse_import_rows(content, default_channel_id)
    batch_name = name.strip() or f"Batch {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    batch_id = str(uuid.uuid4())
    now = utc_now()
    connection.execute(
        "INSERT INTO batches(id, name, workflow_mode, state, import_source, created_at) VALUES (?, ?, ?, 'draft', ?, ?)",
        (batch_id, batch_name, workflow_mode, import_source, now),
    )
    for position, row in enumerate(rows):
        imported_channel = str(row.get("channel", "")).strip()
        channel = ensure_channel(connection, default_channel_id) if default_channel_id else channel_by_imported_value(connection, imported_channel)
        raw_url = str(row.get("url", "")).strip()
        video_id, canonical_url = normalize_youtube_url(raw_url)
        connection.execute(
            """
            INSERT INTO video_jobs(
                id, batch_id, channel_id, imported_channel_name, url, canonical_url,
                video_id, row_number, position, validation_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), batch_id, channel["id"] if channel else None,
                imported_channel, raw_url, canonical_url, video_id,
                int(row["row_number"]), position, "valid" if video_id else "invalid_url", now,
            ),
        )
    refresh_duplicate_flags(connection, batch_id)
    connection.commit()
    return plan_batch_backgrounds(connection, batch_id)


def append_batch_text(
    connection: sqlite3.Connection,
    batch_id: str,
    content: str,
    default_channel_id: str | None,
) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Jobs cannot be added after a Batch is confirmed.")
    if default_channel_id:
        ensure_channel(connection, default_channel_id)
    rows, _ = parse_import_rows(content, default_channel_id)
    start = connection.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM video_jobs WHERE batch_id = ?", (batch_id,)
    ).fetchone()[0]
    now = utc_now()
    for offset, row in enumerate(rows):
        imported_channel = str(row.get("channel", "")).strip()
        channel = ensure_channel(connection, default_channel_id) if default_channel_id else channel_by_imported_value(connection, imported_channel)
        raw_url = str(row.get("url", "")).strip()
        video_id, canonical_url = normalize_youtube_url(raw_url)
        connection.execute(
            """
            INSERT INTO video_jobs(
                id, batch_id, channel_id, imported_channel_name, url, canonical_url,
                video_id, row_number, position, validation_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), batch_id, channel["id"] if channel else None,
                imported_channel, raw_url, canonical_url, video_id,
                int(row["row_number"]), start + offset, "valid" if video_id else "invalid_url", now,
            ),
        )
    refresh_duplicate_flags(connection, batch_id)
    connection.commit()
    return plan_batch_backgrounds(connection, batch_id)


def lookup_metadata_for_batch(connection: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Metadata cannot be changed after a Batch is confirmed.")
    binary = os.environ.get("YTDLP_BINARY") or shutil.which("yt-dlp") or shutil.which("yt_dlp")
    rows = connection.execute(
        "SELECT * FROM video_jobs WHERE batch_id = ? AND validation_code = 'valid' ORDER BY position",
        (batch_id,),
    ).fetchall()
    for row in rows:
        if row["duplicate_of_job_id"] or row["metadata_status"] == "ready":
            continue
        if not binary:
            connection.execute(
                "UPDATE video_jobs SET metadata_status = 'error', metadata_error = ? WHERE id = ?",
                ("yt-dlp was not found. Install it or configure YTDLP_BINARY.", row["id"]),
            )
            continue
        command = [
            binary, "--no-warnings", "--no-call-home", "--skip-download",
            "--no-playlist", "--dump-single-json", row["canonical_url"],
        ]
        try:
            completed = subprocess.run(prepare_ytdlp_command(command, connection), capture_output=True, text=True, check=False, timeout=120)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or f"yt-dlp exited with code {completed.returncode}."
                raise ValueError(detail[-1000:])
            metadata = json.loads(completed.stdout)
            found_id = str(metadata.get("id", row["video_id"]))
            if found_id != row["video_id"]:
                raise ValueError("yt-dlp returned a different video ID than the imported URL.")
            duration = metadata.get("duration")
            subtitle_tracks = simplify_subtitle_tracks(metadata)
            connection.execute(
                """
                UPDATE video_jobs
                SET video_id = ?, title = ?, duration_seconds = ?, thumbnail_url = ?,
                    subtitle_tracks_json = ?,
                    metadata_status = 'ready', metadata_error = NULL
                WHERE id = ?
                """,
                (
                    found_id,
                    str(metadata.get("title") or "Untitled video"),
                    float(duration) if duration is not None else None,
                    metadata.get("thumbnail") or f"https://i.ytimg.com/vi/{found_id}/hqdefault.jpg",
                    json.dumps(subtitle_tracks, ensure_ascii=False),
                    row["id"],
                ),
            )
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as error:
            connection.execute(
                "UPDATE video_jobs SET metadata_status = 'error', metadata_error = ? WHERE id = ?",
                (str(error)[-1000:], row["id"]),
            )
        connection.commit()
    return batch_jobs(connection, batch_id)


def preferences_for_job(connection: sqlite3.Connection, job: sqlite3.Row) -> list[str]:
    override = json.loads(job["subtitle_language_override_json"] or "[]")
    if override:
        return override
    if job["channel_id"]:
        channel = ensure_channel(connection, job["channel_id"])
        return json.loads(channel["subtitle_languages_json"] or "[]")
    return []


def resolve_job_subtitle(connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    tracks = json.loads(job["subtitle_tracks_json"] or '{"creator":[],"automatic":[]}')
    preferences = preferences_for_job(connection, job)
    selected = select_subtitle_track(preferences, tracks)
    if selected:
        connection.execute(
            """
            UPDATE video_jobs SET subtitle_language = ?, subtitle_source = ?,
                subtitle_decision = 'youtube', subtitle_error = NULL WHERE id = ?
            """,
            (selected["language"], selected["source"], job_id),
        )
        decision = "youtube"
        language = selected["language"]
        source = selected["source"]
    elif job["subtitle_decision"] == "skip":
        language = None
        source = None
        decision = "skip"
    elif job["supplied_subtitle_path"] and Path(job["supplied_subtitle_path"]).is_file():
        language = preferences[0] if preferences else "und"
        source = "supplied_file"
        decision = "use_file"
        connection.execute(
            """
            UPDATE video_jobs SET subtitle_language = ?, subtitle_source = ?,
                subtitle_decision = ?, subtitle_error = NULL WHERE id = ?
            """,
            (language, source, decision, job_id),
        )
    else:
        language = None
        source = None
        decision = "needs_decision"
        connection.execute(
            """
            UPDATE video_jobs SET subtitle_language = NULL, subtitle_source = NULL,
                subtitle_decision = ?, subtitle_error = NULL WHERE id = ?
            """,
            (decision, job_id),
        )
    if job["download_status"] == "needs_subtitle_decision" and decision != "needs_decision":
        batch_mode = connection.execute("SELECT workflow_mode FROM batches WHERE id = ?", (job["batch_id"],)).fetchone()
        next_status = "package_pending" if batch_mode and batch_mode["workflow_mode"] == "download_only" else "complete"
        connection.execute("UPDATE video_jobs SET download_status = ? WHERE id = ?", (next_status, job_id))
    connection.commit()
    fresh = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    return {
        "job": job_view(connection, fresh),
        "preferences": preferences,
        "selected": {"language": language, "source": source, "decision": decision},
    }


def inspect_job_subtitles(connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if job["metadata_status"] != "ready":
        raise ValueError("Fetch this video's metadata before inspecting subtitles.")
    return resolve_job_subtitle(connection, job_id)


def set_job_subtitle_override(
    connection: sqlite3.Connection,
    job_id: str,
    supplied_languages: Any,
) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if not isinstance(supplied_languages, list):
        raise ValueError("Subtitle language override must be a list of language codes.")
    languages = []
    seen = set()
    for supplied in supplied_languages:
        language = str(supplied).strip().replace("_", "-")
        if not language:
            continue
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
            raise ValueError(f"Invalid subtitle language code: {language}")
        if language.lower() not in seen:
            seen.add(language.lower())
            languages.append(language)
    connection.execute(
        "UPDATE video_jobs SET subtitle_language_override_json = ? WHERE id = ?",
        (json.dumps(languages, ensure_ascii=False), job_id),
    )
    connection.commit()
    return resolve_job_subtitle(connection, job_id)


def attach_job_subtitle_file(
    connection: sqlite3.Connection,
    job_id: str,
    supplied_path: str,
) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if job["metadata_status"] != "ready":
        raise ValueError("Fetch this video's metadata before attaching a subtitle file.")
    try:
        path = str(Path(supplied_path).expanduser().resolve(strict=True))
    except (OSError, RuntimeError) as error:
        raise ValueError("The subtitle file could not be found.") from error
    if not Path(path).is_file() or Path(path).suffix.lower() not in {".srt", ".vtt"}:
        raise ValueError("Choose an existing SRT or VTT file.")
    tracks = json.loads(job["subtitle_tracks_json"] or '{"creator":[],"automatic":[]}')
    preferences = preferences_for_job(connection, job)
    if select_subtitle_track(preferences, tracks):
        return resolve_job_subtitle(connection, job_id)
    connection.execute(
        "UPDATE video_jobs SET supplied_subtitle_path = ?, subtitle_decision = 'use_file' WHERE id = ?",
        (path, job_id),
    )
    connection.commit()
    return resolve_job_subtitle(connection, job_id)


def skip_job_captions(connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    if select_subtitle_track(preferences_for_job(connection, job), json.loads(job["subtitle_tracks_json"] or '{"creator":[],"automatic":[]}')):
        return resolve_job_subtitle(connection, job_id)
    connection.execute(
        "UPDATE video_jobs SET subtitle_decision = 'skip', subtitle_language = NULL, subtitle_source = NULL, subtitle_error = NULL WHERE id = ?",
        (job_id,),
    )
    connection.commit()
    return resolve_job_subtitle(connection, job_id)


def add_job_artifact(connection: sqlite3.Connection, job_id: str, kind: str, path: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO job_artifacts(id, job_id, kind, path, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), job_id, kind, path, utc_now()),
    )


def job_download_directory(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    output_root: str,
) -> Path:
    batch = connection.execute("SELECT id, name, workflow_mode FROM batches WHERE id = ?", (job["batch_id"],)).fetchone()
    channel = ensure_channel(connection, job["channel_id"])
    root = Path(output_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    folder_name = job["id"]
    if batch["workflow_mode"] == "download_only":
        title_slug = normalize_slug(str(job["title"] or job["video_id"] or "video"))[:80]
        folder_name = f"{title_slug}-{job['video_id'] or job['id'][:8]}"
    batch_folder = normalize_slug(batch["name"])
    if batch["workflow_mode"] == "download_only":
        batch_folder = f"{batch_folder}-{batch['id'][:8]}"
    directory = root.resolve() / batch_folder / channel["slug"] / folder_name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class QueueCancelled(Exception):
    def __init__(self, state: str):
        self.state = state
        super().__init__("Job cancelled by the user." if state == "cancelled" else "App heartbeat stopped; work was marked interrupted.")


def run_ytdlp(
    command: list[str],
    timeout_seconds: int = 3600,
    connection: sqlite3.Connection | None = None,
    queue_task_id: str | None = None,
    progress_base: float = 0,
    progress_span: float = 0.42,
) -> subprocess.CompletedProcess[str]:
    command = prepare_ytdlp_command(command, connection)
    if connection is not None and queue_task_id:
        stream_queue: thread_queue.Queue[str | None] = thread_queue.Queue()
        stream_command = [*command[:-1], "--newline", command[-1]]
        try:
            process = subprocess.Popen(
                stream_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                start_new_session=(os.name != "nt"),
            )
        except OSError as error:
            raise ValueError(f"yt-dlp could not start: {error}") from error
        if process.stdout is None:
            process.kill()
            raise ValueError("yt-dlp did not provide a progress stream.")

        def collect_output() -> None:
            try:
                for output_line in process.stdout:
                    stream_queue.put(output_line)
            finally:
                stream_queue.put(None)

        reader = threading.Thread(target=collect_output, daemon=True)
        reader.start()
        output: list[str] = []
        finished_output = False
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None or not finished_output:
            abort_state = queue_abort_reason(connection, queue_task_id)
            if abort_state:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                reader.join(timeout=1)
                raise QueueCancelled(abort_state)
            if time.monotonic() >= deadline:
                process.kill()
                process.wait()
                reader.join(timeout=1)
                raise ValueError("yt-dlp download exceeded the time limit.")
            try:
                output_line = stream_queue.get(timeout=0.2)
            except thread_queue.Empty:
                continue
            if output_line is None:
                finished_output = True
                continue
            line = output_line.rstrip()
            output.append(line)
            if len(output) > 80:
                del output[:20]
            match = re.search(r"\[download\]\s+([0-9]+(?:\.[0-9]+)?)%", line)
            if match:
                fraction = min(1.0, max(0.0, float(match.group(1)) / 100))
                queue_update_progress(connection, queue_task_id, "downloading", progress_base + fraction * progress_span)
        reader.join(timeout=1)
        return_code = process.wait()
        completed_text = "\n".join(output)
        if return_code != 0:
            detail = completed_text.strip() or f"yt-dlp exited with code {return_code}."
            raise ValueError(detail[-1200:])
        return subprocess.CompletedProcess(stream_command, return_code, completed_text, "")

    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"yt-dlp could not finish the requested download: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"yt-dlp exited with code {completed.returncode}."
        raise ValueError(detail[-1200:])
    return completed


def _application_tools_directory(database_path: str) -> Path:
    return Path(database_path).expanduser().resolve().parent / "tools"


def _release_asset_name(tool: str) -> tuple[str, str | None, str]:
    if os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"}:
        return ("yt-dlp.exe", None, "yt-dlp.exe") if tool == "yt-dlp" else ("deno-x86_64-pc-windows-msvc.zip", "deno.exe", "deno.exe")
    if sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        return ("yt-dlp_macos", None, "yt-dlp") if tool == "yt-dlp" else ("deno-aarch64-apple-darwin.zip", "deno", "deno")
    raise ValueError("Automatic tool updates support Windows x64 and macOS Apple Silicon only.")


def _numeric_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(number) for number in numbers)


def _tool_binary(environment_name: str, command_name: str) -> str | None:
    configured = os.environ.get(environment_name)
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    if os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR"):
        return None
    return shutil.which(command_name)


def _run_version(binary: str, label: str) -> str:
    try:
        version_flag = "-version" if label.lower() in {"ffmpeg", "ffprobe"} else "--version"
        result = subprocess.run([binary, version_flag], capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"{label} could not start: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"{label} could not start: {detail[-500:]}")
    return result.stdout.strip().splitlines()[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _github_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "youtube-video-batch-tool",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not check the latest release from GitHub: {error}") from error


def _find_github_asset(repository: str, asset_name: str) -> tuple[str, str]:
    release = _github_json(f"https://api.github.com/repos/{repository}/releases/latest")
    asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
    if asset is None:
        raise ValueError(f"The latest {repository} release has no supported asset named {asset_name}.")
    checksum = asset.get("digest")
    if not isinstance(checksum, str) or not checksum.startswith("sha256:"):
        raise ValueError(f"GitHub did not publish a SHA-256 digest for {asset_name}; refusing an unverified update.")
    return str(asset["browser_download_url"]), checksum.removeprefix("sha256:").lower()


def _download_release_asset(url: str, checksum: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "youtube-video-batch-tool"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 160 * 1024 * 1024:
                    raise ValueError("The release asset exceeds the 160 MB safety limit.")
                digest.update(chunk)
                output.write(chunk)
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Could not download a required tool update: {error}") from error
    if digest.hexdigest() != checksum:
        destination.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 verification failed for downloaded tool asset {destination.name}.")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _prune_old_tool_versions(app_tools: Path, tool: str) -> None:
    versioned: list[tuple[tuple[int, ...], Path]] = []
    for candidate in app_tools.glob(f"{tool}-*"):
        if not candidate.is_dir():
            continue
        version = candidate.name.removeprefix(f"{tool}-")
        numeric = _numeric_version(version)
        if numeric:
            versioned.append((numeric, candidate))
    versioned.sort(key=lambda item: item[0], reverse=True)
    for _, old_directory in versioned[3:]:
        try:
            shutil.rmtree(old_directory)
        except OSError:
            pass


def _install_latest_release_tool(tool: str, database_path: str) -> dict[str, Any]:
    repository = "yt-dlp/yt-dlp" if tool == "yt-dlp" else "denoland/deno"
    asset_name, archive_member, installed_name = _release_asset_name(tool)
    release = _github_json(f"https://api.github.com/repos/{repository}/releases/latest")
    release_version = str(release.get("tag_name", "")).removeprefix("v")
    if not release_version:
        raise ValueError(f"The latest {tool} release did not include a version tag.")
    asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
    if asset is None:
        raise ValueError(f"The latest {tool} release has no supported asset named {asset_name}.")
    checksum = asset.get("digest")
    if not isinstance(checksum, str) or not checksum.startswith("sha256:"):
        raise ValueError(f"GitHub did not publish a SHA-256 digest for {asset_name}; refusing an unverified update.")
    expected_hash = checksum.removeprefix("sha256:").lower()

    environment_name = "YTDLP_BINARY" if tool == "yt-dlp" else "DENO_BINARY"
    command_name = "yt-dlp" if tool == "yt-dlp" else "deno"
    current_path = _tool_binary(environment_name, command_name)
    current_version: str | None = None
    current_is_verified = False
    if current_path:
        try:
            output = _run_version(current_path, tool)
            current_version = output if tool == "yt-dlp" else output.split()[1]
            current_file = Path(current_path)
            app_tools = _application_tools_directory(database_path)
            try:
                current_relative_path = current_file.relative_to(app_tools).as_posix()
            except ValueError:
                current_relative_path = None
            if current_relative_path is not None:
                info = _read_json(app_tools / f"{tool}.json")
                current_is_verified = bool(
                    info
                    and info.get("version") == current_version
                    and info.get("relative_path") == current_relative_path
                    and info.get("sha256") == _sha256_file(current_file)
                )
            else:
                tools_root = os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR")
                manifest = _read_json(Path(tools_root) / "manifest.json") if tools_root else None
                relative_path = f"bin/{current_file.name}"
                manifest_hash = (manifest or {}).get("files_sha256", {}).get(relative_path)
                current_is_verified = not manifest_hash or manifest_hash == _sha256_file(current_file)
        except (ValueError, OSError, IndexError):
            current_version = None

    is_current = bool(
        current_version
        and _numeric_version(current_version) >= _numeric_version(release_version)
        and current_is_verified
    )
    if is_current:
        return {
            "name": tool,
            "version": current_version,
            "latest_version": release_version,
            "updated": False,
            "path": current_path,
        }

    app_tools = _application_tools_directory(database_path)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", release_version):
        raise ValueError(f"The latest {tool} release has an invalid version tag.")
    destination_directory = app_tools / f"{tool}-{release_version}"
    destination = destination_directory / installed_name
    suffix = ".zip" if archive_member else ".exe" if os.name == "nt" else ".download"
    temporary_id = uuid.uuid4().hex
    update_directory = app_tools / ".updates"
    downloaded = update_directory / f"{tool}.{temporary_id}.partial{suffix}"
    extracted_suffix = ".exe" if os.name == "nt" else ""
    extracted = update_directory / f"{tool}.{temporary_id}.extracted{extracted_suffix}"
    metadata_path = app_tools / f"{tool}.json"
    try:
        update_directory.mkdir(parents=True, exist_ok=True)
        _download_release_asset(str(asset["browser_download_url"]), expected_hash, downloaded)
        if archive_member:
            try:
                with zipfile.ZipFile(downloaded) as archive:
                    member = next((name for name in archive.namelist() if Path(name).name == archive_member), None)
                    if member is None:
                        raise ValueError(f"The {tool} archive did not contain {archive_member}.")
                    extracted.write_bytes(archive.read(member))
            except (OSError, zipfile.BadZipFile) as error:
                raise ValueError(f"The downloaded {tool} archive could not be opened: {error}") from error
            candidate = extracted
        else:
            candidate = downloaded
        if os.name != "nt":
            candidate.chmod(candidate.stat().st_mode | 0o111)
        output = _run_version(str(candidate), tool)
        installed_version = output if tool == "yt-dlp" else output.split()[1]
        if installed_version != release_version:
            raise ValueError(f"Downloaded {tool} reports version {installed_version}; expected {release_version}.")
        destination_directory.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, destination)
        metadata_temporary = app_tools / f".{tool}.{temporary_id}.json.partial"
        metadata_temporary.write_text(
            json.dumps({
                "version": installed_version,
                "sha256": _sha256_file(destination),
                "release": release_version,
                "relative_path": destination.relative_to(app_tools).as_posix(),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(metadata_temporary, metadata_path)
        os.environ[environment_name] = str(destination)
        _prune_old_tool_versions(app_tools, tool)
    finally:
        downloaded.unlink(missing_ok=True)
        extracted.unlink(missing_ok=True)
        try:
            update_directory.rmdir()
        except OSError:
            pass

    return {
        "name": tool,
        "version": installed_version,
        "latest_version": release_version,
        "updated": True,
        "path": str(destination),
    }


def _ensure_ocr_models(database_path: str) -> str:
    configured = os.environ.get("TESSDATA_DIR")
    resource_root = os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR")
    manifest = _read_json(Path(resource_root) / "manifest.json") if resource_root else None
    if not manifest:
        return configured or ""
    expected_hashes = manifest.get("tessdata_sha256", {})
    revision = manifest.get("tessdata_revision")
    if not revision:
        raise ValueError("The packaged OCR manifest does not identify its language-data revision.")
    current = Path(configured) if configured else Path(resource_root) / "tessdata"
    missing: list[str] = []
    for language in ("eng", "vie"):
        model = current / f"{language}.traineddata"
        expected = expected_hashes.get(language)
        if model.is_file() and (not expected or _sha256_file(model) == expected):
            continue
        missing.append(language)
    if not missing:
        return str(current)

    destination = _application_tools_directory(database_path).parent / "tessdata"
    destination.mkdir(parents=True, exist_ok=True)
    for language in missing:
        expected = expected_hashes.get(language)
        if not expected:
            raise ValueError(f"The packaged manifest has no SHA-256 hash for the {language} OCR model.")
        target = destination / f"{language}.traineddata"
        temporary = destination / f".{language}.{uuid.uuid4().hex}.traineddata.partial"
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{revision}/{language}.traineddata"
        _download_release_asset(url, str(expected), temporary)
        os.replace(temporary, target)
    os.environ["TESSDATA_DIR"] = str(destination)
    return str(destination)


def check_local_toolchain(database_path: str) -> dict[str, Any]:
    ffmpeg = _tool_binary("FFMPEG_BINARY", "ffmpeg")
    ffprobe = _tool_binary("FFPROBE_BINARY", "ffprobe")
    tesseract = _tool_binary("TESSERACT_BINARY", "tesseract")
    missing = [name for name, path in (("FFmpeg", ffmpeg), ("ffprobe", ffprobe), ("Tesseract", tesseract)) if not path]
    if missing:
        raise ValueError(f"Required bundled tools are missing ({', '.join(missing)}). Reinstall the app to restore its media toolchain.")
    tessdata = _ensure_ocr_models(database_path)
    try:
        ffmpeg_version = _run_version(str(ffmpeg), "FFmpeg")
        ffprobe_version = _run_version(str(ffprobe), "ffprobe")
        tesseract_version = _run_version(str(tesseract), "Tesseract")
        encoders = subprocess.run([str(ffmpeg), "-hide_banner", "-encoders"], capture_output=True, text=True, check=False, timeout=30)
        filters = subprocess.run([str(ffmpeg), "-hide_banner", "-filters"], capture_output=True, text=True, check=False, timeout=30)
        language_command = [str(tesseract)]
        if tessdata:
            language_command.extend(["--tessdata-dir", tessdata])
        language_command.append("--list-langs")
        languages = subprocess.run(language_command, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"A required media/OCR tool could not start: {error}") from error
    resource_root = os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR")
    manifest = _read_json(Path(resource_root) / "manifest.json") if resource_root else None
    if resource_root and not manifest:
        raise ValueError("The packaged tool manifest is missing or unreadable. Reinstall the app to restore its dependencies.")
    expected_versions = (manifest or {}).get("versions", {})
    actual_versions = {"ffmpeg": ffmpeg_version, "ffprobe": ffprobe_version, "tesseract": tesseract_version}
    for name, actual in actual_versions.items():
        expected = expected_versions.get(name)
        if expected and expected != actual:
            raise ValueError(f"The bundled {name} version differs from its verified package manifest. Reinstall the app to restore the media toolchain.")
    if encoders.returncode != 0 or "libx264" not in encoders.stdout or not re.search(r"\baac\b", encoders.stdout):
        raise ValueError("The installed FFmpeg is missing the libx264 or AAC encoder; reinstall the app's media toolchain.")
    if filters.returncode != 0 or " subtitles " not in filters.stdout:
        raise ValueError("The installed FFmpeg is missing the subtitles/libass filter; reinstall the app's media toolchain.")
    installed_languages = set(languages.stdout.split()) if languages.returncode == 0 else set()
    required_languages = {"eng", "vie"} if os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR") else {"eng"}
    missing_languages = required_languages - installed_languages
    if missing_languages:
        raise ValueError(f"Tesseract is missing OCR model(s): {', '.join(sorted(missing_languages))}.")
    return {
        "ffmpeg": {"version": ffmpeg_version, "ready": True},
        "ffprobe": {"version": ffprobe_version, "ready": True},
        "tesseract": {"version": tesseract_version, "ready": True, "languages": sorted(installed_languages & {"eng", "vie"})},
        "tessdata_dir": tessdata,
    }


def sync_dynamic_toolchain(database_path: str) -> dict[str, Any]:
    yt_dlp = _install_latest_release_tool("yt-dlp", database_path)
    deno = _install_latest_release_tool("deno", database_path)
    return {"yt_dlp": yt_dlp, "deno": deno}


def _configured_cookie_path(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT value FROM app_meta WHERE key = 'youtube_cookies_path'").fetchone()
    if row is None:
        return None
    path = Path(row["value"]).expanduser()
    validate_cookie_file(path)
    return str(path.resolve())


def validate_cookie_file(path: Path) -> None:
    if not path.is_file():
        raise ValueError("The configured cookies.txt file is missing. Choose it again in Settings or clear the cookie setting.")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            header = source.readline().strip()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"The selected cookies.txt file could not be read: {error}") from error
    if header not in {"# HTTP Cookie File", "# Netscape HTTP Cookie File"}:
        raise ValueError("The selected cookie file is not in Netscape cookies.txt format. Export it again as cookies.txt.")


def youtube_cookie_settings(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT value FROM app_meta WHERE key = 'youtube_cookies_path'").fetchone()
    if row is None:
        return {"path": None, "configured": False, "available": False, "valid_format": False}
    path = Path(row["value"]).expanduser()
    try:
        validate_cookie_file(path)
        valid_format = True
    except ValueError:
        valid_format = False
    return {"path": str(path), "configured": True, "available": path.is_file(), "valid_format": valid_format}


def set_youtube_cookie_file(connection: sqlite3.Connection, raw_path: Any) -> dict[str, Any]:
    if raw_path is None or not str(raw_path).strip():
        connection.execute("DELETE FROM app_meta WHERE key = 'youtube_cookies_path'")
        connection.commit()
        return youtube_cookie_settings(connection)
    path = Path(str(raw_path)).expanduser().resolve()
    validate_cookie_file(path)
    connection.execute(
        "INSERT INTO app_meta(key, value) VALUES ('youtube_cookies_path', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(path),),
    )
    connection.commit()
    return youtube_cookie_settings(connection)


def prepare_ytdlp_command(command: list[str], connection: sqlite3.Connection | None = None) -> list[str]:
    deno = _tool_binary("DENO_BINARY", "deno")
    packaged_runtime = bool(os.environ.get("YOUTUBE_BATCH_RESOURCE_DIR"))
    prefix: list[str] = []
    if not deno:
        if packaged_runtime:
            raise ValueError("The bundled Deno JavaScript runtime is missing; restart the app so it can be restored.")
    else:
        try:
            result = subprocess.run([deno, "--version"], capture_output=True, text=True, check=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"The Deno JavaScript runtime could not start: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"Deno exited with code {result.returncode}."
            raise ValueError(f"The Deno JavaScript runtime could not start: {detail[-400:]}")
        prefix.extend(["--js-runtimes", f"deno:{deno}"])
    if connection is not None:
        cookie_path = _configured_cookie_path(connection)
        if cookie_path:
            prefix.extend(["--cookies", cookie_path])
    return [command[0], *prefix, *command[1:]]


def download_job_sources(
    connection: sqlite3.Connection,
    batch_id: str,
    job_id: str,
    output_root: str,
    include_video: bool,
    queue_task_id: str | None = None,
    download_only: bool = False,
) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    job = connection.execute(
        "SELECT * FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)
    ).fetchone()
    if batch is None or job is None:
        raise ValueError("Batch or Video job was not found.")
    if batch["state"] != "confirmed":
        raise ValueError("Confirm the Batch plan before downloading source media.")
    if job["metadata_status"] != "ready":
        raise ValueError("Fetch video metadata before downloading source media.")
    if not job["channel_id"]:
        raise ValueError("Assign this job to a Channel before downloading.")
    if job["duplicate_of_job_id"]:
        raise ValueError("Remove or resolve this duplicate URL before downloading.")
    binary = os.environ.get("YTDLP_BINARY") or shutil.which("yt-dlp") or shutil.which("yt_dlp")
    if not binary:
        raise ValueError("yt-dlp was not found. Install it or configure YTDLP_BINARY.")
    directory = job_download_directory(connection, job, output_root)
    template = str(directory / "source.%(ext)s")
    include_video_value = 1 if include_video else 0
    connection.execute(
        "UPDATE video_jobs SET include_video_source = ?, download_status = 'downloading', download_progress = ?, download_error = NULL WHERE id = ?",
        (include_video_value, 0.02 if queue_task_id else None, job_id),
    )
    connection.commit()
    thumbnail_mode = effective_thumbnail_mode(connection, job)
    command = [binary, "--no-warnings", "--no-call-home", "--no-playlist", "--output", template]
    if download_only or thumbnail_mode != "skip":
        command.extend(["--write-thumbnail", "--convert-thumbnails", "jpg"])
    if include_video:
        command.extend(["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"])
    else:
        command.extend(["-f", "bestaudio/best"])
    command.append(job["canonical_url"])
    try:
        run_ytdlp(command, connection=connection, queue_task_id=queue_task_id)
        files = [path for path in directory.glob("source.*") if path.is_file()]
        thumbnails = [path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        media_files = [path for path in files if path not in thumbnails]
        media_file = next((path for path in media_files if path.suffix.lower() in {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".opus", ".ogg", ".wav", ".aac", ".flac"}), None)
        if not media_file:
            raise ValueError("yt-dlp reported success but did not create a source media file.")
        thumbnail_file = next(iter(thumbnails), None)
        if thumbnail_mode != "skip" and not thumbnail_file:
            raise ValueError("yt-dlp downloaded the source media but did not save a thumbnail.")
        media_kind = "source_video" if include_video else "source_audio"
        connection.execute(
            """
            UPDATE video_jobs SET source_audio_path = ?, source_video_path = ?, source_thumbnail_path = ?,
                download_status = 'resolving_subtitles', download_error = NULL WHERE id = ?
            """,
            (None if include_video else str(media_file), str(media_file) if include_video else None, str(thumbnail_file) if thumbnail_file else None, job_id),
        )
        add_job_artifact(connection, job_id, media_kind, str(media_file))
        if thumbnail_file:
            add_job_artifact(connection, job_id, "source_thumbnail", str(thumbnail_file))
            if download_only:
                pass
            elif thumbnail_mode == "auto":
                if queue_task_id:
                    queue_set_stage(connection, queue_task_id, "thumbnail_ocr", 0.45)
                ocr_text, ocr_confidence, ocr_error = recognize_thumbnail_text(str(thumbnail_file), effective_thumbnail_languages(connection, job))
                ocr_status = "awaiting_confirmation" if ocr_text and ocr_confidence is not None and ocr_confidence >= 0.55 and not ocr_error else "needs_review"
                connection.execute(
                    "UPDATE video_jobs SET thumbnail_ocr_text = ?, thumbnail_ocr_confidence = ?, thumbnail_text = ?, thumbnail_ocr_status = ?, thumbnail_error = ? WHERE id = ?",
                    (ocr_text, ocr_confidence, ocr_text, ocr_status, ocr_error, job_id),
                )
            elif thumbnail_mode == "manual":
                connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'manual', thumbnail_error = NULL WHERE id = ?", (job_id,))
        elif not download_only:
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'skipped', thumbnail_error = NULL WHERE id = ?", (job_id,))
        connection.commit()

        resolution = resolve_job_subtitle(connection, job_id)
        selection = resolution["selected"]
        if selection["source"] in {"creator", "automatic"}:
            subtitle_template = str(directory / "subtitle.%(ext)s")
            subtitle_command = [binary, "--no-warnings", "--no-call-home", "--no-playlist", "--skip-download",
                                "--output", subtitle_template, "--sub-langs", selection["language"],
                                "--sub-format", "vtt/best"]
            subtitle_command.append("--write-subs" if selection["source"] == "creator" else "--write-auto-subs")
            subtitle_command.append(job["canonical_url"])
            if queue_task_id:
                queue_set_stage(connection, queue_task_id, "captions", 0.48)
            run_ytdlp(subtitle_command, connection=connection, queue_task_id=queue_task_id, progress_base=0.48, progress_span=0.08)
            subtitle_files = [path for path in directory.glob("subtitle*") if path.is_file()]
            subtitle_file = next((path for path in subtitle_files if path.suffix.lower() in {".vtt", ".srt", ".ttml", ".srv3", ".json3"}), None)
            if not subtitle_file:
                raise ValueError("The selected YouTube subtitle track was not downloaded.")
            connection.execute(
                "UPDATE video_jobs SET subtitle_decision = 'youtube', subtitle_error = NULL WHERE id = ?",
                (job_id,),
            )
            add_job_artifact(connection, job_id, "subtitle_youtube", str(subtitle_file))
            connection.commit()
        elif selection["decision"] == "use_file" and job["supplied_subtitle_path"]:
            add_job_artifact(connection, job_id, "subtitle_supplied", job["supplied_subtitle_path"])
            connection.commit()
        final_decision = resolve_job_subtitle(connection, job_id)["selected"]["decision"]
        status = "needs_subtitle_decision" if final_decision == "needs_decision" else "complete"
        connection.execute("UPDATE video_jobs SET download_status = ?, download_progress = ? WHERE id = ?", (status, 1 if status == "complete" else None, job_id))
        if queue_task_id:
            queue_update_progress(connection, queue_task_id, "waiting_for_captions" if status == "needs_subtitle_decision" else "downloading", 0.52 if status == "needs_subtitle_decision" else 0.55)
        connection.commit()
    except ValueError as error:
        connection.execute(
            "UPDATE video_jobs SET download_status = 'error', download_progress = NULL, download_error = ? WHERE id = ?",
            (str(error)[-1200:], job_id),
        )
        connection.commit()
    fresh = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    return job_view(connection, fresh)


def media_probe(path: str) -> dict[str, Any]:
    binary = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
    if not binary:
        raise ValueError("ffprobe was not found. Install FFmpeg or configure FFPROBE_BINARY.")
    try:
        completed = subprocess.run(
            [binary, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"ffprobe could not inspect the media file: {error}") from error
    if completed.returncode != 0:
        raise ValueError((completed.stderr.strip() or "ffprobe could not read the media file.")[-1000:])
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("ffprobe returned invalid media information.") from error


def frame_from_media(path: str) -> dict[str, Any]:
    probe = media_probe(path)
    stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("The selected background has no video stream.")
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    rate = parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
    if width <= 0 or height <= 0 or not rate or rate <= 0:
        raise ValueError("The selected background has incomplete resolution or frame-rate metadata.")
    return {"width": width, "height": height, "frame_rate": round(rate, 6)}


def media_duration(path: str) -> float | None:
    probe = media_probe(path)
    duration = probe.get("format", {}).get("duration")
    try:
        parsed = float(duration)
        return parsed if parsed > 0 else None
    except (ValueError, TypeError):
        return None


def output_configuration(connection: sqlite3.Connection, job: sqlite3.Row) -> dict[str, Any]:
    if not job["background_asset_id"]:
        raise ValueError("Assign a background to this video job before configuring output.")
    asset = connection.execute("SELECT path FROM media_assets WHERE id = ?", (job["background_asset_id"],)).fetchone()
    if asset is None or not Path(asset["path"]).is_file():
        raise ValueError("The assigned background file is missing. Relink it before rendering.")
    background_frame = frame_from_media(asset["path"])
    config = json.loads(job["output_profile_json"] or '{"profile":"720p","frame_preference":null,"fit_mode":"crop"}')
    profile = config.get("profile", "720p")
    if profile == "720p":
        profile_frame = {"width": 1280, "height": 720, "frame_rate": background_frame["frame_rate"]}
    elif profile == "match_background":
        profile_frame = dict(background_frame)
    elif profile == "custom":
        profile_frame = {
            "width": int(config.get("custom_width", 1280)),
            "height": int(config.get("custom_height", 720)),
            "frame_rate": float(config.get("custom_frame_rate", background_frame["frame_rate"])),
        }
    else:
        raise ValueError("Choose 720p, Match background, or Custom output profile.")
    if profile_frame["width"] < 16 or profile_frame["height"] < 16 or profile_frame["width"] % 2 or profile_frame["height"] % 2:
        raise ValueError("Output dimensions must be even numbers of at least 16 pixels.")
    if not 1 <= profile_frame["frame_rate"] <= 120:
        raise ValueError("Output frame rate must be between 1 and 120 fps.")
    ratio_delta = abs((profile_frame["width"] / profile_frame["height"]) / (background_frame["width"] / background_frame["height"]) - 1)
    has_mismatch = ratio_delta > 0.005
    frame_preference = config.get("frame_preference")
    if frame_preference == "background":
        output_frame = dict(background_frame)
    else:
        output_frame = dict(profile_frame)
    fit_mode = config.get("fit_mode", "crop")
    if fit_mode not in {"crop", "contain"}:
        raise ValueError("Choose crop-to-fill or contain/pad for the background video.")
    return {
        "profile": profile,
        "background_frame": background_frame,
        "profile_frame": profile_frame,
        "output_frame": output_frame,
        "frame_preference": frame_preference,
        "fit_mode": fit_mode,
        "has_frame_mismatch": has_mismatch,
        "requires_frame_decision": has_mismatch and frame_preference not in {"profile", "background"},
    }


def inspect_job_render(connection: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    try:
        plan = output_configuration(connection, job)
    except ValueError as error:
        return record_preflight_failure(str(error))
    plan["job"] = job_view(connection, job)
    return plan


def configure_job_output(
    connection: sqlite3.Connection,
    job_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError("Video job was not found.")
    current = json.loads(job["output_profile_json"] or '{"profile":"720p","frame_preference":null,"fit_mode":"crop"}')
    profile = str(params.get("profile", current.get("profile", "720p")))
    if profile not in {"720p", "match_background", "custom"}:
        raise ValueError("Choose 720p, Match background, or Custom output profile.")
    frame_preference = params.get("frame_preference", current.get("frame_preference"))
    if frame_preference not in {None, "profile", "background"}:
        raise ValueError("Frame preference must be profile or background.")
    fit_mode = str(params.get("fit_mode", current.get("fit_mode", "crop")))
    if fit_mode not in {"crop", "contain"}:
        raise ValueError("Fit mode must be crop or contain.")
    config = {"profile": profile, "frame_preference": frame_preference, "fit_mode": fit_mode}
    if profile == "custom":
        try:
            config.update({
                "custom_width": int(params.get("custom_width", current.get("custom_width", 1280))),
                "custom_height": int(params.get("custom_height", current.get("custom_height", 720))),
                "custom_frame_rate": float(params.get("custom_frame_rate", current.get("custom_frame_rate", 30))),
            })
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Custom output dimensions and frame rate must be valid numbers.") from error
    connection.execute("UPDATE video_jobs SET output_profile_json = ?, render_status = 'not_started', render_error = NULL, render_progress = NULL, output_video_path = NULL, srt_sidecar_path = NULL, encoder_used = NULL WHERE id = ?", (json.dumps(config), job_id))
    connection.commit()
    return inspect_job_render(connection, job_id)


def configure_batch_output(connection: sqlite3.Connection, batch_id: str, params: dict[str, Any]) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    job_ids = params.get("job_ids")
    if not isinstance(job_ids, list) or not job_ids:
        raise ValueError("Select at least one video job for bulk output settings.")
    if len(job_ids) > 1000:
        raise ValueError("Bulk output settings are limited to 1000 video jobs per request.")
    normalized_ids = list(dict.fromkeys(str(item) for item in job_ids))
    jobs = connection.execute(
        f"SELECT id FROM video_jobs WHERE batch_id = ? AND id IN ({','.join('?' for _ in normalized_ids)})",
        (batch_id, *normalized_ids),
    ).fetchall()
    if len(jobs) != len(normalized_ids):
        raise ValueError("One or more selected jobs do not belong to this Batch.")
    profile = str(params.get("profile", "720p"))
    frame_preference = params.get("frame_preference")
    fit_mode = str(params.get("fit_mode", "crop"))
    if profile not in {"720p", "match_background", "custom"}:
        raise ValueError("Choose 720p, Match background, or Custom output profile.")
    if frame_preference not in {None, "profile", "background"}:
        raise ValueError("Frame preference must be profile or background.")
    if fit_mode not in {"crop", "contain"}:
        raise ValueError("Fit mode must be crop or contain.")
    config: dict[str, Any] = {"profile": profile, "frame_preference": frame_preference, "fit_mode": fit_mode}
    if profile == "custom":
        try:
            config.update({
                "custom_width": int(params.get("custom_width", 1280)),
                "custom_height": int(params.get("custom_height", 720)),
                "custom_frame_rate": float(params.get("custom_frame_rate", 30)),
            })
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Custom output dimensions and frame rate must be valid numbers.") from error
        if config["custom_width"] < 16 or config["custom_height"] < 16 or config["custom_width"] % 2 or config["custom_height"] % 2:
            raise ValueError("Custom output dimensions must be even numbers of at least 16 pixels.")
        if not 1 <= config["custom_frame_rate"] <= 120:
            raise ValueError("Custom output frame rate must be between 1 and 120 fps.")
    encoded = json.dumps(config)
    connection.executemany(
        "UPDATE video_jobs SET output_profile_json = ?, render_status = 'not_started', render_error = NULL, render_progress = NULL, output_video_path = NULL, srt_sidecar_path = NULL, encoder_used = NULL WHERE id = ?",
        [(encoded, job_id) for job_id in normalized_ids],
    )
    connection.commit()
    return get_batch(connection, batch_id)


def normalize_subtitle_to_srt(source_path: str, destination: Path) -> Path:
    try:
        raw = Path(source_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"The selected subtitle file could not be read: {error}") from error
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues: list[tuple[str, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if not lines or lines[0].lstrip().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            continue
        match = re.match(r"\s*((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})", lines[time_index])
        if not match:
            continue
        def srt_time(value: str) -> str:
            parts = value.replace(".", ",").split(":")
            if len(parts) == 2:
                parts.insert(0, "00")
            return ":".join(parts)
        text_lines = [html.unescape(line.strip()) for line in lines[time_index + 1:] if line.strip()]
        if text_lines:
            cues.append((f"{srt_time(match.group(1))} --> {srt_time(match.group(2))}", "\n".join(text_lines)))
    if not cues:
        raise ValueError("The chosen subtitle file does not contain any readable SRT/VTT captions.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n\n".join(f"{index}\n{timing}\n{text}" for index, (timing, text) in enumerate(cues, 1)) + "\n", encoding="utf-8")
    return destination


def ass_color(hex_color: str, opacity: float = 1) -> str:
    color = hex_color.lstrip("#")
    alpha = round((1 - opacity) * 255)
    return f"&H{alpha:02X}{color[4:6]}{color[2:4]}{color[0:2]}"


def write_ass_subtitle(srt_path: Path, ass_path: Path, style: dict[str, Any], frame: dict[str, Any]) -> Path:
    srt_text = srt_path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", srt_text.replace("\r\n", "\n").strip())
    cues: list[str] = []
    anchors = {
        "bottom-left": 1, "bottom-center": 2, "bottom-right": 3,
        "middle-left": 4, "middle-center": 5, "middle-right": 6,
        "top-left": 7, "top-center": 8, "top-right": 9,
    }
    anchor = anchors[style["alignment"]]
    x = round(frame["width"] * style["position_x"] / 100)
    y = round(frame["height"] * style["position_y"] / 100)

    def ass_timestamp(value: str) -> str:
        hours, minutes, seconds = value.replace(",", ".").split(":")
        whole, fraction = seconds.split(".", 1)
        centiseconds = round(int((fraction + "00")[:3]) / 10)
        if centiseconds == 100:
            centiseconds = 0
            whole = str(int(whole) + 1).zfill(2)
        return f"{int(hours)}:{minutes}:{whole}.{centiseconds:02d}"

    for block in blocks:
        lines = block.splitlines()
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = re.match(r"\s*((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})\s+-->\s+((?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})", lines[timing_index])
        if not timing:
            continue
        def timestamp_with_hours(value: str) -> str:
            parts = value.replace(",", ".").split(":")
            if len(parts) == 2:
                parts.insert(0, "00")
            return ":".join(parts)
        start = ass_timestamp(timestamp_with_hours(timing.group(1)))
        end = ass_timestamp(timestamp_with_hours(timing.group(2)))
        body = "\\N".join(line.strip() for line in lines[timing_index + 1:] if line.strip())
        body = html.unescape(body)
        body = re.sub(r"<[^>]*>", "", body)
        body = body.replace("{", r"\{").replace("}", r"\}")
        if body:
            cues.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\an{anchor}\\pos({x},{y})}}{body}")
    if not cues:
        raise ValueError("Could not create render subtitles from the normalized SRT sidecar.")
    bold = -1 if style.get("bold", False) else 0
    back_color = ass_color(style["background_color"], style["background_opacity"] if style["background_enabled"] else 0)
    border_style = 3 if style["background_enabled"] else 1
    content = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {frame['width']}", f"PlayResY: {frame['height']}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Default,{style['font_family']},{style['font_size']},{ass_color(style['text_color'])},&H000000FF,{ass_color(style['outline_color'])},{back_color},{bold},0,0,0,100,100,0,0,{border_style},{style['outline_width']},{style['shadow']},{anchor},0,0,0,1",
        "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text", *cues, "",
    ])
    ass_path.write_text(content, encoding="utf-8")
    return ass_path


def ffmpeg_filter_path(path: str) -> str:
    value = str(Path(path).resolve()).replace("\\", "/")
    for character in ("\\", "'", ":", ",", "[", "]"):
        value = value.replace(character, "\\" + character)
    return value


def render_job_video(connection: sqlite3.Connection, batch_id: str, job_id: str, queue_task_id: str | None = None) -> dict[str, Any]:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)).fetchone()
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if not job or not batch:
        raise ValueError("Batch or Video job was not found.")
    def record_preflight_failure(message: str) -> dict[str, Any]:
        connection.execute(
            "UPDATE video_jobs SET render_status = 'error', render_error = ?, render_progress = NULL WHERE id = ?",
            (message[-1600:], job_id),
        )
        connection.commit()
        fresh_job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
        return job_view(connection, fresh_job)
    if batch["state"] != "confirmed":
        raise ValueError("Confirm the Batch plan before rendering video jobs.")
    if job["download_status"] != "complete":
        raise ValueError("Finish source downloads and resolve the subtitle choice before rendering.")
    source_path = job["source_audio_path"] or job["source_video_path"]
    if not source_path or not Path(source_path).is_file():
        raise ValueError("The downloaded source audio/video file is missing.")
    try:
        plan = output_configuration(connection, job)
    except ValueError as error:
        return record_preflight_failure(str(error))
    if plan["requires_frame_decision"]:
        raise ValueError("The background aspect ratio differs from the output profile. Choose profile frame or background frame first.")
    if job["subtitle_decision"] == "needs_decision":
        raise ValueError("Choose a subtitle file or skip captions before rendering.")
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not ffmpeg:
        return record_preflight_failure("FFmpeg was not found. Install FFmpeg or configure FFMPEG_BINARY.")
    try:
        filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=False, timeout=20)
        encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return record_preflight_failure(f"FFmpeg capability detection failed: {error}")
    if "libx264" not in encoders.stdout:
        return record_preflight_failure("This FFmpeg build does not include the libx264 encoder required for H.264 output.")
    if " aac " not in encoders.stdout and not re.search(r"\baac\b", encoders.stdout):
        return record_preflight_failure("This FFmpeg build does not include an AAC audio encoder.")
    subtitle_path: str | None = None
    if job["subtitle_decision"] in {"youtube", "use_file"}:
        if job["subtitle_decision"] == "use_file":
            subtitle_path = job["supplied_subtitle_path"]
        else:
            subtitle_artifact = connection.execute("SELECT path FROM job_artifacts WHERE job_id = ? AND kind = 'subtitle_youtube' ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
            subtitle_path = subtitle_artifact["path"] if subtitle_artifact else None
        if not subtitle_path or not Path(subtitle_path).is_file():
            return record_preflight_failure("The selected subtitle track is missing. Re-download source subtitles before rendering.")
        if " subtitles " not in filters.stdout:
            return record_preflight_failure("This FFmpeg build has no subtitles/libass filter. Choose FFmpeg with libass enabled or skip captions for this job.")
    background_row = connection.execute("SELECT path FROM media_assets WHERE id = ?", (job["background_asset_id"],)).fetchone()
    if not background_row or not Path(background_row["path"]).is_file():
        raise ValueError("The assigned background file is missing. Relink it before rendering.")
    directory = Path(source_path).parent
    output_path = directory / "final-video.mp4"
    temporary_output = directory / "final-video.partial.mp4"
    sidecar_path: Path | None = None
    ass_subtitle: Path | None = None
    try:
        video_filter = f"fps={plan['output_frame']['frame_rate']},scale={plan['output_frame']['width']}:{plan['output_frame']['height']}:force_original_aspect_ratio={'increase' if plan['fit_mode'] == 'crop' else 'decrease'}"
        if plan["fit_mode"] == "crop":
            video_filter += f",crop={plan['output_frame']['width']}:{plan['output_frame']['height']}"
        else:
            video_filter += f",pad={plan['output_frame']['width']}:{plan['output_frame']['height']}:(ow-iw)/2:(oh-ih)/2:color=black"
        video_filter += ",setsar=1"
        normalized_subtitle: Path | None = None
        if subtitle_path:
            sidecar_path = directory / "captions.srt"
            normalize_subtitle_to_srt(subtitle_path, sidecar_path)
            normalized_subtitle = sidecar_path
            preset_id = job["subtitle_preset_id"] or connection.execute("SELECT default_subtitle_preset_id FROM channels WHERE id = ?", (job["channel_id"],)).fetchone()[0]
            preset = connection.execute("SELECT style_json FROM subtitle_presets WHERE id = ?", (preset_id,)).fetchone() if preset_id else None
            style = validate_subtitle_style(json.loads(preset["style_json"]) if preset else DEFAULT_SUBTITLE_STYLE)
            ass_subtitle = directory / "captions.render.ass"
            write_ass_subtitle(normalized_subtitle, ass_subtitle, style, plan["output_frame"])
            video_filter += f",subtitles=filename='{ffmpeg_filter_path(str(ass_subtitle))}'"
        connection.execute("UPDATE video_jobs SET render_status = 'rendering', render_error = NULL, render_progress = 0.05 WHERE id = ?", (job_id,))
        if queue_task_id:
            queue_set_stage(connection, queue_task_id, "rendering", 0.55)
        connection.commit()
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-stream_loop", "-1", "-i", background_row["path"],
            "-i", source_path, "-map", "0:v:0", "-map", "1:a:0", "-vf", video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest",
            "-progress", "pipe:1", "-nostats", "-stats_period", "0.5", str(temporary_output),
        ]
        duration = media_duration(source_path)
        progress_values: dict[str, str] = {}
        last_progress_commit = 0.0
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as error_log:
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_log, text=True, bufsize=1)
            except OSError as error:
                raise ValueError(f"FFmpeg could not start: {error}") from error
            if process.stdout is None:
                process.kill()
                raise ValueError("FFmpeg did not provide render progress output.")
            started_at = time.monotonic()
            for raw_line in process.stdout:
                if queue_task_id:
                    abort_state = queue_abort_reason(connection, queue_task_id)
                    if abort_state:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise QueueCancelled(abort_state)
                line = raw_line.strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                progress_values[key] = value
                timestamp = progress_values.get("out_time_us") or progress_values.get("out_time_ms")
                if duration and timestamp:
                    try:
                        fraction = max(0.02, min(0.99, int(timestamp) / 1_000_000 / duration))
                    except ValueError:
                        fraction = None
                    now = time.monotonic()
                    if fraction is not None and now - last_progress_commit >= 0.45:
                        connection.execute("UPDATE video_jobs SET render_progress = ? WHERE id = ?", (fraction, job_id))
                        if queue_task_id:
                            queue_update_progress(connection, queue_task_id, "rendering", 0.55 + fraction * 0.45)
                        connection.commit()
                        last_progress_commit = now
                if progress_values.get("progress") == "end":
                    break
            try:
                return_code = process.wait(timeout=max(1, 24 * 60 * 60 - (time.monotonic() - started_at)))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise ValueError("FFmpeg render exceeded the 24-hour time limit.")
            error_log.seek(0)
            error_text = error_log.read().strip()
        if return_code != 0:
            raise ValueError((error_text or f"FFmpeg exited with code {return_code}.")[-1600:])
        if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
            raise ValueError("FFmpeg finished without creating a video file.")
        temporary_output.replace(output_path)
        connection.execute(
            "UPDATE video_jobs SET render_status = 'complete', render_error = NULL, render_progress = 1, output_video_path = ?, srt_sidecar_path = ?, encoder_used = 'libx264' WHERE id = ?",
            (str(output_path), str(sidecar_path) if sidecar_path else None, job_id),
        )
        add_job_artifact(connection, job_id, "rendered_video", str(output_path))
        if sidecar_path:
            add_job_artifact(connection, job_id, "caption_srt", str(sidecar_path))
        connection.commit()
        if ass_subtitle:
            ass_subtitle.unlink(missing_ok=True)
    except QueueCancelled as error:
        temporary_output.unlink(missing_ok=True)
        if ass_subtitle:
            ass_subtitle.unlink(missing_ok=True)
        status = "interrupted" if error.state == "interrupted" else "cancelled"
        connection.execute("UPDATE video_jobs SET render_status = ?, render_error = ?, render_progress = NULL WHERE id = ?", (status, str(error)[-1600:], job_id))
        connection.commit()
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        temporary_output.unlink(missing_ok=True)
        if ass_subtitle:
            ass_subtitle.unlink(missing_ok=True)
        connection.execute("UPDATE video_jobs SET render_status = 'error', render_error = ?, render_progress = NULL WHERE id = ?", (str(error)[-1600:], job_id))
        connection.commit()
    fresh = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (job_id,)).fetchone()
    return job_view(connection, fresh)


def update_batch_job(
    connection: sqlite3.Connection,
    batch_id: str,
    job_id: str,
    url: str | None,
    channel_id: str | None,
    update_channel: bool,
) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Jobs cannot be changed after a Batch is confirmed.")
    job = connection.execute(
        "SELECT * FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)
    ).fetchone()
    if job is None:
        raise ValueError("Video job was not found in this Batch.")
    effective_channel_id = channel_id if update_channel else job["channel_id"]
    if effective_channel_id:
        channel = ensure_channel(connection, effective_channel_id)
        imported_channel_name = channel["name"] if update_channel else job["imported_channel_name"]
    else:
        imported_channel_name = ""
    new_url = job["url"] if url is None else url.strip()
    video_id, canonical_url = normalize_youtube_url(new_url)
    connection.execute(
        """
        UPDATE video_jobs SET channel_id = ?, imported_channel_name = ?, url = ?,
            canonical_url = ?, video_id = ?, validation_code = ?, title = NULL,
            duration_seconds = NULL, thumbnail_url = NULL, metadata_status = 'pending',
            metadata_error = NULL, background_asset_id = NULL, background_locked = 0
        WHERE id = ?
        """,
        (effective_channel_id, imported_channel_name, new_url, canonical_url, video_id,
         "valid" if video_id else "invalid_url", job_id),
    )
    refresh_duplicate_flags(connection, batch_id)
    connection.commit()
    planned = plan_batch_backgrounds(connection, batch_id)
    return next(item for item in planned["jobs"] if item["id"] == job_id)


def remove_batch_job(connection: sqlite3.Connection, batch_id: str, job_id: str) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "draft":
        raise ValueError("Jobs cannot be removed after a Batch is confirmed.")
    job = connection.execute(
        "SELECT position FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)
    ).fetchone()
    if job is None:
        raise ValueError("Video job was not found in this Batch.")
    connection.execute("DELETE FROM video_jobs WHERE id = ?", (job_id,))
    connection.execute("UPDATE video_jobs SET position = position - 1 WHERE batch_id = ? AND position > ?", (batch_id, job["position"]))
    refresh_duplicate_flags(connection, batch_id)
    connection.commit()
    return plan_batch_backgrounds(connection, batch_id)


def override_batch_background(
    connection: sqlite3.Connection,
    batch_id: str,
    job_id: str,
    asset_id: str,
) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    job = connection.execute(
        "SELECT * FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)
    ).fetchone()
    if batch is None or job is None:
        raise ValueError("Batch or Video job was not found.")
    if batch["state"] != "draft":
        raise ValueError("Assignments are fixed after a Batch is confirmed.")
    if not job["channel_id"]:
        raise ValueError("Assign this job to a Channel before choosing a Background.")
    asset = connection.execute(
        """
        SELECT assets.* FROM media_assets AS assets
        JOIN channel_backgrounds AS links ON links.asset_id = assets.id
        WHERE assets.id = ? AND links.channel_id = ?
        """,
        (asset_id, job["channel_id"]),
    ).fetchone()
    if asset is None or not Path(asset["path"]).is_file():
        raise ValueError("Choose an available Background from this Channel's pool.")
    connection.execute(
        "UPDATE video_jobs SET background_asset_id = ?, background_locked = 1 WHERE id = ?",
        (asset_id, job_id),
    )
    connection.commit()
    return next(item for item in batch_jobs(connection, batch_id) if item["id"] == job_id)


def confirm_batch(connection: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] == "confirmed":
        return get_batch(connection, batch_id)
    jobs = batch_jobs(connection, batch_id)
    if not jobs:
        raise ValueError("Add at least one video job before confirming a Batch.")
    unresolved = [job for job in jobs if job["readiness"] != "ready"]
    if unresolved:
        first = unresolved[0]
        raise ValueError(
            f"Resolve {len(unresolved)} job(s) before confirming. First issue: {first['readiness']} on row {first['row_number']}."
        )
    for job in connection.execute("SELECT * FROM video_jobs WHERE batch_id = ? ORDER BY position", (batch_id,)).fetchall():
        mode = effective_thumbnail_mode(connection, job)
        languages = effective_thumbnail_languages(connection, job)
        connection.execute(
            "UPDATE video_jobs SET thumbnail_mode_snapshot = ?, thumbnail_ocr_languages_json = ?, thumbnail_ocr_status = CASE WHEN ? = 'skip' THEN 'skipped' ELSE thumbnail_ocr_status END WHERE id = ?",
            (mode, json.dumps(languages), mode, job["id"]),
        )
    connection.execute(
        "UPDATE batches SET state = 'confirmed', confirmed_at = ? WHERE id = ?",
        (utc_now(), batch_id),
    )
    connection.commit()
    return get_batch(connection, batch_id)


def list_batches(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM batches ORDER BY created_at DESC, id DESC").fetchall()
    return [batch_summary(connection, row) for row in rows]


QUEUE_HEARTBEAT_TIMEOUT_SECONDS = 14


def queue_log(connection: sqlite3.Connection, task_id: str, message: str, level: str = "info") -> None:
    connection.execute(
        "INSERT INTO queue_task_logs(id, task_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, level, str(message)[-2000:], utc_now()),
    )
    connection.execute("UPDATE queue_tasks SET updated_at = ? WHERE id = ?", (utc_now(), task_id))
    connection.commit()


def queue_task_view(connection: sqlite3.Connection, row: sqlite3.Row, include_logs: bool = True) -> dict[str, Any]:
    job = connection.execute("SELECT title, video_id FROM video_jobs WHERE id = ?", (row["job_id"],)).fetchone()
    view = {
        "id": row["id"], "batch_id": row["batch_id"], "job_id": row["job_id"],
        "title": job["title"] if job else None, "video_id": job["video_id"] if job else None,
        "pipeline": row["pipeline"],
        "state": row["state"], "stage": row["stage"], "progress": row["progress"],
        "output_root": row["output_root"], "include_video_source": bool(row["include_video_source"]),
        "error": row["error"], "cancel_requested": bool(row["cancel_requested"]),
        "created_at": row["created_at"], "started_at": row["started_at"],
        "updated_at": row["updated_at"], "completed_at": row["completed_at"],
    }
    if include_logs:
        view["logs"] = [
            {"level": log["level"], "message": log["message"], "created_at": log["created_at"]}
            for log in connection.execute(
                "SELECT level, message, created_at FROM queue_task_logs WHERE task_id = ? ORDER BY created_at DESC LIMIT 30",
                (row["id"],),
            ).fetchall()[::-1]
        ]
    return view


def process_is_alive(process_id: int | None) -> bool:
    if not process_id or process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def queue_seconds_since(timestamp: str | None) -> float:
    if not timestamp:
        return float("inf")
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds())
    except (TypeError, ValueError):
        return float("inf")


def recover_queue_runtime(connection: sqlite3.Connection) -> None:
    runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
    if runtime is None or runtime["state"] not in {"starting", "running"}:
        return
    startup_stale = runtime["state"] == "starting" and queue_seconds_since(runtime["updated_at"]) > QUEUE_HEARTBEAT_TIMEOUT_SECONDS
    heartbeat_stale = queue_seconds_since(runtime["heartbeat_at"]) > QUEUE_HEARTBEAT_TIMEOUT_SECONDS
    dead_worker = runtime["state"] == "running" and not process_is_alive(runtime["pid"])
    if not (startup_stale or heartbeat_stale or dead_worker):
        return
    connection.execute("UPDATE queue_runtime SET state = 'stopping', updated_at = ? WHERE id = 1", (utc_now(),))
    running = connection.execute(
        "SELECT id, job_id, stage, pipeline FROM queue_tasks WHERE state IN ('starting', 'downloading', 'rendering', 'cancel_requested')"
    ).fetchall()
    for task in running:
        connection.execute(
            "UPDATE queue_tasks SET state = 'interrupted', cancel_requested = 1, error = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            ("The app stopped sending queue heartbeats. Retry this job to continue from saved files.", utc_now(), utc_now(), task["id"]),
        )
        if task["pipeline"] == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'interrupted', thumbnail_error = 'The app closed during thumbnail processing.', thumbnail_progress = NULL WHERE id = ?", (task["job_id"],))
        elif task["stage"] == "rendering":
            connection.execute("UPDATE video_jobs SET render_status = 'interrupted', render_error = 'The app closed during rendering.', render_progress = NULL WHERE id = ?", (task["job_id"],))
        elif task["stage"] in {"downloading", "captions", "thumbnail_ocr"}:
            connection.execute("UPDATE video_jobs SET download_status = 'interrupted', download_error = 'The app closed during source download.', download_progress = NULL WHERE id = ?", (task["job_id"],))
        queue_log(connection, task["id"], "Queue work was interrupted because the app heartbeat expired.", "warning")
    if dead_worker or startup_stale:
        connection.execute("UPDATE queue_runtime SET state = 'stopped', pid = NULL, token = NULL, updated_at = ? WHERE id = 1", (utc_now(),))
    connection.commit()


def queue_heartbeat(connection: sqlite3.Connection) -> dict[str, Any]:
    recover_queue_runtime(connection)
    runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
    if runtime["state"] != "stopping":
        connection.execute("UPDATE queue_runtime SET heartbeat_at = ?, updated_at = ? WHERE id = 1", (utc_now(), utc_now()))
        connection.commit()
    runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
    return {"state": runtime["state"], "worker_running": process_is_alive(runtime["pid"]), "heartbeat_at": runtime["heartbeat_at"]}


def queue_abort_reason(connection: sqlite3.Connection, task_id: str) -> str | None:
    task = connection.execute("SELECT cancel_requested FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        return "interrupted"
    if task["cancel_requested"]:
        runtime = connection.execute("SELECT state FROM queue_runtime WHERE id = 1").fetchone()
        return "interrupted" if runtime and runtime["state"] == "stopping" else "cancelled"
    recover_queue_runtime(connection)
    runtime = connection.execute("SELECT state, heartbeat_at FROM queue_runtime WHERE id = 1").fetchone()
    if runtime is None or runtime["state"] != "running":
        return "interrupted"
    if queue_seconds_since(runtime["heartbeat_at"]) > QUEUE_HEARTBEAT_TIMEOUT_SECONDS:
        recover_queue_runtime(connection)
        return "interrupted"
    return None


def queue_set_stage(connection: sqlite3.Connection, task_id: str, stage: str, progress: float) -> None:
    current = connection.execute("SELECT stage, state, job_id, pipeline FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    if current is None:
        return
    progress_value = min(1.0, max(0.0, progress))
    active_state = "rendering" if stage in {"rendering", "thumbnail_rendering"} else ("downloading" if stage.startswith("thumbnail_") else stage if stage in {"downloading", "rendering"} else current["state"])
    connection.execute(
        "UPDATE queue_tasks SET stage = ?, state = ?, progress = ?, updated_at = ? WHERE id = ?",
        (stage, active_state, progress_value, utc_now(), task_id),
    )
    if current["pipeline"] == "thumbnail":
        connection.execute("UPDATE video_jobs SET thumbnail_progress = ? WHERE id = ?", (progress_value, current["job_id"]))
    if stage != current["stage"]:
        queue_log(connection, task_id, f"Started {stage.replace('_', ' ')}.")
    else:
        connection.commit()


def queue_update_progress(connection: sqlite3.Connection, task_id: str, stage: str, progress: float) -> None:
    progress_value = min(1.0, max(0.0, progress))
    task = connection.execute("SELECT job_id, pipeline FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    active_state = "rendering" if stage in {"rendering", "thumbnail_rendering"} else "downloading"
    connection.execute("UPDATE queue_tasks SET state = ?, stage = ?, progress = ?, updated_at = ? WHERE id = ?", (active_state, stage, progress_value, utc_now(), task_id))
    if stage == "downloading":
        connection.execute("UPDATE video_jobs SET download_progress = ? WHERE id = (SELECT job_id FROM queue_tasks WHERE id = ?)", (progress_value, task_id))
    elif task and task["pipeline"] == "thumbnail":
        connection.execute("UPDATE video_jobs SET thumbnail_progress = ? WHERE id = ?", (progress_value, task["job_id"]))
    connection.commit()


def queue_status(connection: sqlite3.Connection, batch_id: str | None = None, database_path: str | None = None) -> dict[str, Any]:
    queue_heartbeat(connection)
    runtime_before_launch = connection.execute("SELECT state FROM queue_runtime WHERE id = 1").fetchone()
    queued = connection.execute("SELECT 1 FROM queue_tasks WHERE state = 'queued' LIMIT 1").fetchone()
    if database_path and queued and runtime_before_launch["state"] not in {"starting", "running"}:
        launch_queue_worker(connection, database_path)
    if batch_id:
        if connection.execute("SELECT 1 FROM batches WHERE id = ?", (batch_id,)).fetchone() is None:
            raise ValueError("Batch was not found.")
        rows = connection.execute("SELECT * FROM queue_tasks WHERE batch_id = ? ORDER BY created_at, id", (batch_id,)).fetchall()
    else:
        rows = connection.execute("SELECT * FROM queue_tasks ORDER BY created_at DESC, id DESC LIMIT 1000").fetchall()
    tasks = [queue_task_view(connection, row) for row in rows]
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task["state"]] = counts.get(task["state"], 0) + 1
    runtime = connection.execute("SELECT state, pid, heartbeat_at, max_concurrency FROM queue_runtime WHERE id = 1").fetchone()
    return {
        "tasks": tasks,
        "counts": counts,
        "runtime": {"state": runtime["state"], "worker_running": process_is_alive(runtime["pid"]), "heartbeat_at": runtime["heartbeat_at"], "max_concurrency": runtime["max_concurrency"]},
    }


def latest_queue_task(connection: sqlite3.Connection, job_id: str, pipeline: str = "video") -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM queue_tasks WHERE job_id = ? AND pipeline = ? ORDER BY created_at DESC, id DESC LIMIT 1", (job_id, pipeline)).fetchone()


def launch_queue_worker(connection: sqlite3.Connection, database_path: str) -> bool:
    connection.execute("BEGIN IMMEDIATE")
    runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
    if runtime["state"] in {"starting", "running", "stopping"} and process_is_alive(runtime["pid"]):
        connection.commit()
        return False
    if runtime["state"] == "starting" and queue_seconds_since(runtime["updated_at"]) <= QUEUE_HEARTBEAT_TIMEOUT_SECONDS:
        connection.commit()
        return False
    dead_tasks = connection.execute("SELECT id, job_id, stage, pipeline FROM queue_tasks WHERE state IN ('starting', 'downloading', 'rendering', 'cancel_requested')").fetchall()
    for task in dead_tasks:
        connection.execute("UPDATE queue_tasks SET state = 'interrupted', error = ?, completed_at = ?, updated_at = ? WHERE id = ?", ("The queue worker stopped unexpectedly. Retry from saved files.", utc_now(), utc_now(), task["id"]))
        if task["pipeline"] == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'interrupted', thumbnail_progress = NULL WHERE id = ?", (task["job_id"],))
        elif task["stage"] == "rendering":
            connection.execute("UPDATE video_jobs SET render_status = 'interrupted', render_progress = NULL WHERE id = ?", (task["job_id"],))
        else:
            connection.execute("UPDATE video_jobs SET download_status = 'interrupted', download_progress = NULL WHERE id = ?", (task["job_id"],))
        queue_log(connection, task["id"], "Queue worker stopped unexpectedly.", "warning")
    queued = connection.execute("SELECT 1 FROM queue_tasks WHERE state = 'queued' LIMIT 1").fetchone()
    if not queued:
        connection.execute("UPDATE queue_runtime SET state = 'stopped', pid = NULL, token = NULL, updated_at = ? WHERE id = 1", (utc_now(),))
        connection.commit()
        return False
    token = str(uuid.uuid4())
    connection.execute("UPDATE queue_runtime SET state = 'starting', pid = NULL, token = ?, heartbeat_at = ?, updated_at = ? WHERE id = 1", (token, utc_now(), utc_now()))
    connection.commit()
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--db-path", str(Path(database_path).expanduser().resolve()), "--queue-worker-token", token]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), "--db-path", str(Path(database_path).expanduser().resolve()), "--queue-worker-token", token]
    worker_environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        # The queue child outlives this request process, so it must unpack its own one-folder runtime.
        worker_environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"), env=worker_environment,
        )
    except OSError as error:
        connection.execute("UPDATE queue_runtime SET state = 'stopped', pid = NULL, token = NULL, updated_at = ? WHERE id = 1", (utc_now(),))
        connection.commit()
        raise ValueError(f"The background queue worker could not start: {error}") from error
    connection.execute("UPDATE queue_runtime SET pid = ?, updated_at = ? WHERE id = 1 AND token = ?", (process.pid, utc_now(), token))
    connection.commit()
    return True


def start_queue_tasks(connection: sqlite3.Connection, database_path: str, params: dict[str, Any]) -> dict[str, Any]:
    pipeline = str(params.get("pipeline", "video"))
    if pipeline not in {"video", "thumbnail", "download_only"}:
        raise ValueError("Queue pipeline must be 'video', 'thumbnail', or 'download_only'.")
    batch_id = str(params.get("batch_id", ""))
    batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise ValueError("Batch was not found.")
    if batch["state"] != "confirmed":
        raise ValueError("Confirm the Batch before adding jobs to the queue.")
    if (batch["workflow_mode"] == "download_only") != (pipeline == "download_only"):
        raise ValueError("Choose the queue action that matches this Batch's workflow mode.")
    job_ids = params.get("job_ids")
    if not isinstance(job_ids, list) or not job_ids:
        raise ValueError("Select at least one job to add to the queue.")
    if len(job_ids) > 500:
        raise ValueError("A single queue request can include at most 500 jobs.")
    output_root = str(params.get("output_root", "")).strip()
    if not output_root:
        raise ValueError("Choose an output folder before starting queued jobs.")
    normalized_ids = list(dict.fromkeys(str(job_id) for job_id in job_ids))
    for job_id in normalized_ids:
        job = connection.execute("SELECT * FROM video_jobs WHERE id = ? AND batch_id = ?", (job_id, batch_id)).fetchone()
        if job is None:
            raise ValueError("One or more selected jobs do not belong to this Batch.")
        if job["metadata_status"] != "ready" or not job["channel_id"] or job["duplicate_of_job_id"]:
            raise ValueError(f"Resolve the URL, Channel, or duplicate issue on row {job['row_number']} before queueing.")
        if pipeline == "video" and job["download_status"] == "complete" and job["render_status"] == "complete":
            continue
        if pipeline == "download_only":
            source_video = Path(job["source_video_path"] or "")
            source_thumbnail = Path(job["source_thumbnail_path"] or "")
            latest_download = latest_queue_task(connection, job_id, pipeline)
            subtitle_ready = job["subtitle_decision"] == "skip"
            if job["subtitle_decision"] == "use_file":
                subtitle_ready = bool(job["supplied_subtitle_path"] and Path(job["supplied_subtitle_path"]).is_file())
            elif job["subtitle_decision"] == "youtube":
                artifact = connection.execute(
                    "SELECT path FROM job_artifacts WHERE job_id = ? AND kind = 'subtitle_youtube' ORDER BY created_at DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
                subtitle_ready = bool(artifact and Path(artifact["path"]).is_file())
            if latest_download and latest_download["state"] == "complete" and source_video.is_file() and source_thumbnail.is_file() and subtitle_ready:
                continue
        if pipeline == "thumbnail":
            if effective_thumbnail_mode(connection, job) == "skip":
                continue
            if effective_thumbnail_mode(connection, job) == "auto" and not job["thumbnail_preset_id"]:
                raise ValueError(f"Assign a thumbnail style before queueing row {job['row_number']}.")
            thumbnail_path = job["thumbnail_output_path"]
            if job["thumbnail_ocr_status"] == "complete" and thumbnail_path and Path(thumbnail_path).is_file():
                continue
        active_states = {"queued", "starting", "downloading", "rendering", "cancel_requested", "waiting_for_captions", "waiting_for_thumbnail_review"}
        for other_pipeline in {"video", "thumbnail", "download_only"} - {pipeline}:
            opposite = latest_queue_task(connection, job_id, other_pipeline)
            if opposite and opposite["state"] in active_states:
                raise ValueError(f"Row {job['row_number']} already has {other_pipeline} work in the queue. Let it finish or cancel it before starting this pipeline.")
        latest = latest_queue_task(connection, job_id, pipeline)
        waiting_states = {"waiting_for_captions"} if pipeline in {"video", "download_only"} else {"waiting_for_thumbnail_review"}
        if latest and latest["state"] in {"queued", "starting", "downloading", "rendering", "cancel_requested", *waiting_states}:
            continue
        task_id = str(uuid.uuid4())
        now = utc_now()
        connection.execute(
            "INSERT INTO queue_tasks(id, batch_id, job_id, pipeline, state, stage, progress, output_root, include_video_source, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', 'queued', 0, ?, ?, ?, ?)",
            (task_id, batch_id, job_id, pipeline, output_root, int(pipeline == "download_only" or bool(params.get("include_video_source", job["include_video_source"]))), now, now),
        )
        if pipeline == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'queued', thumbnail_progress = 0, thumbnail_error = NULL WHERE id = ?", (job_id,))
        queue_log(connection, task_id, "Job added to the local processing queue.")
    connection.commit()
    launch_queue_worker(connection, database_path)
    return queue_status(connection, batch_id, database_path)


def retry_queue_task(connection: sqlite3.Connection, database_path: str, task_id: str) -> dict[str, Any]:
    task = connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise ValueError("Queue task was not found.")
    resumable_states = {"failed", "cancelled", "interrupted", "waiting_for_captions", "waiting_for_thumbnail_review"}
    if task["state"] not in resumable_states:
        raise ValueError("Only failed, cancelled, interrupted, or review-waiting jobs can be resumed.")
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    if not job or (task["pipeline"] in {"video", "download_only"} and (job["download_status"] == "needs_subtitle_decision" or job["subtitle_decision"] == "needs_decision")):
        raise ValueError("Choose a matching subtitle file or Skip captions before resuming this queued job.")
    active_states = {"queued", "starting", "downloading", "rendering", "cancel_requested", "waiting_for_captions", "waiting_for_thumbnail_review"}
    for other_pipeline in {"video", "thumbnail", "download_only"} - {task["pipeline"]}:
        opposite = latest_queue_task(connection, task["job_id"], other_pipeline)
        if opposite and opposite["state"] in active_states:
            raise ValueError(f"This job already has {other_pipeline} work in the queue.")
    connection.execute(
        "UPDATE queue_tasks SET state = 'queued', stage = 'queued', progress = 0, error = NULL, cancel_requested = 0, started_at = NULL, completed_at = NULL, updated_at = ? WHERE id = ?",
        (utc_now(), task_id),
    )
    if task["pipeline"] == "thumbnail" and job["thumbnail_ocr_status"] not in {"confirmed", "awaiting_confirmation", "needs_review"}:
        connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'queued', thumbnail_progress = 0, thumbnail_error = NULL WHERE id = ?", (task["job_id"],))
    queue_log(connection, task_id, "Job was queued for retry. Existing source artifacts will be reused when valid.")
    connection.commit()
    database_path = str(connection.execute("PRAGMA database_list").fetchone()[2])
    launch_queue_worker(connection, database_path)
    return queue_task_view(connection, connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone())


def cancel_queue_task(connection: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    task = connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    if task is None:
        raise ValueError("Queue task was not found.")
    if task["state"] in {"complete", "failed", "cancelled", "interrupted"}:
        raise ValueError("This queue task is already finished.")
    if task["state"] in {"queued", "waiting_for_captions", "waiting_for_thumbnail_review"}:
        connection.execute("UPDATE queue_tasks SET state = 'cancelled', cancel_requested = 1, completed_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), task_id))
        if task["pipeline"] == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'cancelled', thumbnail_progress = NULL WHERE id = ?", (task["job_id"],))
        elif task["pipeline"] == "download_only":
            connection.execute("UPDATE video_jobs SET download_status = 'cancelled', download_progress = NULL WHERE id = ?", (task["job_id"],))
        queue_log(connection, task_id, "Job was removed from the queue.", "warning")
    else:
        connection.execute("UPDATE queue_tasks SET state = 'cancel_requested', cancel_requested = 1, updated_at = ? WHERE id = ?", (utc_now(), task_id))
        queue_log(connection, task_id, "Cancellation requested. The active media process will stop safely.", "warning")
    connection.commit()
    return queue_task_view(connection, connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone())


def configure_queue(connection: sqlite3.Connection, params: dict[str, Any]) -> dict[str, int]:
    try:
        concurrency = int(params.get("max_concurrency", 1))
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("Queue concurrency must be an integer from 1 to 4.") from error
    if not 1 <= concurrency <= 4:
        raise ValueError("Queue concurrency must be between 1 and 4.")
    connection.execute("UPDATE queue_runtime SET max_concurrency = ?, updated_at = ? WHERE id = 1", (concurrency, utc_now()))
    connection.commit()
    return {"max_concurrency": concurrency}


def finish_queue_task(connection: sqlite3.Connection, task_id: str, state: str, error: str | None = None) -> None:
    connection.execute(
        "UPDATE queue_tasks SET state = ?, error = ?, completed_at = ?, updated_at = ?, progress = CASE WHEN ? = 'complete' THEN 1 ELSE progress END WHERE id = ?",
        (state, error, utc_now(), utc_now(), state, task_id),
    )
    if error:
        queue_log(connection, task_id, error, "error")
    else:
        queue_log(connection, task_id, {"complete": "Job completed successfully.", "cancelled": "Job was cancelled.", "interrupted": "Job was interrupted and can be retried."}.get(state, state.replace("_", " ").capitalize()), "warning" if state != "complete" else "info")
    connection.commit()


def process_thumbnail_queue_task(connection: sqlite3.Connection, task: sqlite3.Row) -> None:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    if not job:
        raise ValueError("Video job was not found.")
    mode = effective_thumbnail_mode(connection, job)
    if mode == "skip":
        raise ValueError("Thumbnail handling is set to Skip for this job.")
    source_path = job["source_thumbnail_path"]
    if not source_path or not Path(source_path).is_file():
        queue_log(connection, task["id"], "Downloading the source thumbnail image.")
        downloaded = download_source_thumbnail(connection, task["job_id"], task["output_root"], task["id"])
        job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
        if not job["source_thumbnail_path"] or not Path(job["source_thumbnail_path"]).is_file():
            raise ValueError(downloaded.get("thumbnail_error") or "The source thumbnail image could not be saved.")
    if mode == "manual":
        connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'manual', thumbnail_progress = 1, thumbnail_error = NULL WHERE id = ?", (task["job_id"],))
        connection.commit()
        finish_queue_task(connection, task["id"], "complete")
        return
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    if job["thumbnail_ocr_status"] not in {"awaiting_confirmation", "needs_review", "confirmed", "complete"}:
        queue_set_stage(connection, task["id"], "thumbnail_ocr", 0.68)
        text, confidence, error = recognize_thumbnail_text(job["source_thumbnail_path"], effective_thumbnail_languages(connection, job))
        ocr_status = "awaiting_confirmation" if text and confidence is not None and confidence >= 0.55 and not error else "needs_review"
        connection.execute("UPDATE video_jobs SET thumbnail_ocr_text = ?, thumbnail_ocr_confidence = ?, thumbnail_text = ?, thumbnail_ocr_status = ?, thumbnail_error = ?, thumbnail_progress = 0.82 WHERE id = ?", (text, confidence, text, ocr_status, error, task["job_id"]))
        connection.commit()
        job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    if job["thumbnail_ocr_status"] != "confirmed":
        connection.execute("UPDATE queue_tasks SET state = 'waiting_for_thumbnail_review', stage = 'waiting_for_thumbnail_review', progress = 0.82, updated_at = ? WHERE id = ?", (utc_now(), task["id"]))
        queue_log(connection, task["id"], "OCR is ready. Review or edit the text, then resume to export the PNG.", "warning")
        connection.commit()
        return
    abort_state = queue_abort_reason(connection, task["id"])
    if abort_state:
        raise QueueCancelled(abort_state)
    queue_set_stage(connection, task["id"], "thumbnail_rendering", 0.9)
    connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'generating', thumbnail_progress = 0.9 WHERE id = ?", (task["job_id"],))
    connection.commit()
    rendered = render_job_thumbnail(connection, task["job_id"])
    if rendered["thumbnail_ocr_status"] != "complete":
        raise ValueError(rendered["thumbnail_error"] or "Thumbnail export failed.")
    connection.execute("UPDATE video_jobs SET thumbnail_progress = 1 WHERE id = ?", (task["job_id"],))
    connection.commit()
    finish_queue_task(connection, task["id"], "complete")


def prepare_download_only_package(connection: sqlite3.Connection, task: sqlite3.Row) -> None:
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    if job is None:
        raise ValueError("Video job was not found while preparing its download package.")
    source_video = Path(job["source_video_path"] or "")
    source_thumbnail = Path(job["source_thumbnail_path"] or "")
    if not source_video.is_file():
        raise ValueError("The full YouTube source video is missing from this download package.")
    if not source_thumbnail.is_file():
        raise ValueError("The original YouTube thumbnail is missing from this download package.")

    subtitle_path: Path | None = None
    if job["subtitle_decision"] == "youtube":
        artifact = connection.execute(
            "SELECT path FROM job_artifacts WHERE job_id = ? AND kind = 'subtitle_youtube' ORDER BY created_at DESC LIMIT 1",
            (job["id"],),
        ).fetchone()
        if artifact and Path(artifact["path"]).is_file():
            subtitle_path = Path(artifact["path"])
        else:
            raise ValueError("The selected YouTube subtitle file is missing from this download package.")
    elif job["subtitle_decision"] == "use_file" and job["supplied_subtitle_path"]:
        supplied_path = Path(job["supplied_subtitle_path"])
        if not supplied_path.is_file():
            raise ValueError("The supplied subtitle file is no longer available. Attach it again or Skip captions.")
        directory = job_download_directory(connection, job, task["output_root"])
        subtitle_path = directory / f"subtitle.supplied{supplied_path.suffix.lower()}"
        if supplied_path.resolve() != subtitle_path.resolve():
            shutil.copy2(supplied_path, subtitle_path)
        add_job_artifact(connection, job["id"], "subtitle_supplied_copy", str(subtitle_path))
    elif job["subtitle_decision"] != "skip":
        raise ValueError("Choose a preferred subtitle file or Skip captions before completing this package.")

    if subtitle_path:
        normalized = normalize_subtitle_to_srt(str(subtitle_path), subtitle_path.parent / "captions.srt")
        add_job_artifact(connection, job["id"], "subtitle_srt", str(normalized))
    connection.commit()


def process_queue_task(connection: sqlite3.Connection, task_id: str) -> None:
    task = connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return
    job = connection.execute("SELECT * FROM video_jobs WHERE id = ?", (task["job_id"],)).fetchone()
    try:
        abort_state = queue_abort_reason(connection, task_id)
        if abort_state:
            raise QueueCancelled(abort_state)
        if task["pipeline"] == "thumbnail":
            process_thumbnail_queue_task(connection, task)
            return
        download_only = task["pipeline"] == "download_only"
        if job["download_status"] == "needs_subtitle_decision" or job["subtitle_decision"] == "needs_decision":
            connection.execute("UPDATE queue_tasks SET state = 'waiting_for_captions', stage = 'waiting_for_captions', updated_at = ? WHERE id = ?", (utc_now(), task_id))
            queue_log(connection, task_id, "Source media is saved. Waiting for an SRT/VTT choice or Skip captions.", "warning")
            return
        source_path = job["source_video_path"] if download_only else job["source_audio_path"] or job["source_video_path"]
        source_available = bool(source_path and Path(source_path).is_file())
        thumbnail_available = bool(job["source_thumbnail_path"] and Path(job["source_thumbnail_path"]).is_file())
        subtitle_available = job["subtitle_decision"] in {"skip", "use_file"}
        if job["subtitle_decision"] == "use_file":
            subtitle_available = bool(job["supplied_subtitle_path"] and Path(job["supplied_subtitle_path"]).is_file())
        elif job["subtitle_decision"] == "youtube":
            subtitle_artifact = connection.execute(
                "SELECT path FROM job_artifacts WHERE job_id = ? AND kind = 'subtitle_youtube' ORDER BY created_at DESC LIMIT 1",
                (job["id"],),
            ).fetchone()
            subtitle_available = bool(subtitle_artifact and Path(subtitle_artifact["path"]).is_file())
        if (not download_only and (job["download_status"] != "complete" or not source_available)) or (download_only and (not source_available or not thumbnail_available or not subtitle_available)):
            queue_set_stage(connection, task_id, "downloading", 0.02)
            queue_log(connection, task_id, "Downloading the full source video, original thumbnail, and resolving subtitles." if download_only else "Downloading source audio and resolving subtitles.")
            downloaded = download_job_sources(
                connection,
                task["batch_id"],
                task["job_id"],
                task["output_root"],
                bool(task["include_video_source"]) or download_only,
                task_id,
                download_only=download_only,
            )
            if downloaded["download_status"] == "needs_subtitle_decision":
                connection.execute("UPDATE queue_tasks SET state = 'waiting_for_captions', stage = 'waiting_for_captions', progress = 0.52, updated_at = ? WHERE id = ?", (utc_now(), task_id))
                queue_log(connection, task_id, "Source media is saved. Waiting for an SRT/VTT choice or Skip captions.", "warning")
                return
            if downloaded["download_status"] != "complete":
                raise ValueError(downloaded["download_error"] or "Source media download failed.")
        abort_state = queue_abort_reason(connection, task_id)
        if abort_state:
            raise QueueCancelled(abort_state)
        if download_only:
            queue_set_stage(connection, task_id, "packaging", 0.82)
            prepare_download_only_package(connection, task)
            connection.execute("UPDATE video_jobs SET download_status = 'complete', download_progress = 1, download_error = NULL WHERE id = ?", (task["job_id"],))
            connection.commit()
            queue_log(connection, task_id, "Source video, original thumbnail, and available subtitle files are ready in the job folder.")
            finish_queue_task(connection, task_id, "complete")
            return
        queue_log(connection, task_id, "Source files are ready; rendering the assigned Background.")
        rendered = render_job_video(connection, task["batch_id"], task["job_id"], task_id)
        abort_state = queue_abort_reason(connection, task_id)
        if abort_state:
            raise QueueCancelled(abort_state)
        if rendered["render_status"] != "complete":
            raise ValueError(rendered["render_error"] or "Video rendering failed.")
        finish_queue_task(connection, task_id, "complete")
    except QueueCancelled as error:
        current = connection.execute("SELECT stage, pipeline FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
        if current and current["pipeline"] == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = ?, thumbnail_progress = NULL, thumbnail_error = ? WHERE id = ?", ("interrupted" if error.state == "interrupted" else "cancelled", str(error), task["job_id"]))
        elif current and current["stage"] in {"downloading", "captions", "thumbnail_ocr"}:
            connection.execute("UPDATE video_jobs SET download_status = ?, download_progress = NULL, download_error = ? WHERE id = ?", ("interrupted" if error.state == "interrupted" else "cancelled", str(error), task["job_id"]))
        finish_queue_task(connection, task_id, error.state, str(error))
    except (OSError, sqlite3.Error, ValueError) as error:
        current = connection.execute("SELECT pipeline FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
        if current and current["pipeline"] == "thumbnail":
            connection.execute("UPDATE video_jobs SET thumbnail_ocr_status = 'error', thumbnail_error = ?, thumbnail_progress = NULL WHERE id = ?", (str(error)[-1200:], task["job_id"]))
        elif current and current["pipeline"] == "download_only":
            connection.execute("UPDATE video_jobs SET download_status = 'error', download_progress = NULL, download_error = ? WHERE id = ?", (str(error)[-1200:], task["job_id"]))
        finish_queue_task(connection, task_id, "failed", str(error)[-1600:])


def process_queue_task_in_worker(database_path: str, task_id: str) -> None:
    with open_database(database_path) as connection:
        try:
            process_queue_task(connection, task_id)
        except Exception as error:
            connection.execute("UPDATE queue_tasks SET state = 'failed', error = ?, completed_at = ?, updated_at = ? WHERE id = ?", (str(error)[-1600:], utc_now(), utc_now(), task_id))
            queue_log(connection, task_id, str(error)[-1600:], "error")


def run_queue_worker(database_path: str, token: str) -> int:
    with open_database(database_path) as connection:
        runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
        if not runtime or runtime["token"] != token:
            return 2
        connection.execute("UPDATE queue_runtime SET state = 'running', pid = ?, updated_at = ? WHERE id = 1", (os.getpid(), utc_now()))
        connection.commit()
        active_tasks = set()
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="media-job") as executor:
            while True:
                runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
                if not runtime or runtime["token"] != token or runtime["state"] != "running":
                    break
                concurrency = max(1, min(4, int(runtime["max_concurrency"])))
                while len(active_tasks) < concurrency:
                    task = connection.execute("SELECT id FROM queue_tasks WHERE state = 'queued' ORDER BY created_at, id LIMIT 1").fetchone()
                    if not task:
                        break
                    connection.execute("UPDATE queue_tasks SET state = 'starting', started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?", (utc_now(), utc_now(), task["id"]))
                    connection.commit()
                    queue_log(connection, task["id"], "Queue worker claimed this job.")
                    active_tasks.add(executor.submit(process_queue_task_in_worker, database_path, task["id"]))
                if active_tasks:
                    finished, active_tasks = wait(active_tasks, timeout=0.15, return_when=FIRST_COMPLETED)
                    for future in finished:
                        future.result()
                    continue
                queued = connection.execute("SELECT 1 FROM queue_tasks WHERE state = 'queued' LIMIT 1").fetchone()
                if not queued:
                    break
        runtime = connection.execute("SELECT * FROM queue_runtime WHERE id = 1").fetchone()
        if runtime and runtime["token"] == token:
            connection.execute("UPDATE queue_runtime SET state = 'stopped', pid = NULL, token = NULL, updated_at = ? WHERE id = 1", (utc_now(),))
            connection.commit()
    return 0


def dispatch(connection: sqlite3.Connection, method: str, params: dict[str, Any], database_path: str | None = None) -> Any:
    if method == "health":
        return {"status": "ready", "schema_version": SCHEMA_VERSION}
    if method == "system.toolchain.check":
        path = database_path or str(connection.execute("PRAGMA database_list").fetchone()[2])
        return check_local_toolchain(path)
    if method == "system.ytdlp.sync":
        path = database_path or str(connection.execute("PRAGMA database_list").fetchone()[2])
        return sync_dynamic_toolchain(path)
    if method == "settings.youtube_cookies.get":
        return youtube_cookie_settings(connection)
    if method == "settings.youtube_cookies.set":
        return set_youtube_cookie_file(connection, params.get("path"))
    if method == "queue.heartbeat":
        return queue_heartbeat(connection)
    if method == "queue.status":
        raw_batch_id = params.get("batch_id")
        path = database_path or str(connection.execute("PRAGMA database_list").fetchone()[2])
        return queue_status(connection, str(raw_batch_id) if raw_batch_id else None, path)
    if method == "queue.start":
        path = database_path or str(connection.execute("PRAGMA database_list").fetchone()[2])
        return start_queue_tasks(connection, path, params)
    if method == "queue.configure":
        return configure_queue(connection, params)
    if method == "queue.retry":
        task_id = str(params.get("task_id", ""))
        task = connection.execute("SELECT * FROM queue_tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise ValueError("Queue task was not found.")
        return retry_queue_task(connection, database_path or str(connection.execute("PRAGMA database_list").fetchone()[2]), task_id)
    if method == "queue.cancel":
        return cancel_queue_task(connection, str(params.get("task_id", "")))
    if method == "channels.list":
        return list_channels(connection)
    if method == "channels.create":
        return create_channel(connection, str(params.get("name", "")))
    if method == "channels.update":
        channel_id = str(params.get("channel_id", ""))
        ensure_channel(connection, channel_id)
        name = str(params.get("name", "")).strip()
        if not name:
            raise ValueError("Channel name is required.")
        slug = unique_slug(connection, name, excluding_channel_id=channel_id)
        connection.execute(
            "UPDATE channels SET name = ?, slug = ?, updated_at = ? WHERE id = ?",
            (name, slug, utc_now(), channel_id),
        )
        connection.commit()
        return channel_view(connection, ensure_channel(connection, channel_id))
    if method == "channels.set_subtitle_languages":
        return set_channel_subtitle_languages(
            connection,
            str(params.get("channel_id", "")),
            params.get("languages", []),
        )
    if method == "channels.set_thumbnail_settings":
        return set_channel_thumbnail_settings(connection, str(params.get("channel_id", "")), str(params.get("mode", "auto")), params.get("languages", []))
    if method == "channels.set_default_thumbnail_preset":
        return set_channel_default_thumbnail_preset(connection, str(params.get("channel_id", "")), str(params.get("preset_id", "")))
    if method == "channels.add_thumbnail_preset":
        return link_thumbnail_preset_to_channel(connection, str(params.get("channel_id", "")), str(params.get("preset_id", "")))
    if method == "thumbnail.ocr.languages":
        return list_ocr_languages()
    if method == "thumbnail.presets.list":
        return list_thumbnail_presets(connection, params)
    if method == "thumbnail.presets.create":
        owner_channel_id = str(params["channel_id"]) if params.get("channel_id") else None
        result = create_thumbnail_preset(connection, owner_channel_id, str(params.get("name", "")), params.get("style", DEFAULT_THUMBNAIL_STYLE))
        if owner_channel_id:
            link_thumbnail_preset_to_channel(connection, owner_channel_id, result["id"])
        connection.commit()
        return result
    if method == "thumbnail.presets.update":
        result = update_thumbnail_preset(connection, str(params.get("preset_id", "")), str(params.get("name", "")), params.get("style", {}))
        connection.commit()
        return result
    if method == "thumbnail.presets.assign_channels":
        return assign_thumbnail_presets_to_channels(connection, str(params.get("preset_id", "")), params.get("channel_ids", []))
    if method == "thumbnail.presets.channels":
        return thumbnail_preset_channels(connection, str(params.get("preset_id", "")))
    if method == "channels.set_default_subtitle_preset":
        return set_channel_default_subtitle_preset(
            connection,
            str(params.get("channel_id", "")),
            str(params.get("preset_id", "")),
        )
    if method == "subtitles.presets.list":
        channel_id = params.get("channel_id")
        return list_subtitle_presets(connection, str(channel_id) if channel_id else None)
    if method == "subtitles.presets.create":
        result = create_subtitle_preset(
            connection,
            str(params["channel_id"]) if params.get("channel_id") else None,
            str(params.get("name", "")),
            params.get("style", DEFAULT_SUBTITLE_STYLE),
        )
        connection.commit()
        return result
    if method == "subtitles.presets.update":
        result = update_subtitle_preset(
            connection,
            str(params.get("preset_id", "")),
            str(params.get("name", "")),
            params.get("style", {}),
        )
        connection.commit()
        return result
    if method == "subtitles.presets.duplicate":
        original = get_subtitle_preset(connection, str(params.get("preset_id", "")))
        result = create_subtitle_preset(
            connection,
            original["channel_id"],
            str(params.get("name", f"{original['name']} copy")),
            json.loads(original["style_json"]),
        )
        connection.commit()
        return result
    if method == "subtitles.font.inspect":
        return inspect_font_family(str(params.get("font_family", "")))
    if method == "channels.set_active":
        channel_id = str(params.get("channel_id", ""))
        ensure_channel(connection, channel_id)
        active = bool(params.get("active"))
        connection.execute(
            "UPDATE channels SET active = ?, updated_at = ? WHERE id = ?",
            (1 if active else 0, utc_now(), channel_id),
        )
        connection.commit()
        return channel_view(connection, ensure_channel(connection, channel_id))
    if method == "channels.duplicate":
        source_id = str(params.get("channel_id", ""))
        source = ensure_channel(connection, source_id)
        name = str(params.get("name", "")).strip()
        if not name:
            raise ValueError("A name is required for the duplicate Channel.")
        now = utc_now()
        new_id = str(uuid.uuid4())
        slug = unique_slug(connection, name)
        connection.execute(
            """
            INSERT INTO channels(id, name, slug, active, subtitle_languages_json, thumbnail_mode, ocr_languages_json, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (new_id, name, slug, source["subtitle_languages_json"], source["thumbnail_mode"], source["ocr_languages_json"], now, now),
        )
        source_preset = connection.execute("SELECT style_json FROM subtitle_presets WHERE id = ?", (source["default_subtitle_preset_id"],)).fetchone() if source["default_subtitle_preset_id"] else None
        duplicated_preset = create_subtitle_preset(
            connection, new_id, f"{name} default",
            json.loads(source_preset["style_json"]) if source_preset else DEFAULT_SUBTITLE_STYLE,
        )
        connection.execute("UPDATE channels SET default_subtitle_preset_id = ? WHERE id = ?", (duplicated_preset["id"], new_id))
        source_thumbnail_default = connection.execute("SELECT * FROM thumbnail_presets WHERE id = ?", (source["default_thumbnail_preset_id"],)).fetchone() if source["default_thumbnail_preset_id"] else None
        duplicated_thumbnail_default = create_thumbnail_preset(
            connection, new_id, f"{name} default",
            {key: source_thumbnail_default[key] for key in DEFAULT_THUMBNAIL_STYLE} if source_thumbnail_default else DEFAULT_THUMBNAIL_STYLE,
        )
        connection.execute("UPDATE channels SET default_thumbnail_preset_id = ? WHERE id = ?", (duplicated_thumbnail_default["id"], new_id))
        connection.execute("INSERT INTO channel_thumbnail_presets(channel_id, preset_id, position) VALUES (?, ?, 0)", (new_id, duplicated_thumbnail_default["id"]))
        connection.execute(
            """
            INSERT INTO channel_backgrounds(channel_id, asset_id, position)
            SELECT ?, asset_id, position FROM channel_backgrounds
            WHERE channel_id = ?
            """,
            (new_id, source_id),
        )
        connection.commit()
        return channel_view(connection, ensure_channel(connection, new_id))
    if method == "backgrounds.add_to_channel":
        return add_background_to_channel(
            connection,
            str(params.get("channel_id", "")),
            str(params.get("path", "")),
        )
    if method == "backgrounds.list":
        return list_backgrounds(connection, str(params.get("channel_id", "")))
    if method == "backgrounds.library":
        return list_background_library(connection)
    if method == "backgrounds.assign_to_channel":
        return assign_background_to_channel(
            connection,
            str(params.get("channel_id", "")),
            str(params.get("asset_id", "")),
        )
    if method == "backgrounds.remove_from_channel":
        return remove_background_from_channel(
            connection,
            str(params.get("channel_id", "")),
            str(params.get("asset_id", "")),
        )
    if method == "backgrounds.relink_asset":
        return relink_background_asset(
            connection,
            str(params.get("asset_id", "")),
            str(params.get("path", "")),
        )
    if method == "batches.list":
        return list_batches(connection)
    if method == "batches.get":
        return get_batch(connection, str(params.get("batch_id", "")))
    if method == "batches.import_text":
        raw_channel_id = params.get("channel_id")
        return import_batch_text(
            connection,
            str(params.get("name", "")),
            str(params.get("content", "")),
            str(raw_channel_id) if raw_channel_id else None,
            str(params.get("workflow_mode", "render")),
        )
    if method == "batches.append_text":
        raw_channel_id = params.get("channel_id")
        return append_batch_text(
            connection,
            str(params.get("batch_id", "")),
            str(params.get("content", "")),
            str(raw_channel_id) if raw_channel_id else None,
        )
    if method == "batches.lookup_metadata":
        return lookup_metadata_for_batch(connection, str(params.get("batch_id", "")))
    if method == "batches.rebalance_backgrounds":
        return plan_batch_backgrounds(connection, str(params.get("batch_id", "")))
    if method == "batches.configure_output_bulk":
        return configure_batch_output(connection, str(params.get("batch_id", "")), params)
    if method == "batches.set_thumbnail_mode":
        raw_mode = params.get("mode")
        return set_batch_thumbnail_mode(connection, str(params.get("batch_id", "")), str(raw_mode) if raw_mode else None)
    if method == "batches.set_thumbnail_pool":
        return set_batch_thumbnail_pool(connection, str(params.get("batch_id", "")), params.get("preset_ids", []))
    if method == "batches.update_job":
        raw_url = params.get("url")
        raw_channel_id = params.get("channel_id")
        return update_batch_job(
            connection,
            str(params.get("batch_id", "")),
            str(params.get("job_id", "")),
            str(raw_url) if raw_url is not None else None,
            str(raw_channel_id) if raw_channel_id else None,
            "channel_id" in params,
        )
    if method == "batches.remove_job":
        return remove_batch_job(
            connection,
            str(params.get("batch_id", "")),
            str(params.get("job_id", "")),
        )
    if method == "batches.override_background":
        return override_batch_background(
            connection,
            str(params.get("batch_id", "")),
            str(params.get("job_id", "")),
            str(params.get("asset_id", "")),
        )
    if method == "batches.confirm":
        return confirm_batch(connection, str(params.get("batch_id", "")))
    if method == "jobs.inspect_subtitles":
        return inspect_job_subtitles(connection, str(params.get("job_id", "")))
    if method == "jobs.set_subtitle_preset":
        raw_preset_id = params.get("preset_id")
        return set_job_subtitle_preset(connection, str(params.get("job_id", "")), str(raw_preset_id) if raw_preset_id else None)
    if method == "jobs.inspect_render":
        return inspect_job_render(connection, str(params.get("job_id", "")))
    if method == "jobs.configure_output":
        return configure_job_output(connection, str(params.get("job_id", "")), params)
    if method == "jobs.render_video":
        return render_job_video(connection, str(params.get("batch_id", "")), str(params.get("job_id", "")))
    if method == "jobs.set_thumbnail_mode":
        raw_mode = params.get("mode")
        return set_job_thumbnail_mode(connection, str(params.get("job_id", "")), str(raw_mode) if raw_mode else None)
    if method == "jobs.set_thumbnail_preset":
        return set_job_thumbnail_preset(connection, str(params.get("job_id", "")), str(params.get("preset_id", "")))
    if method == "jobs.set_thumbnail_text":
        return set_job_thumbnail_text(connection, str(params.get("job_id", "")), str(params.get("text", "")))
    if method == "jobs.render_thumbnail":
        return render_job_thumbnail(connection, str(params.get("job_id", "")), str(params["text"]) if params.get("text") is not None else None)
    if method == "jobs.download_thumbnail":
        return download_source_thumbnail(connection, str(params.get("job_id", "")))
    if method == "jobs.set_subtitle_language_override":
        return set_job_subtitle_override(
            connection,
            str(params.get("job_id", "")),
            params.get("languages", []),
        )
    if method == "jobs.attach_subtitle_file":
        return attach_job_subtitle_file(
            connection,
            str(params.get("job_id", "")),
            str(params.get("path", "")),
        )
    if method == "jobs.skip_captions":
        return skip_job_captions(connection, str(params.get("job_id", "")))
    if method == "jobs.download_sources":
        return download_job_sources(
            connection,
            str(params.get("batch_id", "")),
            str(params.get("job_id", "")),
            str(params.get("output_dir", "")),
            bool(params.get("include_video_source", False)),
        )
    raise ValueError(f"Unknown worker method: {method}")


def respond(database_path: str, request: dict[str, Any]) -> dict[str, Any]:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return {
            "id": request_id,
            "ok": False,
            "error": {"code": "invalid_request", "message": "Malformed worker request."},
        }
    try:
        with open_database(database_path) as connection:
            result = dispatch(connection, method, params, database_path)
        return {"id": request_id, "ok": True, "result": result}
    except (ValueError, sqlite3.Error) as error:
        return {
            "id": request_id,
            "ok": False,
            "error": {"code": "request_failed", "message": str(error)},
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--queue-worker-token")
    arguments = parser.parse_args()
    if arguments.queue_worker_token:
        return run_queue_worker(arguments.db_path, arguments.queue_worker_token)
    try:
        raw = sys.stdin.readline()
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("Worker request must be a JSON object.")
        response = respond(arguments.db_path, request)
    except (json.JSONDecodeError, ValueError) as error:
        response = {
            "id": None,
            "ok": False,
            "error": {"code": "invalid_request", "message": str(error)},
        }
    print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
