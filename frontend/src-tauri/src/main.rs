#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod portable;
#[path = "bin/updater.rs"]
mod updater;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use portable::{
    sha256_file, validate_mcp_database_path, version_is_newer, BackendHandshake, EmbeddedComponent,
    PortableManifest, PortablePaths, DEFAULT_MANIFEST_URL, UPDATE_PUBLIC_KEY_B64,
};
use rand::RngCore;
use reqwest::{blocking::Client, redirect::Policy, Certificate};
use rfd::FileDialog;
use serde::Serialize;
use std::{
    env,
    error::Error as StdError,
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{Read, Write},
    os::windows::{
        ffi::{OsStrExt, OsStringExt},
        io::AsRawHandle,
    },
    path::{Path, PathBuf},
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
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
static UPDATE_LOG_LOCK: Mutex<()> = Mutex::new(());

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

#[derive(Debug)]
struct UpdateFailure {
    category: &'static str,
    user_message: String,
    http_status: Option<u16>,
}

impl UpdateFailure {
    fn new(category: &'static str, user_message: impl Into<String>) -> Self {
        Self {
            category,
            user_message: user_message.into(),
            http_status: None,
        }
    }

    fn with_status(mut self, status: u16) -> Self {
        self.http_status = Some(status);
        self
    }

    fn background_join() -> Self {
        Self::new("internal", "更新后台任务异常结束，请重试或重启应用")
    }
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
        has_active_tasks(&self.api_base, &self.token)
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
async fn save_export_file(
    suggested_name: String,
    extension: String,
    content_base64: String,
) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (extension, filter_name) = export_file_type(&extension)?;
        let content = STANDARD
            .decode(content_base64)
            .map_err(|_| "导出内容无效，请重试".to_owned())?;
        let suggested_name = export_suggested_file_name(&suggested_name, extension);
        let Some(path) = FileDialog::new()
            .add_filter(filter_name, &[extension])
            .set_file_name(&suggested_name)
            .save_file()
        else {
            return Ok(None);
        };
        let path = if path
            .extension()
            .is_some_and(|current| current.eq_ignore_ascii_case(extension))
        {
            path
        } else {
            path.with_extension(extension)
        };
        fs::write(&path, content)
            .map_err(|_| "无法写入所选位置，请检查文件权限或是否被占用".to_owned())?;
        Ok(Some(path.to_string_lossy().into_owned()))
    })
    .await
    .map_err(|_| "保存任务异常结束，请重试".to_owned())?
}

fn export_file_type(value: &str) -> Result<(&'static str, &'static str), String> {
    match value.to_ascii_lowercase().as_str() {
        "csv" => Ok(("csv", "CSV 文件")),
        "png" => Ok(("png", "PNG 图片")),
        _ => Err("不支持的导出文件类型".to_owned()),
    }
}

fn export_suggested_file_name(value: &str, extension: &str) -> String {
    let name = Path::new(value)
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.trim().is_empty())
        .unwrap_or("bili-export");
    if name
        .rsplit_once('.')
        .is_some_and(|(_, current)| current.eq_ignore_ascii_case(extension))
    {
        name.to_owned()
    } else {
        format!("{name}.{extension}")
    }
}

#[tauri::command]
async fn check_for_updates(app: AppHandle) -> Result<UpdateCheck, String> {
    let (app_version, data_dir) = {
        let state = app.state::<AppState>();
        (state.app_version.clone(), state.paths.data_dir.clone())
    };
    let result = run_update_task(move || {
        logged_update_task(&data_dir, "check", || {
            let manifest = fetch_manifest(UPDATE_TIMEOUT)?;
            Ok(UpdateCheck {
                enabled: true,
                available: version_is_newer(&manifest.version, &app_version),
                version: Some(manifest.version),
                notes_url: Some(manifest.notes_url),
                message: None,
            })
        })
    })
    .await;
    match result {
        Ok(update) => Ok(update),
        Err(error) => Ok(UpdateCheck {
            enabled: false,
            available: false,
            version: None,
            notes_url: None,
            message: Some(error.user_message),
        }),
    }
}

#[tauri::command]
async fn download_update(app: AppHandle) -> Result<DownloadedUpdate, String> {
    let (paths, app_version) = {
        let state = app.state::<AppState>();
        (state.paths.clone(), state.app_version.clone())
    };
    let data_dir = paths.data_dir.clone();
    let downloaded = run_update_task(move || {
        logged_update_task(&data_dir, "download", || {
            download_update_blocking(&paths, &app_version)
        })
    })
    .await
    .map_err(|error| error.user_message)?;
    let state = app.state::<AppState>();
    *state
        .downloaded_update
        .lock()
        .map_err(|_| "更新状态锁定失败")? = Some(downloaded.clone());
    Ok(downloaded)
}

#[tauri::command]
async fn install_update(app: AppHandle) -> Result<(), String> {
    let (paths, api_base, token, downloaded) = {
        let state = app.state::<AppState>();
        let downloaded = state
            .downloaded_update
            .lock()
            .map_err(|_| "更新状态锁定失败")?
            .clone()
            .ok_or("请先完整下载并校验更新包")?;
        (
            state.paths.clone(),
            state.api_base.clone(),
            state.token.clone(),
            downloaded,
        )
    };
    let data_dir = paths.data_dir.clone();
    run_update_task(move || {
        logged_update_task(&data_dir, "install", || {
            install_update_blocking(&paths, &api_base, &token, downloaded)
        })
    })
    .await
    .map_err(|error| error.user_message)?;
    app.exit(0);
    Ok(())
}

async fn run_update_task<T, F>(task: F) -> Result<T, UpdateFailure>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, UpdateFailure> + Send + 'static,
{
    tauri::async_runtime::spawn_blocking(task)
        .await
        .map_err(|_| UpdateFailure::background_join())?
}

fn fetch_manifest(timeout: Duration) -> Result<PortableManifest, UpdateFailure> {
    if UPDATE_PUBLIC_KEY_B64.trim().is_empty() {
        return Err(UpdateFailure::new(
            "configuration",
            "当前版本未配置在线更新，请从项目发布页手动下载",
        ));
    }
    let manifest_url = std::env::var("BILI_PORTABLE_UPDATE_MANIFEST_URL")
        .unwrap_or_else(|_| DEFAULT_MANIFEST_URL.to_owned());
    fetch_manifest_from_url(&manifest_url, UPDATE_PUBLIC_KEY_B64, timeout)
}

fn fetch_manifest_from_url(
    manifest_url: &str,
    public_key_b64: &str,
    timeout: Duration,
) -> Result<PortableManifest, UpdateFailure> {
    let client = secure_update_client(timeout)
        .map_err(|_| UpdateFailure::new("internal", "无法初始化更新网络组件，请重启应用后重试"))?;
    let response = client
        .get(manifest_url)
        .send()
        .map_err(|error| classify_request_error(&error, "检查"))?;
    if response.status().is_redirection() {
        return Err(
            UpdateFailure::new("redirect", "更新服务返回了不安全的跳转，已停止更新")
                .with_status(response.status().as_u16()),
        );
    }
    let response = response
        .error_for_status()
        .map_err(|error| classify_request_error(&error, "检查"))?;
    let manifest: PortableManifest = response
        .json()
        .map_err(|error| classify_request_error(&error, "检查"))?;
    manifest
        .verify_signature(public_key_b64)
        .map_err(classify_manifest_error)?;
    Ok(manifest)
}

fn download_update_blocking(
    paths: &PortablePaths,
    app_version: &str,
) -> Result<DownloadedUpdate, UpdateFailure> {
    let manifest = fetch_manifest(UPDATE_TIMEOUT)?;
    if !version_is_newer(&manifest.version, app_version) {
        return Err(UpdateFailure::new("not_available", "当前已是最新版本"));
    }
    if !manifest.asset.name.to_ascii_lowercase().ends_with(".exe") {
        return Err(UpdateFailure::new(
            "manifest",
            "已签名更新清单的程序文件名无效",
        ));
    }
    let final_path = paths.update_cache_dir.join("BiliOpinionMonitor.exe");
    let part_path = paths.update_cache_dir.join("BiliOpinionMonitor.exe.part");
    let client = secure_update_client(UPDATE_TIMEOUT)
        .map_err(|_| UpdateFailure::new("internal", "无法初始化更新网络组件，请重启应用后重试"))?;
    let response = client
        .get(&manifest.asset.url)
        .send()
        .map_err(|error| classify_request_error(&error, "下载"))?;
    if response.status().is_redirection() {
        return Err(
            UpdateFailure::new("redirect", "更新下载返回了不安全的跳转，已停止更新")
                .with_status(response.status().as_u16()),
        );
    }
    let mut response = response
        .error_for_status()
        .map_err(|error| classify_request_error(&error, "下载"))?;
    if response
        .content_length()
        .is_some_and(|length| length != manifest.asset.size)
    {
        return Err(UpdateFailure::new(
            "asset_validation",
            "更新包大小与已签名清单不一致",
        ));
    }
    let mut output = fs::File::create(&part_path).map_err(|_| {
        UpdateFailure::new(
            "storage",
            "无法写入更新缓存，请检查程序目录权限或安全软件设置",
        )
    })?;
    let mut total = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = match response.read(&mut buffer) {
            Ok(count) => count,
            Err(error) => {
                let _ = fs::remove_file(&part_path);
                let message = if error.kind() == std::io::ErrorKind::TimedOut {
                    "读取更新包超时，请检查网络或代理后重试"
                } else {
                    "读取更新包时网络连接中断，请重试"
                };
                return Err(UpdateFailure::new("network_read", message));
            }
        };
        if count == 0 {
            break;
        }
        total += count as u64;
        if total > manifest.asset.size {
            let _ = fs::remove_file(&part_path);
            return Err(UpdateFailure::new(
                "asset_validation",
                "更新包超过已签名的文件大小",
            ));
        }
        if output.write_all(&buffer[..count]).is_err() {
            let _ = fs::remove_file(&part_path);
            return Err(UpdateFailure::new(
                "storage",
                "写入更新缓存失败，请检查磁盘空间或目录权限",
            ));
        }
    }
    output
        .flush()
        .map_err(|_| UpdateFailure::new("storage", "写入更新缓存失败，请检查磁盘空间或目录权限"))?;
    let digest = sha256_file(&part_path)
        .map_err(|_| UpdateFailure::new("asset_validation", "无法校验更新包，文件已删除"))?;
    if total != manifest.asset.size || digest != manifest.asset.sha256 {
        let _ = fs::remove_file(&part_path);
        return Err(UpdateFailure::new(
            "asset_validation",
            "更新包校验失败，文件已删除",
        ));
    }
    if validate_update_executable(&part_path).is_err() {
        let _ = fs::remove_file(&part_path);
        return Err(UpdateFailure::new(
            "asset_validation",
            "更新文件不是有效的 Windows 程序，已删除",
        ));
    }
    let _ = fs::remove_file(&final_path);
    fs::rename(&part_path, &final_path).map_err(|_| {
        UpdateFailure::new(
            "storage",
            "无法保存已校验的更新包，请检查目录权限或安全软件设置",
        )
    })?;
    Ok(DownloadedUpdate {
        version: manifest.version,
        executable_path: final_path,
        sha256: manifest.asset.sha256,
    })
}

fn install_update_blocking(
    paths: &PortablePaths,
    api_base: &str,
    token: &str,
    downloaded: DownloadedUpdate,
) -> Result<(), UpdateFailure> {
    if has_active_tasks(api_base, token) {
        return Err(UpdateFailure::new(
            "active_tasks",
            "当前仍有抓取或分析任务，完成或停止后再安装更新",
        ));
    }
    let installed_updater = paths
        .update_runner_dir
        .join("BiliOpinionMonitor-update-runner.exe");
    let current_executable = std::env::current_exe()
        .map_err(|_| UpdateFailure::new("storage", "无法定位当前程序，请重启应用后重试"))?;
    fs::copy(&current_executable, &installed_updater).map_err(|_| {
        UpdateFailure::new(
            "storage",
            "无法准备更新器，请检查程序目录权限或安全软件设置",
        )
    })?;
    let ready_event = format!("Local\\BiliOpinionUpdateReady-{}", random_hex(16));
    let ready_event_wide = wide_nul(std::ffi::OsStr::new(&ready_event))
        .map_err(|_| UpdateFailure::new("install_coordination", "无法建立更新协调信号"))?;
    // SAFETY: the event name is NUL-terminated and uses an unguessable suffix.
    let ready_handle = unsafe { CreateEventW(std::ptr::null(), 1, 0, ready_event_wide.as_ptr()) };
    if ready_handle.is_null() {
        return Err(UpdateFailure::new(
            "install_coordination",
            "无法建立更新协调信号",
        ));
    }
    Command::new(installed_updater)
        .arg(updater::RUNNER_ARGUMENT)
        .arg("--staged-exe")
        .arg(downloaded.executable_path)
        .arg("--target-exe")
        .arg(&current_executable)
        .arg("--data-dir")
        .arg(&paths.data_dir)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .arg("--expected-version")
        .arg(downloaded.version)
        .arg("--expected-sha256")
        .arg(downloaded.sha256)
        .arg("--ready-event")
        .arg(&ready_event)
        .spawn()
        .map_err(|_| {
            // SAFETY: this branch still owns the event handle.
            unsafe { CloseHandle(ready_handle) };
            UpdateFailure::new("install_coordination", "无法启动更新器，请检查安全软件设置")
        })?;
    // The runner signals only after it holds the exclusive lock. Keeping GUI
    // alive until then removes the check/exit/acquire race with a new MCP run.
    let ready = unsafe { WaitForSingleObject(ready_handle, UPDATE_READY_WAIT.as_millis() as u32) };
    unsafe { CloseHandle(ready_handle) };
    if ready != WAIT_OBJECT_0 {
        return Err(UpdateFailure::new(
            "install_coordination",
            "更新器未能取得安装协调锁；可能仍有 MCP 会话正在运行",
        ));
    }
    Ok(())
}

fn has_active_tasks(api_base: &str, token: &str) -> bool {
    let client = Client::builder().timeout(Duration::from_secs(2)).build();
    let Ok(client) = client else { return true };
    client
        .get(format!("{api_base}/api/runtime/activity"))
        .header(LOCAL_TOKEN_HEADER, token)
        .send()
        .ok()
        .and_then(|response| response.json::<serde_json::Value>().ok())
        .and_then(|body| body.get("active").and_then(|value| value.as_bool()))
        .unwrap_or(true)
}

fn classify_request_error(error: &reqwest::Error, action: &str) -> UpdateFailure {
    let source_has = |needle: &str| {
        let mut current: Option<&(dyn StdError + 'static)> = Some(error);
        while let Some(item) = current {
            if item.to_string().to_ascii_lowercase().contains(needle) {
                return true;
            }
            current = item.source();
        }
        false
    };
    if source_has("certificate") || source_has("tls") || source_has("ssl") {
        return UpdateFailure::new(
            "tls",
            "无法验证更新服务的 HTTPS 证书，请检查系统时间或网络代理",
        );
    }
    if error.is_timeout() {
        return UpdateFailure::new(
            "timeout",
            format!("{action}更新服务超时，请检查网络或代理后重试"),
        );
    }
    if error.is_redirect() {
        return UpdateFailure::new("redirect", "更新服务跳转异常，已停止更新");
    }
    if error.is_connect() {
        return UpdateFailure::new("connection", "无法连接更新服务，请检查网络或代理设置");
    }
    if let Some(status) = error.status() {
        return UpdateFailure::new(
            "http_status",
            format!(
                "更新服务返回异常状态（HTTP {}），请稍后重试",
                status.as_u16()
            ),
        )
        .with_status(status.as_u16());
    }
    if error.is_decode() {
        return UpdateFailure::new("manifest", "更新清单格式无效，已停止更新");
    }
    UpdateFailure::new("network", format!("{action}更新时发生网络错误，请稍后重试"))
}

fn classify_manifest_error(error: anyhow::Error) -> UpdateFailure {
    let summary = error.to_string();
    if summary.contains("公钥") {
        return UpdateFailure::new(
            "configuration",
            "当前版本的更新验证配置无效，请从项目发布页手动下载",
        );
    }
    if summary.contains("签名") {
        return UpdateFailure::new("signature", "更新清单签名校验失败，已停止更新");
    }
    if summary.contains("HTTPS") {
        return UpdateFailure::new("manifest_security", "更新清单包含非 HTTPS 地址，已停止更新");
    }
    UpdateFailure::new("manifest", "更新清单内容无效，已停止更新")
}

fn logged_update_task<T, F>(
    data_dir: &Path,
    task: &'static str,
    action: F,
) -> Result<T, UpdateFailure>
where
    F: FnOnce() -> Result<T, UpdateFailure>,
{
    let started_at = unix_timestamp_ms();
    let started = Instant::now();
    let result = action();
    write_update_log(data_dir, task, started_at, started.elapsed(), &result);
    result
}

fn write_update_log<T>(
    data_dir: &Path,
    task: &'static str,
    started_at: u128,
    duration: Duration,
    result: &Result<T, UpdateFailure>,
) {
    let (result_name, category, status, summary) = match result {
        Ok(_) => ("success", None, None, None),
        Err(error) => (
            "failure",
            Some(error.category),
            error.http_status,
            Some(error.user_message.as_str()),
        ),
    };
    let record = serde_json::json!({
        "timestamp": unix_timestamp_ms(),
        "task": task,
        "started_at_unix_ms": started_at,
        "finished_at_unix_ms": unix_timestamp_ms(),
        "duration_ms": duration.as_millis(),
        "result": result_name,
        "category": category,
        "http_status": status,
        "summary": summary,
    });
    let Ok(_guard) = UPDATE_LOG_LOCK.lock() else {
        return;
    };
    let logs_dir = data_dir.join("logs");
    if fs::create_dir_all(&logs_dir).is_err() {
        return;
    }
    let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs_dir.join("update.log"))
    else {
        return;
    };
    if serde_json::to_writer(&mut file, &record).is_ok() {
        let _ = file.write_all(b"\n");
    }
}

fn unix_timestamp_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_millis())
}

/*
 * The three commands above intentionally hand every blocking network, file,
 * hash, and Win32 wait operation to Tauri's blocking executor. Keep the
 * command bodies async even when changing their return contract.
 */

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
    if portable_update_self_test_requested() {
        if let Err(error) = run_portable_update_self_test() {
            eprintln!("更新测试失败：{}", error.user_message);
            std::process::exit(1);
        }
        return;
    }
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
            let state = AppState::start(paths.clone(), update_current_version())?;
            app.manage(state);
            build_main_window(app, &paths)?;
            build_tray(app)?;
            write_healthy_marker(app, &paths)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            runtime_config,
            save_export_file,
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

/// The release-check script compiles this branch only into its throwaway test
/// executable.  Production packages neither recognize the argument nor carry
/// the test CA, so this cannot become an alternate update entry point.
fn portable_update_self_test_requested() -> bool {
    option_env!("BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64").is_some()
        && env::args_os()
            .skip(1)
            .eq([OsString::from("--portable-update-self-test")])
}

fn run_portable_update_self_test() -> Result<(), UpdateFailure> {
    let paths = PortablePaths::discover()
        .map_err(|_| UpdateFailure::new("storage", "无法初始化测试程序目录"))?;
    let state = AppState::start(paths.clone(), update_current_version())
        .map_err(|_| UpdateFailure::new("internal", "无法启动测试后端"))?;
    let data_dir = paths.data_dir.clone();
    let downloaded = logged_update_task(&data_dir, "download", || {
        download_update_blocking(&paths, &state.app_version)
    })?;
    let install = logged_update_task(&data_dir, "install", || {
        install_update_blocking(&paths, &state.api_base, &state.token, downloaded)
    });
    state.stop_child();
    install
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
fn secure_update_client(timeout: Duration) -> anyhow::Result<Client> {
    let mut builder = Client::builder()
        .redirect(Policy::custom(|attempt| {
            if attempt.url().scheme() == "https" && attempt.previous().len() < 5 {
                attempt.follow()
            } else {
                attempt.stop()
            }
        }))
        .connect_timeout(Duration::from_secs(10))
        .timeout(timeout);
    if let Some(encoded_certificate) = option_env!("BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64") {
        let certificate = STANDARD
            .decode(encoded_certificate)
            .map_err(|_| anyhow::anyhow!("测试更新证书配置无效"))?;
        builder = builder.add_root_certificate(Certificate::from_pem(&certificate)?);
    }
    Ok(builder.build()?)
}

fn update_current_version() -> String {
    option_env!("BILI_PORTABLE_UPDATE_TEST_CURRENT_VERSION")
        .unwrap_or(env!("CARGO_PKG_VERSION"))
        .to_owned()
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
        classify_manifest_error, export_file_type, export_suggested_file_name,
        fetch_manifest_from_url, frontend_api_base, is_valid_std_handle, logged_update_task,
        mcp_environment, mcp_start_failure_message, parse_start_mode_from, McpStartupStage,
        PortablePaths, StartMode, UpdateFailure, MCP_STDIO_ARGUMENT,
    };
    use std::ffi::OsString;
    use std::{
        env, fs,
        io::{Read, Write},
        net::TcpListener,
        path::Path,
        thread,
        time::{Duration, SystemTime, UNIX_EPOCH},
    };

    fn serve_once(response: &'static str, delay: Duration) -> (String, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request);
            thread::sleep(delay);
            let _ = stream.write_all(response.as_bytes());
        });
        (format!("http://{address}/latest-portable.json"), server)
    }

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
    fn update_commands_keep_blocking_work_off_the_tauri_command_thread() {
        let source = include_str!("main.rs");
        let production = source.split("#[cfg(test)]").next().unwrap();
        for signature in [
            "async fn check_for_updates(app: AppHandle)",
            "async fn download_update(app: AppHandle)",
            "async fn install_update(app: AppHandle)",
        ] {
            assert!(
                production.contains(signature),
                "missing async command: {signature}"
            );
        }
        assert!(production.contains("tauri::async_runtime::spawn_blocking"));
    }

    #[test]
    fn export_save_command_keeps_the_native_dialog_and_write_off_the_tauri_thread() {
        let source = include_str!("main.rs");
        let production = source.split("#[cfg(test)]").next().unwrap();
        assert!(production.contains("async fn save_export_file"));
        assert!(production.contains("FileDialog::new()"));
        assert!(production.contains("tauri::async_runtime::spawn_blocking(move ||"));
        assert!(production.contains(".decode(content_base64)"));
        assert!(production.contains("fs::write(&path, content)"));
    }

    #[test]
    fn export_file_type_and_suggested_name_are_restricted_to_safe_formats() {
        assert_eq!(export_file_type("PNG").unwrap(), ("png", "PNG 图片"));
        assert!(export_file_type("exe").is_err());
        assert_eq!(
            export_suggested_file_name("C:\\临时\\评论", "csv"),
            "评论.csv"
        );
        assert_eq!(
            export_suggested_file_name("图表.jpg", "png"),
            "图表.jpg.png"
        );
    }

    #[test]
    fn update_test_trust_is_compile_time_only() {
        let source = include_str!("main.rs");
        let production = source.split("#[cfg(test)]").next().unwrap();
        assert!(production.contains("option_env!(\"BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64\")"));
        assert!(production.contains("option_env!(\"BILI_PORTABLE_UPDATE_TEST_CURRENT_VERSION\")"));
        assert!(!production.contains("danger_accept_invalid_certs"));
    }

    #[test]
    fn update_manifest_rejects_unsafe_redirects_and_service_failures() {
        let (redirect_url, redirect_server) = serve_once(
            "HTTP/1.1 302 Found\r\nLocation: http://invalid.example/manifest\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            Duration::ZERO,
        );
        let redirect =
            fetch_manifest_from_url(&redirect_url, "unused", Duration::from_secs(1)).unwrap_err();
        redirect_server.join().unwrap();
        assert_eq!(redirect.category, "redirect");
        assert_eq!(redirect.http_status, Some(302));

        let (status_url, status_server) = serve_once(
            "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            Duration::ZERO,
        );
        let status =
            fetch_manifest_from_url(&status_url, "unused", Duration::from_secs(1)).unwrap_err();
        status_server.join().unwrap();
        assert_eq!(status.category, "http_status");
        assert_eq!(status.http_status, Some(503));
        assert!(!status.user_message.contains(&status_url));
    }

    #[test]
    fn update_manifest_timeout_and_signature_errors_are_safe_for_users() {
        let (slow_url, slow_server) = serve_once(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
            Duration::from_millis(120),
        );
        let timeout =
            fetch_manifest_from_url(&slow_url, "unused", Duration::from_millis(20)).unwrap_err();
        slow_server.join().unwrap();
        assert_eq!(timeout.category, "timeout");
        assert!(!timeout.user_message.contains(&slow_url));

        let failure = classify_manifest_error(anyhow::anyhow!("更新清单签名校验失败: secret"));
        assert_eq!(failure.category, "signature");
        assert_eq!(failure.user_message, "更新清单签名校验失败，已停止更新");
    }

    #[test]
    fn update_diagnostics_are_structured_and_contain_only_safe_summary() {
        let root = env::temp_dir().join(format!(
            "bili-opinion-update-log-test-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let result: Result<(), UpdateFailure> = logged_update_task(&root, "check", || {
            Err(UpdateFailure::new(
                "connection",
                "无法连接更新服务，请检查网络或代理设置",
            ))
        });
        assert!(result.is_err());
        let log = fs::read_to_string(root.join("logs").join("update.log")).unwrap();
        let record: serde_json::Value = serde_json::from_str(log.trim()).unwrap();
        assert_eq!(record["task"], "check");
        assert_eq!(record["category"], "connection");
        assert!(record["duration_ms"].is_number());
        assert!(!log.contains("api-key-and-cookie-sentinel"));
        fs::remove_dir_all(root).unwrap();
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
