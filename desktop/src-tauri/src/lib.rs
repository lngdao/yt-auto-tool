use serde_json::{json, Value};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

fn app_data_tool(app_tools: &Path, tool_name: &str) -> Option<PathBuf> {
    let metadata = std::fs::read_to_string(app_tools.join(format!("{tool_name}.json"))).ok()?;
    let value: Value = serde_json::from_str(&metadata).ok()?;
    let relative = Path::new(value.get("relative_path")?.as_str()?);
    if relative.as_os_str().is_empty()
        || relative.is_absolute()
        || relative.components().any(|component| !matches!(component, Component::Normal(_)))
    {
        return None;
    }
    let path = app_tools.join(relative);
    path.is_file().then_some(path)
}

#[tauri::command]
async fn worker_request(
    app: AppHandle,
    method: String,
    params: Value,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let data_dir = app
            .path()
            .app_data_dir()
            .map_err(|error| format!("Could not locate the application data folder: {error}"))?;
        std::fs::create_dir_all(&data_dir)
            .map_err(|error| format!("Could not create the application data folder: {error}"))?;

        let resource_directory = app
            .path()
            .resource_dir()
            .map_err(|error| format!("Could not locate the bundled application resources: {error}"))?;
        let tool_directory = resource_directory.join("resources").join("tools");
        let executable_name = if cfg!(windows) {
            "youtube-video-batch-worker.exe"
        } else {
            "youtube-video-batch-worker"
        };
        let packaged_worker = tool_directory
            .join("worker")
            .join("youtube-video-batch-worker")
            .join(executable_name);
        let worker_script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("worker")
            .join("worker.py");
        let bundled_worker = packaged_worker.is_file();
        if !bundled_worker && !worker_script.is_file() {
            return Err(format!(
                "The packaged worker was not found at {} and the development worker was not found at {}.",
                packaged_worker.display(), worker_script.display()
            ));
        }

        let worker_directory = worker_script.parent();
        let virtual_python = if let Some(worker_directory) = worker_directory {
            if cfg!(windows) {
                worker_directory.join(".venv").join("Scripts").join("python.exe")
            } else {
                worker_directory.join(".venv").join("bin").join("python")
            }
        } else {
            PathBuf::new()
        };
        let executable = if bundled_worker {
            packaged_worker.clone()
        } else {
            std::env::var("YOUTUBE_BATCH_PYTHON")
                .map(PathBuf::from)
                .unwrap_or_else(|_| {
                    if virtual_python.is_file() {
                        virtual_python
                    } else if cfg!(windows) {
                        PathBuf::from("python")
                    } else {
                        PathBuf::from("python3")
                    }
                })
        };
        let request_id = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|value| value.as_nanos().to_string())
            .unwrap_or_else(|_| "0".to_string());
        let request = json!({
            "id": request_id,
            "method": method,
            "params": params,
        });

        let mut command = Command::new(executable);
        if !bundled_worker {
            command.arg(&worker_script);
        }
        command
            .arg("--db-path")
            .arg(data_dir.join("youtube-video-batch.sqlite3"));

        if bundled_worker {
            let tools_bin = tool_directory.join("bin");
            let app_tools = data_dir.join("tools");
            let mut search_paths = vec![tools_bin.clone()];
            search_paths.push(app_tools.clone());
            if let Some(existing_path) = std::env::var_os("PATH") {
                search_paths.extend(std::env::split_paths(&existing_path));
            }
            let joined_path = std::env::join_paths(search_paths)
                .map_err(|error| format!("Could not configure bundled media tool paths: {error}"))?;
            command
                .env("PATH", joined_path)
                .env("YOUTUBE_BATCH_RESOURCE_DIR", &tool_directory);
            let tool_names = if cfg!(windows) {
                ["ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "tesseract.exe", "deno.exe"]
            } else {
                ["ffmpeg", "ffprobe", "yt-dlp", "tesseract", "deno"]
            };
            for (environment_name, file_name) in [
                "FFMPEG_BINARY", "FFPROBE_BINARY", "YTDLP_BINARY", "TESSERACT_BINARY", "DENO_BINARY",
            ]
            .into_iter()
            .zip(tool_names)
            {
                let mutable_tool = match environment_name {
                    "YTDLP_BINARY" => Some("yt-dlp"),
                    "DENO_BINARY" => Some("deno"),
                    _ => None,
                };
                let path = if let Some(tool_name) = mutable_tool {
                    app_data_tool(&app_tools, tool_name).unwrap_or_else(|| tools_bin.join(file_name))
                } else {
                    tools_bin.join(file_name)
                };
                if path.is_file() {
                    command.env(environment_name, path);
                }
            }
            let app_tessdata = data_dir.join("tessdata");
            let tessdata = if app_tessdata.is_dir() {
                app_tessdata
            } else {
                tool_directory.join("tessdata")
            };
            if tessdata.is_dir() {
                command.env("TESSDATA_DIR", tessdata);
            }
        } else {
            let app_tools = data_dir.join("tools");
            let mut search_paths = vec![app_tools.clone()];
            if let Some(existing_path) = std::env::var_os("PATH") {
                search_paths.extend(std::env::split_paths(&existing_path));
            }
            let joined_path = std::env::join_paths(search_paths)
                .map_err(|error| format!("Could not configure app-data tool paths: {error}"))?;
            command.env("PATH", joined_path);
            for (environment_name, name) in [("YTDLP_BINARY", "yt-dlp"), ("DENO_BINARY", "deno")] {
                if let Some(path) = app_data_tool(&app_tools, name) {
                    command.env(environment_name, path);
                }
            }
        }

        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start the local worker: {error}"))?;

        let request_line = serde_json::to_vec(&request)
            .map_err(|error| format!("Could not encode the worker request: {error}"))?;
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| "Could not open the local worker input stream.".to_string())?;
        stdin
            .write_all(&request_line)
            .and_then(|_| stdin.write_all(b"\n"))
            .map_err(|error| format!("Could not send a request to the local worker: {error}"))?;
        drop(stdin);

        let output = child
            .wait_with_output()
            .map_err(|error| format!("Could not read the local worker response: {error}"))?;
        if !output.status.success() {
            let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
            return Err(if detail.is_empty() {
                "The local worker exited unexpectedly.".to_string()
            } else {
                format!("The local worker exited unexpectedly: {detail}")
            });
        }
        let response: Value = serde_json::from_slice(&output.stdout)
            .map_err(|error| format!("The local worker returned an invalid response: {error}"))?;
        if response.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(response
                .pointer("/error/message")
                .and_then(Value::as_str)
                .unwrap_or("The local worker could not complete the request.")
                .to_string());
        }
        response
            .get("result")
            .cloned()
            .ok_or_else(|| "The local worker response did not contain a result.".to_string())
    })
    .await
    .map_err(|error| format!("The worker request could not be completed: {error}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![worker_request])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
