#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod portable;
#[path = "bin/updater.rs"]
mod updater;

use portable::{
    sha256_file, version_is_newer, BackendHandshake, PortableManifest, PortablePaths,
    DEFAULT_MANIFEST_URL, UPDATE_PUBLIC_KEY_B64,
};
use rand::RngCore;
use reqwest::{blocking::Client, redirect::Policy};
use serde::Serialize;
use std::{
    fs,
    io::{Read, Write},
    os::windows::io::AsRawHandle,
    path::PathBuf,
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    },
};

const LOCAL_TOKEN_HEADER: &str = "X-Bili-Local-Token";
const HEALTH_WAIT: Duration = Duration::from_secs(18);
const UPDATE_TIMEOUT: Duration = Duration::from_secs(30);
const EMBEDDED_BACKEND: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/resources/BiliOpinionBackend.exe"
));

struct AppState {
    paths: PortablePaths,
    token: String,
    api_base: String,
    app_version: String,
    child: Mutex<Option<Child>>,
    _job: WindowsJob,
    downloaded_update: Mutex<Option<DownloadedUpdate>>,
}

struct WindowsJob(HANDLE);

unsafe impl Send for WindowsJob {}
unsafe impl Sync for WindowsJob {}

impl Drop for WindowsJob {
    fn drop(&mut self) {
        if !self.0.is_null() {
            // SAFETY: the handle is owned by this wrapper and is closed once.
            unsafe { CloseHandle(self.0) };
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeConfig {
    api_base: String,
    local_token: String,
    app_version: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct UpdateCheck {
    enabled: bool,
    available: bool,
    version: Option<String>,
    notes_url: Option<String>,
    message: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DownloadedUpdate {
    version: String,
    executable_path: PathBuf,
    sha256: String,
}

impl AppState {
    fn start(paths: PortablePaths, app_version: String) -> anyhow::Result<Self> {
        let token = random_hex(32);
        let job = create_kill_on_close_job()?;
        paths.clear_abandoned_backend_temp()?;
        let backend = paths.materialize_embedded_backend(EMBEDDED_BACKEND, &app_version)?;
        let _ = fs::remove_file(&paths.handshake_path);
        let mut command = Command::new(backend);
        command
            .current_dir(&paths.runtime_dir)
            .env("BILI_DATA_DIR", &paths.data_dir)
            .env("BILI_DB_PATH", paths.data_dir.join("database.sqlite3"))
            .env("BILI_AUTH_PATH", paths.data_dir.join("auth.json"))
            .env("BILI_SETTINGS_PATH", paths.data_dir.join("settings.json"))
            .env("TEMP", &paths.backend_temp_dir)
            .env("TMP", &paths.backend_temp_dir)
            .env("TMPDIR", &paths.backend_temp_dir)
            .env("BILI_LOCAL_TOKEN", &token)
            .env("BILI_HANDSHAKE_PATH", &paths.handshake_path)
            .env("BILI_APP_VERSION", &app_version)
            .env("BILI_HOST", "127.0.0.1")
            .env("BILI_PORT", "0")
            .env("BILI_DESKTOP_MODE", "1");
        let child = command.spawn().map_err(|error| {
            anyhow::anyhow!("无法启动本地后端，请检查目录权限或安全软件设置：{error}")
        })?;
        assign_process_to_job(job.0, &child)?;
        let api_base = wait_for_backend(&paths.handshake_path, &token)?;

        Ok(Self {
            paths,
            token,
            api_base,
            app_version,
            child: Mutex::new(Some(child)),
            _job: job,
            downloaded_update: Mutex::new(None),
        })
    }

    fn has_active_tasks(&self) -> bool {
        let client = Client::builder().timeout(Duration::from_secs(2)).build();
        let Ok(client) = client else { return true };
        client
            .get(format!("{}/api/runtime/activity", self.api_base))
            .header(LOCAL_TOKEN_HEADER, &self.token)
            .send()
            .ok()
            .and_then(|response| response.json::<serde_json::Value>().ok())
            .and_then(|body| body.get("active").and_then(|value| value.as_bool()))
            .unwrap_or(true)
    }

    fn prepare_exit(&self) {
        let _ = Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .and_then(|client| {
                client
                    .post(format!("{}/api/runtime/prepare-exit", self.api_base))
                    .header(LOCAL_TOKEN_HEADER, &self.token)
                    .send()
            });
    }

    fn stop_child(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut process) = child.take() {
                let _ = process.kill();
                let _ = process.wait();
            }
        }
    }

    fn fetch_manifest(&self) -> anyhow::Result<PortableManifest> {
        if UPDATE_PUBLIC_KEY_B64.trim().is_empty() {
            anyhow::bail!("此测试构建未嵌入便携更新公钥，已禁用在线更新");
        }
        let manifest_url = std::env::var("BILI_PORTABLE_UPDATE_MANIFEST_URL")
            .unwrap_or_else(|_| DEFAULT_MANIFEST_URL.to_owned());
        let client = secure_update_client()?;
        let manifest: PortableManifest = client
            .get(manifest_url)
            .send()?
            .error_for_status()?
            .json()?;
        manifest.verify_signature(UPDATE_PUBLIC_KEY_B64)?;
        Ok(manifest)
    }
}

#[tauri::command]
fn runtime_config(state: State<'_, AppState>) -> RuntimeConfig {
    RuntimeConfig {
        api_base: frontend_api_base(&state.api_base),
        local_token: state.token.clone(),
        app_version: state.app_version.clone(),
    }
}

fn frontend_api_base(origin: &str) -> String {
    format!("{}/api", origin.trim_end_matches('/'))
}

#[tauri::command]
fn check_for_updates(state: State<'_, AppState>) -> Result<UpdateCheck, String> {
    match state.fetch_manifest() {
        Ok(manifest) => Ok(UpdateCheck {
            enabled: true,
            available: version_is_newer(&manifest.version, &state.app_version),
            version: Some(manifest.version),
            notes_url: Some(manifest.notes_url),
            message: None,
        }),
        Err(error) => Ok(UpdateCheck {
            enabled: false,
            available: false,
            version: None,
            notes_url: None,
            message: Some(error.to_string()),
        }),
    }
}

#[tauri::command]
fn download_update(state: State<'_, AppState>) -> Result<DownloadedUpdate, String> {
    let manifest = state.fetch_manifest().map_err(|error| error.to_string())?;
    if !version_is_newer(&manifest.version, &state.app_version) {
        return Err("当前已是最新版本".into());
    }
    if !manifest.asset.name.to_ascii_lowercase().ends_with(".exe") {
        return Err("已签名更新清单的程序文件名无效".into());
    }
    let final_path = state.paths.update_cache_dir.join("BiliOpinionMonitor.exe");
    let part_path = state
        .paths
        .update_cache_dir
        .join("BiliOpinionMonitor.exe.part");
    let client = secure_update_client().map_err(|error| error.to_string())?;
    let mut response = client
        .get(&manifest.asset.url)
        .send()
        .and_then(|response| response.error_for_status())
        .map_err(|error| format!("下载更新失败：{error}"))?;
    if response
        .content_length()
        .is_some_and(|length| length != manifest.asset.size)
    {
        return Err("更新包大小与已签名清单不一致".into());
    }
    let mut output = fs::File::create(&part_path).map_err(|error| error.to_string())?;
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = response
            .read(&mut buffer)
            .map_err(|error| error.to_string())?;
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > manifest.asset.size {
            let _ = fs::remove_file(&part_path);
            return Err("更新包超过已签名的文件大小".into());
        }
        output
            .write_all(&buffer[..count])
            .map_err(|error| error.to_string())?;
    }
    output.flush().map_err(|error| error.to_string())?;
    if total != manifest.asset.size
        || sha256_file(&part_path).map_err(|error| error.to_string())? != manifest.asset.sha256
    {
        let _ = fs::remove_file(&part_path);
        return Err("更新包校验失败，文件已删除".into());
    }
    validate_update_executable(&part_path).map_err(|error| error.to_string())?;
    let _ = fs::remove_file(&final_path);
    fs::rename(&part_path, &final_path).map_err(|error| error.to_string())?;
    let downloaded = DownloadedUpdate {
        version: manifest.version,
        executable_path: final_path,
        sha256: manifest.asset.sha256,
    };
    *state
        .downloaded_update
        .lock()
        .map_err(|_| "更新状态锁定失败")? = Some(downloaded.clone());
    Ok(downloaded)
}

#[tauri::command]
fn install_update(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    if state.has_active_tasks() {
        return Err("当前仍有抓取或分析任务，完成或停止后再安装更新".into());
    }
    let downloaded = state
        .downloaded_update
        .lock()
        .map_err(|_| "更新状态锁定失败")?
        .clone()
        .ok_or("请先完整下载并校验更新包")?;
    let installed_updater = state
        .paths
        .update_runner_dir
        .join("BiliOpinionMonitor-update-runner.exe");
    let current_executable =
        std::env::current_exe().map_err(|error| format!("无法定位当前程序：{error}"))?;
    fs::copy(&current_executable, &installed_updater)
        .map_err(|error| format!("无法准备更新器：{error}"))?;
    Command::new(installed_updater)
        .arg(updater::RUNNER_ARGUMENT)
        .arg("--staged-exe")
        .arg(downloaded.executable_path)
        .arg("--target-exe")
        .arg(&current_executable)
        .arg("--data-dir")
        .arg(&state.paths.data_dir)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg("--expected-version")
        .arg(downloaded.version)
        .arg("--expected-sha256")
        .arg(downloaded.sha256)
        .spawn()
        .map_err(|error| format!("无法启动更新器：{error}"))?;
    app.exit(0);
    Ok(())
}

/// Frontend contract: a native close request dispatches
/// `bili:close-requested` with `{ requestId }`. The UI must call this command
/// with the same request ID and one action: `exit`, `tray`, or `cancel`.
#[tauri::command]
fn resolve_close_request(
    app: AppHandle,
    state: State<'_, AppState>,
    action: String,
    request_id: Option<String>,
) -> Result<(), String> {
    // Request IDs make stale UI dialogs harmless; there is only one main window,
    // so no further state lookup is required for this first desktop release.
    let _ = request_id;
    match action.as_str() {
        "exit" => {
            state.prepare_exit();
            state.stop_child();
            app.exit(0);
        }
        "tray" => {
            if let Some(window) = app.get_webview_window("main") {
                window.hide().map_err(|error| error.to_string())?;
            }
        }
        "cancel" => {}
        _ => return Err("未知的关闭操作".into()),
    }
    Ok(())
}

fn main() {
    if std::env::args().nth(1).as_deref() == Some(updater::RUNNER_ARGUMENT) {
        if updater::run_update_runner().is_err() {
            std::process::exit(1);
        }
        return;
    }
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            let paths = PortablePaths::discover()?;
            let state = AppState::start(paths.clone(), env!("CARGO_PKG_VERSION").to_owned())?;
            app.manage(state);
            build_main_window(app, &paths)?;
            build_tray(app)?;
            write_healthy_marker(app, &paths)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            runtime_config,
            check_for_updates,
            download_update,
            install_update,
            resolve_close_request
        ])
        .build(tauri::generate_context!());

    match result {
        Ok(app) => app.run(|app_handle, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    state.stop_child();
                }
            }
        }),
        Err(error) => {
            let _ = fs::write("desktop-startup-error.txt", error.to_string());
            eprintln!("桌面程序启动失败：{error}");
        }
    }
}

fn build_main_window(app: &tauri::App, paths: &PortablePaths) -> tauri::Result<()> {
    let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("B站舆论监测平台")
        .inner_size(1280.0, 860.0)
        .min_inner_size(960.0, 640.0)
        .visible(false)
        // Keep Edge WebView profile/cache alongside the portable app, never in C:\\Users.
        .data_directory(paths.webview_dir.clone())
        .build()?;
    let close_window = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            let Some(state) = close_window.try_state::<AppState>() else { return };
            if state.has_active_tasks() {
                api.prevent_close();
                let request_id = random_hex(12);
                let encoded = serde_json::to_string(&request_id).unwrap_or_else(|_| "\"\"".into());
                let script = format!(
                    "window.dispatchEvent(new CustomEvent('bili:close-requested', {{ detail: {{ requestId: {encoded} }} }}));"
                );
                let _ = close_window.eval(&script);
            }
        }
    });
    window.show()?;
    Ok(())
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
    let exit = MenuItem::with_id(app, "exit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &exit])?;
    let tray = TrayIconBuilder::new()
        .tooltip("B站舆论监测平台")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "exit" => {
                if let Some(state) = app.try_state::<AppState>() {
                    state.prepare_exit();
                    state.stop_child();
                }
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;
    // Tauri's manager keeps the tray alive for the life of this application.
    app.manage(tray);
    Ok(())
}

fn wait_for_backend(handshake_path: &PathBuf, token: &str) -> anyhow::Result<String> {
    let deadline = Instant::now() + HEALTH_WAIT;
    let client = Client::builder().timeout(Duration::from_secs(2)).build()?;
    while Instant::now() < deadline {
        if let Ok(text) = fs::read_to_string(handshake_path) {
            if let Ok(handshake) = serde_json::from_str::<BackendHandshake>(&text) {
                if handshake.schema == 1 && handshake.port > 0 && handshake.pid > 0 {
                    let base = format!("http://127.0.0.1:{}", handshake.port);
                    if client
                        .get(format!("{base}/api/runtime/health"))
                        .header(LOCAL_TOKEN_HEADER, token)
                        .send()
                        .is_ok_and(|response| response.status().is_success())
                    {
                        return Ok(base);
                    }
                }
            }
        }
        thread::sleep(Duration::from_millis(180));
    }
    anyhow::bail!(
        "本地后端启动超时。请查看 data/logs，并确认安全软件没有拦截 BiliOpinionBackend.exe。"
    )
}

fn create_kill_on_close_job() -> anyhow::Result<WindowsJob> {
    // SAFETY: passing null names creates an anonymous job object owned by this process.
    let job = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
    if job.is_null() {
        anyhow::bail!("无法创建后端进程守护对象");
    }
    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    // SAFETY: `limits` is initialized and lives throughout this call.
    let success = unsafe {
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if success == 0 {
        unsafe { CloseHandle(job) };
        anyhow::bail!("无法配置后端进程守护对象");
    }
    Ok(WindowsJob(job))
}

fn assign_process_to_job(job: HANDLE, child: &Child) -> anyhow::Result<()> {
    // SAFETY: child process handle is valid while `child` is retained by AppState.
    if unsafe { AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) } == 0 {
        anyhow::bail!("无法将本地后端加入进程守护对象");
    }
    Ok(())
}

fn validate_update_executable(path: &PathBuf) -> anyhow::Result<()> {
    let mut header = [0_u8; 2];
    fs::File::open(path)?.read_exact(&mut header)?;
    if header != *b"MZ" {
        anyhow::bail!("更新文件不是 Windows 可执行程序");
    }
    Ok(())
}

/// GitHub release assets redirect to a CDN. Redirects are allowed only when
/// every destination remains HTTPS and the chain has at most five hops.
/// Signature, exact byte count, and SHA-256 remain the content trust root.
fn secure_update_client() -> anyhow::Result<Client> {
    Ok(Client::builder()
        .redirect(Policy::custom(|attempt| {
            if attempt.url().scheme() == "https" && attempt.previous().len() < 5 {
                attempt.follow()
            } else {
                attempt.stop()
            }
        }))
        .timeout(UPDATE_TIMEOUT)
        .build()?)
}

fn write_healthy_marker(app: &tauri::App, paths: &PortablePaths) -> anyhow::Result<()> {
    let pending = paths.update_cache_dir.join("pending-health.json");
    if pending.is_file() {
        let marker = serde_json::json!({
            "version": app.package_info().version.to_string(),
            "healthy_at": chrono_like_timestamp(),
        });
        fs::write(
            paths.update_cache_dir.join("healthy-version.json"),
            serde_json::to_vec(&marker)?,
        )?;
    }
    Ok(())
}

fn chrono_like_timestamp() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

fn random_hex(bytes: usize) -> String {
    let mut raw = vec![0_u8; bytes];
    rand::rngs::OsRng.fill_bytes(&mut raw);
    raw.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use super::frontend_api_base;

    #[test]
    fn desktop_csp_allows_locally_generated_qr_data_images_only() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let csp = config["app"]["security"]["csp"].as_str().unwrap();
        let login_page = include_str!("../../src/components/LoginPage.tsx");

        assert!(csp.contains("img-src"));
        assert!(csp.contains("data:"));
        assert!(!csp.contains("api.qrserver.com"));
        assert!(login_page.contains("image_data_url"));
        assert!(!login_page.contains("api.qrserver.com"));
    }

    #[test]
    fn desktop_frontend_receives_the_api_prefix() {
        assert_eq!(
            frontend_api_base("http://127.0.0.1:49152"),
            "http://127.0.0.1:49152/api"
        );
        assert_eq!(
            frontend_api_base("http://127.0.0.1:49152/"),
            "http://127.0.0.1:49152/api"
        );
    }
}
