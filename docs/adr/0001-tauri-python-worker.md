# Use Tauri with a Python local worker

Status: accepted

The app targets Windows x64 and macOS Apple Silicon as a local desktop tool, so it uses Tauri v2 with a React/TypeScript interface and a Python worker sidecar. Native file dialogs and explicit sidecar boundaries fit the local media workflow, while Python can coordinate yt-dlp, FFmpeg, and OCR without making the UI responsible for long-running work. This choice requires platform-specific packaged worker and tool binaries; code signing and notarization are handled before external distribution.
