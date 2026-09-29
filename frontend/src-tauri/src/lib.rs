#[cfg(not(debug_assertions))]
use std::fs::{self, File};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
#[cfg(not(debug_assertions))]
use std::process::{Command, Stdio};
use std::process::Child;
use std::sync::Mutex;
use tauri::Manager;

// Holds the spawned backend process so we can stop it when the app closes.
struct Backend(Mutex<Option<Child>>);

// The URL of the backend this app started (None in dev, where the Vite proxy
// reaches a manually started backend). The page asks for it at startup.
struct BackendUrl(Option<String>);

// Preferred backend port. 8765 is often taken by other local model servers,
// and 8766/8767 are used by the dev and one-click launchers, so the desktop
// app defaults to 8768 and falls back to any free port when that is busy.
// Set STUDY_COPILOT_PORT to force a specific port.
const DEFAULT_PORT: u16 = 8768;

fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn choose_port() -> u16 {
    if let Some(port) = std::env::var("STUDY_COPILOT_PORT")
        .ok()
        .and_then(|value| value.trim().parse::<u16>().ok())
        .filter(|port| *port != 0)
    {
        return port;
    }
    if port_is_free(DEFAULT_PORT) {
        return DEFAULT_PORT;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(DEFAULT_PORT)
}

#[cfg_attr(debug_assertions, allow(dead_code))]
fn is_project_dir(path: &Path) -> bool {
    path.join(".venv/Scripts/pythonw.exe").is_file() && path.join("app/main.py").is_file()
}

#[cfg_attr(debug_assertions, allow(dead_code))]
fn project_dir() -> Option<PathBuf> {
    std::env::var_os("STUDY_COPILOT_PROJECT_DIR")
        .map(PathBuf::from)
        .filter(|path| is_project_dir(path))
        .or_else(|| {
            let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
            is_project_dir(&path).then_some(path)
        })
        .or_else(|| {
            let path = std::env::current_exe().ok()?.parent()?.to_path_buf();
            is_project_dir(&path).then_some(path)
        })
}

// Where the running backend's port is recorded, so the background sync task
// can tell the app is open even when it had to use a non-default port.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn port_file(project_dir: &Path) -> PathBuf {
    project_dir.join("data/desktop-port.txt")
}

// In a release build the app starts the Python backend itself (single launch).
// In dev we rely on the manually-run backend, so we don't spawn a second one.
#[cfg(not(debug_assertions))]
fn spawn_backend(port: u16) -> Option<Child> {
    let project_dir = project_dir()?;
    let python = project_dir.join(".venv/Scripts/pythonw.exe");
    let port_arg = port.to_string();
    let mut cmd = Command::new(python);
    cmd.args([
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", port_arg.as_str(), "--log-level", "warning",
    ])
    .current_dir(&project_dir)
    .stdin(Stdio::null());

    // A detached GUI launch has no valid stdio; if the child inherits those
    // handles its logging crashes. Redirect to a log file (or null) instead.
    let _ = fs::create_dir_all(project_dir.join("data"));
    match File::create(project_dir.join("data/desktop-backend.log")) {
        Ok(f) => {
            let err = f.try_clone().ok();
            cmd.stdout(Stdio::from(f));
            cmd.stderr(err.map(Stdio::from).unwrap_or_else(Stdio::null));
        }
        Err(_) => {
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    let child = cmd.spawn().ok()?;
    let _ = fs::write(port_file(&project_dir), &port_arg);
    Some(child)
}

#[cfg(debug_assertions)]
fn spawn_backend(_port: u16) -> Option<Child> {
    None
}

// On exit, kick off one vault sync. The helper waits for the app to finish
// closing (its backend port frees) before syncing, so the app and sync never
// write the vault at the same time. Detached, so it outlives the app.
#[cfg(not(debug_assertions))]
fn spawn_sync_on_close() {
    let Some(project_dir) = project_dir() else { return };
    let _ = fs::remove_file(port_file(&project_dir));
    let python = project_dir.join(".venv/Scripts/pythonw.exe");
    let script = project_dir.join("scripts/sync_standalone.py");
    let _ = Command::new(python)
        .arg(script)
        .arg("--on-close")
        .current_dir(project_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

#[cfg(debug_assertions)]
fn spawn_sync_on_close() {}

#[tauri::command]
fn backend_url(state: tauri::State<'_, BackendUrl>) -> Option<String> {
    state.0.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port = choose_port();
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_url])
        .setup(move |app| {
            let child = spawn_backend(port);
            let url = child
                .as_ref()
                .map(|_| format!("http://127.0.0.1:{port}"));
            app.manage(BackendUrl(url));
            app.manage(Backend(Mutex::new(child)));
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<Backend>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
                spawn_sync_on_close();
            }
        });
}
