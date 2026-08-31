#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod portable;
#[path = "bin/updater.rs"]
mod updater;

use portable::{
    sha256_file, validate_mcp_database_path, version_is_newer, BackendHandshake, EmbeddedComponent,
    PortableManifest, PortablePaths, DEFAULT_MANIFEST_URL, UPDATE_PUBLIC_KEY_B64,
};
use rand::RngCore;
use reqwest::{blocking::Client, redirect::Policy};
use serde::Serialize;
use std::{
    env,
    ffi::OsString,
    fs,
    io::{Read, Write},
    os::windows::{
        ffi::{OsStrExt, OsStringExt},
        io::AsRawHandle,
    },
    path::{Path, PathBuf},
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
    Foundation::{
        CloseHandle, DuplicateHandle, DUPLICATE_SAME_ACCESS, HANDLE, INVALID_HANDLE_VALUE,
        WAIT_OBJECT_0,
    },
    System::{
        Console::{GetStdHandle, STD_ERROR_HANDLE, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE},
        JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        SystemInformation::GetWindowsDirectoryW,
        Threading::{
            CreateEventW, CreateProcessW, GetCurrentProcess, GetExitCodeProcess, ResumeThread,
            TerminateProcess, WaitForSingleObject, CREATE_NO_WINDOW, CREATE_SUSPENDED,
            CREATE_UNICODE_ENVIRONMENT, INFINITE, PROCESS_INFORMATION, STARTF_USESTDHANDLES,
            STARTUPINFOW,
        },
    },
};

const LOCAL_TOKEN_HEADER: &str = "X-Bili-Local-Token";
const HEALTH_WAIT: Duration = Duration::from_secs(18);
const UPDATE_TIMEOUT: Duration = Duration::from_secs(30);
const EMBEDDED_BACKEND: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/resources/BiliOpinionBackend.exe"
));
const EMBEDDED_AGENT_MCP: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/resources/BiliOpinionAgentMcp.exe"
));
const MCP_STDIO_ARGUMENT: &str = "--mcp-stdio";
const UPDATE_READY_WAIT: Duration = Duration::from_secs(5);

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

enum StartMode {
    Gui,
    McpStdio,
    UpdateRunner,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum McpStartupStage {
    Discover,
    CoordinationLock,
    Session,
    DatabaseValidate,
    Materialize,
    Environment,
    JobCreate,
    ProcessCreate,
    JobAssign,
    Resume,
    Wait,
    ExitCode,
}

impl McpStartupStage {
    fn code(self) -> &'static str {
        match self {
            Self::Discover => "DISCOVER",
            Self::CoordinationLock => "COORDINATION_LOCK",
            Self::Session => "SESSION",
            Self::DatabaseValidate => "DATABASE_VALIDATE",
            Self::Materialize => "MATERIALIZE",
            Self::Environment => "ENVIRONMENT",
            Self::JobCreate => "JOB_CREATE",
            Self::ProcessCreate => "PROCESS_CREATE",
            Self::JobAssign => "JOB_ASSIGN",
            Self::Resume => "RESUME",
            Self::Wait => "WAIT",
            Self::ExitCode => "EXIT_CODE",
        }
    }
}

#[derive(Clone, Copy)]
struct McpStartupFailure(McpStartupStage);

struct SuspendedChild {
    process: HANDLE,
    thread: HANDLE,
}

struct InheritableStdio {
    input: HANDLE,
    output: HANDLE,
    error: HANDLE,
}

impl InheritableStdio {
    fn from_current_process() -> anyhow::Result<Self> {
        // SAFETY: querying standard handles has no side effects.
        let input = unsafe { GetStdHandle(STD_INPUT_HANDLE) };
        let output = unsafe { GetStdHandle(STD_OUTPUT_HANDLE) };
        let error = unsafe { GetStdHandle(STD_ERROR_HANDLE) };
        let input = duplicate_inheritable_stdio_handle(input)?;
        let output = match duplicate_inheritable_stdio_handle(output) {
            Ok(handle) => handle,
            Err(error) => {
                unsafe { CloseHandle(input) };
                return Err(error);
            }
        };
        let error = match duplicate_inheritable_stdio_handle(error) {
            Ok(handle) => handle,
            Err(error) => {
                unsafe {
                    CloseHandle(input);
                    CloseHandle(output);
                }
                return Err(error);
            }
        };
        Ok(Self {
            input,
            output,
            error,
        })
    }
}

impl Drop for InheritableStdio {
    fn drop(&mut self) {
        // SAFETY: these are independently duplicated handles owned by this wrapper.
        unsafe {
            CloseHandle(self.input);
            CloseHandle(self.output);
            CloseHandle(self.error);
        }
    }
}

impl SuspendedChild {
    fn terminate_and_wait(&self) {
        // SAFETY: both handles are valid until this object is dropped.
        unsafe {
            TerminateProcess(self.process, 1);
            WaitForSingleObject(self.process, INFINITE);
        }
    }

    fn resume(&self) -> anyhow::Result<()> {
        // SAFETY: the primary thread is suspended by CreateProcessW.
        if unsafe { ResumeThread(self.thread) } == u32::MAX {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(())
    }

    fn wait_for_exit(&self) -> anyhow::Result<()> {
        // SAFETY: process is owned and valid until Drop.
        if unsafe { WaitForSingleObject(self.process, INFINITE) } != WAIT_OBJECT_0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(())
    }

    fn exit_code(&self) -> anyhow::Result<u32> {
        let mut exit_code = 0;
        // SAFETY: process is valid and exit_code is writable.
        if unsafe { GetExitCodeProcess(self.process, &mut exit_code) } == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(exit_code)
    }
}

impl Drop for SuspendedChild {
    fn drop(&mut self) {
        // SAFETY: handles are owned by this wrapper and are each closed once.
        unsafe {
            if !self.thread.is_null() {
                CloseHandle(self.thread);
            }
            if !self.process.is_null() {
                CloseHandle(self.process);
            }
        }
    }
}

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
    let ready_event = format!("Local\\BiliOpinionUpdateReady-{}", random_hex(16));
    let ready_event_wide =
        wide_nul(std::ffi::OsStr::new(&ready_event)).map_err(|error| error.to_string())?;
    // SAFETY: the event name is NUL-terminated and uses an unguessable suffix.
    let ready_handle = unsafe { CreateEventW(std::ptr::null(), 1, 0, ready_event_wide.as_ptr()) };
    if ready_handle.is_null() {
        return Err("无法建立更新协调信号".into());
    }
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
        .arg("--ready-event")
        .arg(&ready_event)
        .spawn()
        .map_err(|error| {
            // SAFETY: this branch still owns the event handle.
            unsafe { CloseHandle(ready_handle) };
            format!("无法启动更新器：{error}")
        })?;
    // The runner signals only after it holds the exclusive lock.  Keeping GUI
    // alive until then removes the check/exit/acquire race with a new MCP run.
    let ready = unsafe { WaitForSingleObject(ready_handle, UPDATE_READY_WAIT.as_millis() as u32) };
    unsafe { CloseHandle(ready_handle) };
    if ready != WAIT_OBJECT_0 {
        return Err("更新器未能取得安装协调锁；可能仍有 MCP 会话正在运行".into());
    }
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
    match parse_start_mode() {
        Ok(StartMode::UpdateRunner) => {
            if updater::run_update_runner().is_err() {
                std::process::exit(1);
            }
            return;
        }
        Ok(StartMode::McpStdio) => {
            let exit_code = run_mcp_stdio().unwrap_or_else(|failure| {
                eprintln!("{}", mcp_start_failure_message(failure.0));
                1
            });
            std::process::exit(exit_code as i32);
        }
        Ok(StartMode::Gui) => {}
        Err(_) => {
            eprintln!("启动参数无效");
            std::process::exit(2);
        }
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

fn parse_start_mode() -> anyhow::Result<StartMode> {
    parse_start_mode_from(env::args_os().skip(1).collect())
}

fn parse_start_mode_from(arguments: Vec<OsString>) -> anyhow::Result<StartMode> {
    match arguments.as_slice() {
        [] => Ok(StartMode::Gui),
        [argument] if argument == MCP_STDIO_ARGUMENT => Ok(StartMode::McpStdio),
        [argument, ..] if argument == updater::RUNNER_ARGUMENT => Ok(StartMode::UpdateRunner),
        _ => anyhow::bail!("只支持无参数 GUI、--mcp-stdio 或受限的内部更新器参数"),
    }
}

fn run_mcp_stdio() -> Result<u32, McpStartupFailure> {
    let paths =
        PortablePaths::discover().map_err(|_| McpStartupFailure(McpStartupStage::Discover))?;
    // The guard lives until the child has fully exited, blocking updater's
    // exclusive installation lock and preventing a mid-session replacement.
    let _coordination_lock = paths
        .acquire_mcp_lock()
        .map_err(|_| McpStartupFailure(McpStartupStage::CoordinationLock))?;
    paths
        .clear_abandoned_mcp_sessions()
        .map_err(|_| McpStartupFailure(McpStartupStage::Session))?;
    let session = paths
        .create_mcp_session()
        .map_err(|_| McpStartupFailure(McpStartupStage::Session))?;
    let database = env::var_os("BILI_MCP_DB_PATH")
        .ok_or(McpStartupFailure(McpStartupStage::DatabaseValidate))?;
    let database = validate_mcp_database_path(Path::new(&database))
        .map_err(|_| McpStartupFailure(McpStartupStage::DatabaseValidate))?;
    let executable = paths
        .materialize_embedded_component(
            EmbeddedComponent::AgentMcp,
            EMBEDDED_AGENT_MCP,
            env!("CARGO_PKG_VERSION"),
        )
        .map_err(|_| McpStartupFailure(McpStartupStage::Materialize))?;
    let environment = mcp_environment(&session, &database)
        .map_err(|_| McpStartupFailure(McpStartupStage::Environment))?;
    let job =
        create_kill_on_close_job().map_err(|_| McpStartupFailure(McpStartupStage::JobCreate))?;
    let child = create_suspended_mcp_process(&executable, &paths.runtime_dir, &environment)
        .map_err(|_| McpStartupFailure(McpStartupStage::ProcessCreate))?;
    if assign_process_handle_to_job(job.0, child.process).is_err() {
        child.terminate_and_wait();
        return Err(McpStartupFailure(McpStartupStage::JobAssign));
    }
    if child.resume().is_err() {
        child.terminate_and_wait();
        return Err(McpStartupFailure(McpStartupStage::Resume));
    }
    // `session`, lock and job intentionally stay alive while the child owns
    // stdio. If waiting or reading its exit code fails, terminate and reap the
    // suspended/job-owned tree before allowing any guard to drop.
    if child.wait_for_exit().is_err() {
        child.terminate_and_wait();
        return Err(McpStartupFailure(McpStartupStage::Wait));
    }
    child
        .exit_code()
        .map_err(|_| McpStartupFailure(McpStartupStage::ExitCode))
}

fn mcp_environment(session: &portable::McpSession, database: &Path) -> anyhow::Result<Vec<u16>> {
    let windows_dir = windows_directory_from_api()?;
    mcp_environment_from_windows_dir(session, database, &windows_dir)
}

fn mcp_environment_from_windows_dir(
    session: &portable::McpSession,
    database: &Path,
    windows_dir: &Path,
) -> anyhow::Result<Vec<u16>> {
    let windows_metadata = fs::symlink_metadata(windows_dir)?;
    if windows_metadata.file_type().is_symlink() || !windows_metadata.is_dir() {
        anyhow::bail!("Windows 系统目录不可用")
    }
    let comspec = windows_dir.join("System32").join("cmd.exe");
    let comspec_metadata = fs::symlink_metadata(&comspec)?;
    if comspec_metadata.file_type().is_symlink() || !comspec_metadata.is_file() {
        anyhow::bail!("Windows 命令解释器不可用")
    }
    let mut values: Vec<(String, OsString)> = vec![
        ("SystemRoot".into(), windows_dir.as_os_str().to_owned()),
        ("WINDIR".into(), windows_dir.as_os_str().to_owned()),
        ("ComSpec".into(), comspec.into_os_string()),
    ];
    values.extend([
        ("TEMP".into(), session.path().as_os_str().to_owned()),
        ("TMP".into(), session.path().as_os_str().to_owned()),
        ("TMPDIR".into(), session.path().as_os_str().to_owned()),
        ("BILI_MCP_DB_PATH".into(), database.as_os_str().to_owned()),
    ]);
    values.sort_by(|left, right| left.0.cmp(&right.0));
    let mut block = Vec::new();
    for (key, value) in values {
        block.extend(std::ffi::OsStr::new(&key).encode_wide());
        block.push(b'=' as u16);
        block.extend(value.encode_wide());
        block.push(0);
    }
    block.push(0);
    Ok(block)
}

fn windows_directory_from_api() -> anyhow::Result<PathBuf> {
    let mut buffer = vec![0_u16; 32_768];
    // SAFETY: buffer is writable and length is supplied in UTF-16 units.
    let length = unsafe { GetWindowsDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) };
    if length == 0 || length as usize >= buffer.len() {
        anyhow::bail!("无法确定 Windows 系统目录")
    }
    buffer.truncate(length as usize);
    Ok(PathBuf::from(OsString::from_wide(&buffer)))
}

fn create_suspended_mcp_process(
    executable: &Path,
    current_dir: &Path,
    environment: &[u16],
) -> anyhow::Result<SuspendedChild> {
    let executable_wide = wide_nul(executable.as_os_str())?;
    let current_dir_wide = wide_nul(current_dir.as_os_str())?;
    let mut command_line = quote_windows_argument(executable.as_os_str());
    command_line.push(0);
    let mut startup: STARTUPINFOW = unsafe { std::mem::zeroed() };
    startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
    startup.dwFlags = STARTF_USESTDHANDLES;
    // Inspector can provide valid, non-inheritable pipe handles. Duplicate each
    // one with inheritability enabled; do not mutate or require flags on its
    // original handles.
    let inherited_stdio = InheritableStdio::from_current_process()?;
    startup.hStdInput = inherited_stdio.input;
    startup.hStdOutput = inherited_stdio.output;
    startup.hStdError = inherited_stdio.error;
    let mut process_info: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: all UTF-16 arguments are NUL-terminated, command_line remains
    // mutable for this call, and CreateProcess starts suspended before its
    // PyInstaller bootloader can create a descendant.
    if unsafe {
        CreateProcessW(
            executable_wide.as_ptr(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
            CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            environment.as_ptr().cast(),
            current_dir_wide.as_ptr(),
            &startup,
            &mut process_info,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(SuspendedChild {
        process: process_info.hProcess,
        thread: process_info.hThread,
    })
}

fn duplicate_inheritable_stdio_handle(source: HANDLE) -> anyhow::Result<HANDLE> {
    if !is_valid_std_handle(source) {
        anyhow::bail!("MCP stdio 不可用")
    }
    let mut duplicate = std::ptr::null_mut();
    // SAFETY: source is a valid handle in the current process. The duplicate
    // belongs to this process, uses the same access rights, and is inheritable.
    if unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            source,
            GetCurrentProcess(),
            &mut duplicate,
            0,
            1,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0
        || !is_valid_std_handle(duplicate)
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(duplicate)
}

fn is_valid_std_handle(handle: HANDLE) -> bool {
    !handle.is_null() && handle != INVALID_HANDLE_VALUE
}

fn mcp_start_failure_message(stage: McpStartupStage) -> String {
    format!("MCP_START_FAILED({})", stage.code())
}

fn quote_windows_argument(value: &std::ffi::OsStr) -> Vec<u16> {
    let mut output = Vec::from([b'"' as u16]);
    let mut backslashes = 0;
    for unit in value.encode_wide() {
        if unit == b'\\' as u16 {
            backslashes += 1;
        } else if unit == b'"' as u16 {
            output.extend(std::iter::repeat(b'\\' as u16).take(backslashes * 2 + 1));
            output.push(unit);
            backslashes = 0;
        } else {
            output.extend(std::iter::repeat(b'\\' as u16).take(backslashes));
            output.push(unit);
            backslashes = 0;
        }
    }
    output.extend(std::iter::repeat(b'\\' as u16).take(backslashes * 2));
    output.push(b'"' as u16);
    output
}

fn wide_nul(value: &std::ffi::OsStr) -> anyhow::Result<Vec<u16>> {
    let mut output: Vec<u16> = value.encode_wide().collect();
    if output.contains(&0) {
        anyhow::bail!("Windows 路径包含无效 NUL 字符")
    }
    output.push(0);
    Ok(output)
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

fn assign_process_handle_to_job(job: HANDLE, process: HANDLE) -> anyhow::Result<()> {
    // SAFETY: the suspended child process handle is valid until its wrapper drops.
    if unsafe { AssignProcessToJobObject(job, process) } == 0 {
        anyhow::bail!("无法将 MCP 进程加入进程守护对象");
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
    use super::{
        frontend_api_base, is_valid_std_handle, mcp_environment, mcp_start_failure_message,
        parse_start_mode_from, McpStartupStage, PortablePaths, StartMode, MCP_STDIO_ARGUMENT,
    };
    use std::ffi::OsString;
    use std::{
        env, fs,
        path::Path,
        time::{SystemTime, UNIX_EPOCH},
    };

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

    #[test]
    fn startup_modes_are_exact_and_mutually_exclusive() {
        assert!(matches!(parse_start_mode_from(vec![]), Ok(StartMode::Gui)));
        assert!(matches!(
            parse_start_mode_from(vec![OsString::from(MCP_STDIO_ARGUMENT)]),
            Ok(StartMode::McpStdio)
        ));
        assert!(
            parse_start_mode_from(vec![OsString::from("--mcp-stdio"), OsString::from("x")])
                .is_err()
        );
        assert!(parse_start_mode_from(vec![OsString::from("--unknown")]).is_err());
        assert!(parse_start_mode_from(vec![
            OsString::from("--mcp-stdio"),
            OsString::from("--portable-update-runner")
        ])
        .is_err());
    }

    #[test]
    fn mcp_startup_error_is_a_fixed_safe_message() {
        let sentinel = r"C:\secret\api-key-and-db-path.sqlite";
        let message = mcp_start_failure_message(McpStartupStage::ProcessCreate);
        assert!(!message.contains(sentinel));
        assert_eq!(message, "MCP_START_FAILED(PROCESS_CREATE)");
    }

    #[test]
    fn all_mcp_startup_stage_messages_are_fixed_codes() {
        let stages = [
            McpStartupStage::Discover,
            McpStartupStage::CoordinationLock,
            McpStartupStage::Session,
            McpStartupStage::DatabaseValidate,
            McpStartupStage::Materialize,
            McpStartupStage::Environment,
            McpStartupStage::JobCreate,
            McpStartupStage::ProcessCreate,
            McpStartupStage::JobAssign,
            McpStartupStage::Resume,
            McpStartupStage::Wait,
            McpStartupStage::ExitCode,
        ];
        for stage in stages {
            let message = mcp_start_failure_message(stage);
            assert!(message.starts_with("MCP_START_FAILED("));
            assert!(message.ends_with(')'));
            assert!(!message.contains('\\'));
            assert!(!message.contains('/'));
        }
    }

    #[test]
    fn stdio_validation_rejects_only_null_and_invalid_handles() {
        assert!(!is_valid_std_handle(std::ptr::null_mut()));
        assert!(!is_valid_std_handle(
            windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE
        ));
        assert!(is_valid_std_handle(
            1_usize as windows_sys::Win32::Foundation::HANDLE
        ));
    }

    #[test]
    fn mcp_environment_uses_windows_api_when_caller_system_variables_are_missing() {
        let root = env::temp_dir().join(format!(
            "bili-opinion-mcp-env-test-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let paths = PortablePaths::from_install_root(root.clone()).unwrap();
        let session = paths.create_mcp_session().unwrap();
        let names = ["SystemRoot", "WINDIR", "ComSpec"];
        let previous: Vec<(&str, Option<OsString>)> = names
            .iter()
            .map(|name| (*name, env::var_os(name)))
            .collect();
        for name in names {
            env::remove_var(name);
        }
        let result = mcp_environment(&session, Path::new(r"C:\allowed\backup.sqlite"));
        for (name, value) in previous {
            match value {
                Some(value) => env::set_var(name, value),
                None => env::remove_var(name),
            }
        }
        let block = result.unwrap();
        let text = String::from_utf16(&block).unwrap();
        assert!(text.contains("SystemRoot="));
        assert!(text.contains("WINDIR="));
        assert!(text.contains("ComSpec="));
        assert!(!text.contains("HTTP_PROXY="));
        assert!(!text.contains("caller-secret-sentinel"));
        drop(session);
        fs::remove_dir_all(root).unwrap();
    }
}
