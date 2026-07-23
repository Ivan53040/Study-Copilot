use std::fs::File;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

// Holds the spawned backend process so we can stop it when the app closes.
struct Backend(Mutex<Option<Child>>);

fn project_dir() -> Option<PathBuf> {
    std::env::var_os("STUDY_COPILOT_PROJECT_DIR")
        .map(PathBuf::from)
        .or_else(|| std::env::current_exe().ok()?.parent().map(PathBuf::from))
}

// In a release build the app starts the Python backend itself (single launch).
// In dev we rely on the manually-run backend, so we don't spawn a second one.
#[cfg(not(debug_assertions))]
fn spawn_backend() -> Option<Child> {
    let project_dir = project_dir()?;
    let python = project_dir.join(".venv/Scripts/pythonw.exe");
    let mut cmd = Command::new(python);
    cmd.args([
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning",
    ])
    .current_dir(&project_dir)
    .stdin(Stdio::null());

    // A detached GUI launch has no valid stdio; if the child inherits those
    // handles its logging crashes. Redirect to a log file (or null) instead.
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
    cmd.spawn().ok()
}

#[cfg(debug_assertions)]
fn spawn_backend() -> Option<Child> {
    None
}

// On exit, kick off one vault sync. The helper waits for the app to finish
// closing (its backend port frees) before syncing, so the app and sync never
// write the vault at the same time. Detached, so it outlives the app.
#[cfg(not(debug_assertions))]
fn spawn_sync_on_close() {
    let Some(project_dir) = project_dir() else { return };
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let child = spawn_backend();
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
                        }
                    }
                }
                spawn_sync_on_close();
            }
        });
}
