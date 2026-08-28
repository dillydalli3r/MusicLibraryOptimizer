//! Music Library Optimizer — Tauri desktop shell.
//!
//! Spawns the Python FastAPI backend (`server.main:app` on 127.0.0.1:8000)
//! when the app starts and kills it on exit. The React UI (web/dist) is
//! served by the Tauri webview and talks to the backend over HTTP.

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

struct BackendState(Mutex<Option<Child>>);

const PORT: &str = "8000";

/// Try to locate the backend entry point.
///
/// Preference order:
///   1. bundled `mlo-server.exe` sidecar next to the app binary
///   2. `python`/`python3` on PATH running `-m uvicorn server.main:app`
///      from the project root (works from the repo checkout)
fn find_backend(app: &tauri::AppHandle) -> (String, Vec<String>, Option<PathBuf>) {
    // 1. bundled executable (PyInstaller one-file build of server.main)
    if let Ok(dir) = app.path().resource_dir() {
        for name in ["mlo-server.exe", "mlo-server"] {
            let cand = dir.join(name);
            if cand.is_file() {
                return (cand.to_string_lossy().to_string(), Vec::new(), None);
            }
        }
    }

    // 2. project-root checkout: python -m uvicorn server.main:app
    let root = project_root();
    let mut args = vec![
        "-m".into(),
        "uvicorn".into(),
        "server.main:app".into(),
        "--host".into(),
        "127.0.0.1".into(),
        "--port".into(),
        PORT.into(),
    ];
    if !root.is_dir() {
        // absolute fallback: rely on a python module installed elsewhere
        args.clear();
    }
    let py = which_python();
    (py, args, root.is_dir().then_some(root))
}

fn which_python() -> String {
    for cand in ["python", "python3"] {
        if let Ok(out) = Command::new(cand).arg("--version").output() {
            if out.status.success() {
                return cand.to_string();
            }
        }
    }
    "python".to_string()
}

fn project_root() -> PathBuf {
    let mut dir = std::env::current_dir().unwrap_or_default();
    // During `tauri dev` cwd is desktop/src-tauri; climb to the repo root.
    if dir.file_name().map(|n| n == "src-tauri").unwrap_or(false) {
        dir.pop();
        if dir.file_name().map(|n| n == "desktop").unwrap_or(false) {
            dir.pop();
        }
    }
    dir
}

fn spawn_backend(app: &tauri::AppHandle) {
    let (exe, args, cwd) = find_backend(app);
    let mut cmd = Command::new(&exe);
    cmd.args(&args);
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    cmd.env("MLO_BACKEND_PORT", PORT);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    match cmd.spawn() {
        Ok(child) => {
            if let Some(state) = app.try_state::<BackendState>() {
                *state.0.lock().unwrap() = Some(child);
            }
            println!("[mlo-desktop] backend spawned: {exe}");
        }
        Err(e) => eprintln!("[mlo-desktop] failed to start backend ({exe}): {e}"),
    }
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Some(mut child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
            println!("[mlo-desktop] backend stopped");
        }
    }
}

/// Native folder picker (also reachable from the web UI via invoke when
/// running inside the Tauri webview).
#[tauri::command]
fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    app.dialog()
        .file()
        .blocking_pick_folder()
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().to_string())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![pick_folder])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                // Give the backend a moment to boot before the UI polls it.
                std::thread::sleep(Duration::from_secs(2));
                spawn_backend(&handle);
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                stop_backend(&window.app_handle().clone());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running MusicLibraryOptimizer");
}