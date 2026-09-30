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

// The project's own Python (a developer checkout with a `.venv`).
#[cfg_attr(debug_assertions, allow(dead_code))]
fn venv_python(project_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        project_dir.join(".venv/Scripts/pythonw.exe")
    } else {
        project_dir.join(".venv/bin/python")
    }
}

// Where the packaged backend keeps its config and data. Must match
// default_home() in scripts/desktop_backend.py.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn user_data_dir() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("APPDATA").map(|base| PathBuf::from(base).join("Study Copilot"))
    }
    #[cfg(target_os = "macos")]
    {
        std::env::var_os("HOME").map(|home| {
            PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join("Study Copilot")
        })
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
            .map(|base| base.join("Study Copilot"))
    }
}

#[cfg_attr(debug_assertions, allow(dead_code))]
fn is_project_dir(path: &Path) -> bool {
    venv_python(path).is_file() && path.join("app/main.py").is_file()
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

// A one-line-per-event trail in <data dir>/app.log, so "the app opens but nothing works"
// can be diagnosed on a machine we cannot see.
#[cfg(not(debug_assertions))]
fn breadcrumb(message: &str) {
    use std::io::Write;
    let Some(dir) = user_data_dir().map(|dir| dir.join("data")) else { return };
    if fs::create_dir_all(&dir).is_err() {
        return;
    }
    if let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(dir.join("app.log")) {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_secs())
            .unwrap_or(0);
        let _ = writeln!(file, "[{secs}] {message}");
    }
}

#[cfg(debug_assertions)]
fn breadcrumb(_message: &str) {}

// In a release build the app starts the backend itself (single launch).
// In dev we rely on the manually-run backend, so we don't spawn a second one.
//
// Two ways to run it:
//  * a developer checkout that still has `.venv` next to it (the old behaviour:
//    `python -m uvicorn` from the project, using the project's config.yaml), or
//  * the frozen `study-copilot-backend` shipped inside the installer
//    (see scripts/build_backend.py). It keeps config and data in
//    %APPDATA%\Study Copilot (Windows) or ~/Library/Application Support/Study
//    Copilot (macOS) and needs no Python on the user's machine.
// STUDY_COPILOT_MODE=bundled forces the second even inside a checkout.
#[cfg(not(debug_assertions))]
fn spawn_backend(app: &tauri::AppHandle, port: u16) -> Option<Child> {
    let force_bundled = std::env::var("STUDY_COPILOT_MODE")
        .map(|value| value.eq_ignore_ascii_case("bundled"))
        .unwrap_or(false);
    if !force_bundled {
        if let Some(dir) = project_dir() {
            return spawn_project_backend(&dir, port);
        }
    }
    spawn_bundled_backend(app, port)
}

#[cfg(not(debug_assertions))]
fn spawn_project_backend(project_dir: &Path, port: u16) -> Option<Child> {
    let python = venv_python(project_dir);
    let port_arg = port.to_string();
    let mut cmd = Command::new(python);
    cmd.args([
        "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", port_arg.as_str(), "--log-level", "warning",
    ])
    .current_dir(project_dir)
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
    let _ = fs::write(port_file(project_dir), &port_arg);
    Some(child)
}

#[cfg(not(debug_assertions))]
fn spawn_bundled_backend(app: &tauri::AppHandle, port: u16) -> Option<Child> {
    let exe_name = if cfg!(windows) {
        "study-copilot-backend.exe"
    } else {
        "study-copilot-backend"
    };
    let resources = match app.path().resource_dir() {
        Ok(dir) => dir,
        Err(error) => {
            breadcrumb(&format!("no resource dir: {error}"));
            return None;
        }
    };
    let exe = resources.join("backend").join(exe_name);
    breadcrumb(&format!("backend exe {} (exists: {})", exe.display(), exe.is_file()));
    if !exe.is_file() {
        return None;
    }
    let port_arg = port.to_string();
    let mut cmd = Command::new(&exe);
    cmd.args(["--port", port_arg.as_str()])
        .current_dir(exe.parent()?)
        .stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    // Keep a log next to the user's data so problems can be diagnosed.
    let log_dir = user_data_dir().map(|dir| dir.join("data"));
    let log = log_dir.and_then(|dir| {
        fs::create_dir_all(&dir).ok()?;
        File::create(dir.join("backend.log")).ok()
    });
    match log {
        Some(f) => {
            let err = f.try_clone().ok();
            cmd.stdout(Stdio::from(f));
            cmd.stderr(err.map(Stdio::from).unwrap_or_else(Stdio::null));
        }
        None => {
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
        }
    }
    match cmd.spawn() {
        Ok(child) => {
            breadcrumb(&format!("backend started (pid {}) on port {port}", child.id()));
            Some(child)
        }
        Err(error) => {
            breadcrumb(&format!("backend failed to start: {error}"));
            None
        }
    }
}

#[cfg(debug_assertions)]
fn spawn_backend(_app: &tauri::AppHandle, _port: u16) -> Option<Child> {
    None
}

// On exit, kick off one vault sync. The helper waits for the app to finish
// closing (its backend port frees) before syncing, so the app and sync never
// write the vault at the same time. Detached, so it outlives the app.
#[cfg(not(debug_assertions))]
fn spawn_sync_on_close() {
    let Some(project_dir) = project_dir() else { return };
    let _ = fs::remove_file(port_file(&project_dir));
    let python = venv_python(&project_dir);
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
    breadcrumb(&format!("app start, port {port}"));
    let builder = tauri::Builder::default();
    // Registered first: a second launch of the app hands over to this one
    // (its window comes to the front) and exits before starting a backend.
    // Release builds only, so `tauri dev` still runs next to the installed app.
    #[cfg(all(desktop, not(debug_assertions)))]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
        }
    }));
    builder
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![backend_url])
        .setup(move |app| {
            breadcrumb("setup reached");
            let child = spawn_backend(app.handle(), port);
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
