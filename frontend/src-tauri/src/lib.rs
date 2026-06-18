use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

// Holds the spawned backend process so we can stop it when the app closes.
struct Backend(Mutex<Option<Child>>);

// Project location for this machine (personal desktop build). For a portable
// installer this would be replaced by a bundled PyInstaller sidecar.
const PROJECT_DIR: &str = r"C:\Users\ivank\Desktop\Sideproject\Study Copilot";

// In a release build the app starts the Python backend itself (single launch).
// In dev we rely on the manually-run backend, so we don't spawn a second one.
#[cfg(not(debug_assertions))]
fn spawn_backend() -> Option<Child> {
    let python = format!(r"{PROJECT_DIR}\.venv\Scripts\pythonw.exe");
    Command::new(python)
        .args([
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning",
        ])
        .current_dir(PROJECT_DIR)
        .spawn()
        .ok()
}

#[cfg(debug_assertions)]
fn spawn_backend() -> Option<Child> {
    None
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
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
            }
        });
}
