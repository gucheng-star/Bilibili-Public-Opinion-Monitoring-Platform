//! Portable-install paths, update manifest validation, and ZIP safety checks.
//!
//! This module deliberately contains no Tauri command handling so its critical
//! update validation rules can be unit-tested without a WebView or network.

use base64::{engine::general_purpose::STANDARD, Engine as _};
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsStr,
    fs::{self, OpenOptions},
    io::{Read, Write},
    os::windows::ffi::OsStrExt,
    path::{Component, Path, PathBuf, Prefix},
    process,
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::{Duration, Instant},
};
use url::Url;
use windows_sys::Win32::Storage::FileSystem::{
    GetDriveTypeW, GetFileAttributesW, LockFileEx, MoveFileExW, UnlockFileEx,
    FILE_ATTRIBUTE_REPARSE_POINT, FILE_SHARE_READ, FILE_SHARE_WRITE, INVALID_FILE_ATTRIBUTES,
    LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY, MOVEFILE_REPLACE_EXISTING,
    MOVEFILE_WRITE_THROUGH,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE},
    Storage::FileSystem::{CreateFileW, OPEN_ALWAYS},
    System::WindowsProgramming::{DRIVE_FIXED, DRIVE_REMOVABLE},
    System::IO::OVERLAPPED,
};

pub const DEFAULT_MANIFEST_URL: &str =
    "https://github.com/gucheng-star/Bilibili-Public-Opinion-Monitoring-Platform/releases/latest/download/latest-portable.json";

/// Set at compile time by the release workflow. It is intentionally public;
/// the corresponding Ed25519 private key must never be put in this repository.
pub const UPDATE_PUBLIC_KEY_B64: &str = match option_env!("BILI_PORTABLE_UPDATE_PUBLIC_KEY") {
    Some(value) => value,
    None => "",
};

const EMBEDDED_BACKEND_NAME: &str = "BiliOpinionBackend.exe";
const EMBEDDED_BACKEND_MANIFEST: &str = "backend-release.json";
const EMBEDDED_MCP_NAME: &str = "BiliOpinionAgentMcp.exe";
const EMBEDDED_MCP_MANIFEST: &str = "agent-mcp-release.json";
const MCP_SESSION_MARKER: &str = ".bili-mcp-session.json";
const MCP_SESSION_LIFECYCLE_LOCK: &str = ".bili-mcp-session.lock";
const MCP_SESSION_MAX_AGE: std::time::Duration = std::time::Duration::from_secs(60 * 60);
const COMPONENT_RELEASE_LOCK_WAIT: Duration = Duration::from_secs(20);
const COMPONENT_RELEASE_LOCK_RETRY: Duration = Duration::from_millis(50);
static TEMP_FILE_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone, Copy)]
pub enum EmbeddedComponent {
    Backend,
    AgentMcp,
}

impl EmbeddedComponent {
    fn executable_name(self) -> &'static str {
        match self {
            Self::Backend => EMBEDDED_BACKEND_NAME,
            Self::AgentMcp => EMBEDDED_MCP_NAME,
        }
    }

    fn manifest_name(self) -> &'static str {
        match self {
            Self::Backend => EMBEDDED_BACKEND_MANIFEST,
            Self::AgentMcp => EMBEDDED_MCP_MANIFEST,
        }
    }
}

#[derive(Debug, Clone)]
pub struct PortablePaths {
    pub data_dir: PathBuf,
    pub webview_dir: PathBuf,
    pub update_cache_dir: PathBuf,
    pub update_runner_dir: PathBuf,
    pub runtime_dir: PathBuf,
    pub backend_temp_dir: PathBuf,
    pub mcp_temp_root: PathBuf,
    pub coordination_lock_path: PathBuf,
    pub component_release_lock_path: PathBuf,
    pub handshake_path: PathBuf,
}

impl PortablePaths {
    pub fn discover() -> anyhow::Result<Self> {
        let executable = std::env::current_exe()?;
        let install_root = executable
            .parent()
            .ok_or_else(|| anyhow::anyhow!("无法确定便携程序目录"))?
            .to_path_buf();
        Self::from_install_root(install_root)
    }

    pub fn from_install_root(application_directory: PathBuf) -> anyhow::Result<Self> {
        let data_dir = application_directory.join("data");
        let logs_dir = data_dir.join("logs");
        let webview_dir = data_dir.join("webview");
        let update_cache_dir = data_dir.join("update-cache");
        let update_runner_dir = data_dir.join("update-runner");
        let runtime_dir = data_dir.join("runtime");
        let backend_temp_dir = runtime_dir.join("tmp");
        let mcp_temp_root = runtime_dir.join("mcp-tmp");
        for directory in [
            &data_dir,
            &logs_dir,
            &webview_dir,
            &update_cache_dir,
            &update_runner_dir,
            &runtime_dir,
            &backend_temp_dir,
            &mcp_temp_root,
        ] {
            fs::create_dir_all(directory)?;
        }
        ensure_real_directory(&runtime_dir)?;
        ensure_real_directory(&backend_temp_dir)?;
        ensure_real_directory(&mcp_temp_root)?;
        let coordination_lock_path = runtime_dir.join("install-coordination.lock");
        let component_release_lock_path = runtime_dir.join("component-release.lock");

        Ok(Self {
            handshake_path: data_dir.join("backend-handshake.json"),
            data_dir,
            webview_dir,
            update_cache_dir,
            update_runner_dir,
            runtime_dir,
            backend_temp_dir,
            mcp_temp_root,
            coordination_lock_path,
            component_release_lock_path,
        })
    }

    /// Releases the backend embedded in the desktop EXE into a durable runtime
    /// location. A matching version and SHA-256 is reused; corrupt or stale
    /// files are atomically replaced before they can be launched.
    pub fn materialize_embedded_backend(
        &self,
        embedded_bytes: &[u8],
        app_version: &str,
    ) -> anyhow::Result<PathBuf> {
        self.materialize_embedded_component(EmbeddedComponent::Backend, embedded_bytes, app_version)
    }

    /// Releases one of the allowlisted EXE resources.  Component names and
    /// manifests are fixed by this enum so a caller cannot select an arbitrary
    /// destination under the portable runtime directory.
    pub fn materialize_embedded_component(
        &self,
        component: EmbeddedComponent,
        embedded_bytes: &[u8],
        app_version: &str,
    ) -> anyhow::Result<PathBuf> {
        // This lock covers both the current-manifest read and every atomic
        // replacement. It is intentionally separate from MCP session/update
        // coordination so concurrent GUI/MCP startup cannot race resources.
        let _release_lock = self.acquire_component_release_lock()?;
        self.materialize_embedded_component_locked(component, embedded_bytes, app_version)
    }

    fn materialize_embedded_component_locked(
        &self,
        component: EmbeddedComponent,
        embedded_bytes: &[u8],
        app_version: &str,
    ) -> anyhow::Result<PathBuf> {
        let executable = self.runtime_dir.join(component.executable_name());
        let manifest_path = self.runtime_dir.join(component.manifest_name());
        let expected_sha256 = sha256_bytes(embedded_bytes);

        if embedded_backend_is_current(&executable, &manifest_path, app_version, &expected_sha256)?
        {
            return Ok(executable);
        }

        reject_symlink(&executable)?;
        reject_symlink(&manifest_path)?;
        atomic_write(&executable, embedded_bytes)?;
        let manifest = EmbeddedComponentManifest {
            schema: 1,
            app_version: app_version.to_owned(),
            sha256: expected_sha256,
        };
        atomic_write(&manifest_path, &serde_json::to_vec(&manifest)?)?;
        Ok(executable)
    }

    pub fn create_mcp_session(&self) -> anyhow::Result<McpSession> {
        ensure_real_directory(&self.mcp_temp_root)?;
        for _ in 0..16 {
            let name = format!(
                "mcp-session-{}-{}",
                random_hex(16),
                TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
            );
            let path = self.mcp_temp_root.join(name);
            match fs::create_dir(&path) {
                Ok(()) => {
                    ensure_real_directory(&path)?;
                    let marker = serde_json::json!({ "schema": 1, "owner": "bili-opinion-mcp" });
                    if let Err(error) = atomic_write(
                        &path.join(MCP_SESSION_MARKER),
                        &serde_json::to_vec(&marker)?,
                    ) {
                        let _ = fs::remove_dir(&path);
                        return Err(error);
                    }
                    let lifecycle_lock = match SessionLifecycleLock::acquire_shared(
                        &path.join(MCP_SESSION_LIFECYCLE_LOCK),
                    ) {
                        Ok(lock) => lock,
                        Err(error) => {
                            let _ = remove_real_directory_tree(&path);
                            return Err(error);
                        }
                    };
                    return Ok(McpSession {
                        path,
                        lifecycle_lock: Some(lifecycle_lock),
                    });
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error.into()),
            }
        }
        anyhow::bail!("无法创建 MCP 会话临时目录")
    }

    pub fn clear_abandoned_mcp_sessions(&self) -> anyhow::Result<()> {
        self.clear_abandoned_mcp_sessions_at(std::time::SystemTime::now())
    }

    fn clear_abandoned_mcp_sessions_at(&self, now: std::time::SystemTime) -> anyhow::Result<()> {
        ensure_real_directory(&self.mcp_temp_root)?;
        for entry in fs::read_dir(&self.mcp_temp_root)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            if !name.starts_with("mcp-session-") {
                continue;
            }
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path)?;
            if is_reparse_point(&path)? || !metadata.is_dir() {
                anyhow::bail!("MCP 临时根包含异常目录，已拒绝清理")
            }
            if now.duration_since(metadata.modified()?).unwrap_or_default() < MCP_SESSION_MAX_AGE {
                continue;
            }
            let marker = path.join(MCP_SESSION_MARKER);
            let owned = fs::read(&marker)
                .ok()
                .and_then(|value| serde_json::from_slice::<serde_json::Value>(&value).ok())
                .is_some_and(|value| value["schema"] == 1 && value["owner"] == "bili-opinion-mcp");
            if owned {
                // A live MCP parent holds a shared byte-range lock for its
                // entire session. Only an immediately available exclusive lock
                // proves this old directory is not backing a running _MEI.
                match SessionLifecycleLock::try_acquire_exclusive(
                    &path.join(MCP_SESSION_LIFECYCLE_LOCK),
                )? {
                    Some(lock) => {
                        drop(lock);
                        remove_real_directory_tree(&path)?;
                    }
                    None => continue,
                }
            }
        }
        Ok(())
    }

    pub fn acquire_mcp_lock(&self) -> anyhow::Result<InstallCoordinationLock> {
        InstallCoordinationLock::acquire(&self.coordination_lock_path, false)
    }

    pub fn acquire_update_lock(&self) -> anyhow::Result<InstallCoordinationLock> {
        InstallCoordinationLock::acquire(&self.coordination_lock_path, true)
    }

    pub fn acquire_component_release_lock(&self) -> anyhow::Result<ComponentReleaseLock> {
        ComponentReleaseLock::acquire(
            &self.component_release_lock_path,
            COMPONENT_RELEASE_LOCK_WAIT,
        )
    }

    /// PyInstaller onefile uses TEMP/TMP to expand its private `_MEI...`
    /// directory. The shell calls this before launch; normal process exits
    /// remove it, while a later start safely clears abandoned directories.
    pub fn clear_abandoned_backend_temp(&self) -> anyhow::Result<()> {
        ensure_real_directory(&self.backend_temp_dir)?;
        for entry in fs::read_dir(&self.backend_temp_dir)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            if !name.starts_with("_MEI") {
                continue;
            }
            let metadata = fs::symlink_metadata(entry.path())?;
            if is_reparse_point(&entry.path())? {
                anyhow::bail!("后端临时目录包含符号链接，已拒绝清理");
            }
            if metadata.is_dir() {
                fs::remove_dir_all(entry.path())?;
            }
        }
        Ok(())
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct EmbeddedComponentManifest {
    schema: u32,
    app_version: String,
    sha256: String,
}

fn embedded_backend_is_current(
    executable: &Path,
    manifest_path: &Path,
    app_version: &str,
    expected_sha256: &str,
) -> anyhow::Result<bool> {
    let executable_metadata = match fs::symlink_metadata(executable) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    if executable_metadata.file_type().is_symlink() {
        anyhow::bail!("后端运行文件不能是符号链接");
    }
    if !executable_metadata.is_file() {
        return Ok(false);
    }

    let manifest_metadata = match fs::symlink_metadata(manifest_path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    if manifest_metadata.file_type().is_symlink() {
        anyhow::bail!("后端运行清单不能是符号链接");
    }
    if !manifest_metadata.is_file() {
        return Ok(false);
    }
    let manifest: EmbeddedComponentManifest =
        match serde_json::from_slice(&fs::read(manifest_path)?) {
            Ok(manifest) => manifest,
            Err(_) => return Ok(false),
        };
    Ok(manifest.schema == 1
        && manifest.app_version == app_version
        && manifest.sha256 == expected_sha256
        && sha256_file(executable)? == expected_sha256)
}

fn ensure_real_directory(path: &Path) -> anyhow::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || is_reparse_point(path)? || !metadata.is_dir() {
        anyhow::bail!("运行目录必须是实际目录：{}", path.display());
    }
    Ok(())
}

fn reject_symlink(path: &Path) -> anyhow::Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || is_reparse_point(path)? => {
            anyhow::bail!("运行文件不能是符号链接：{}", path.display())
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn is_reparse_point(path: &Path) -> anyhow::Result<bool> {
    let wide = wide_path(path)?;
    // SAFETY: wide_path provides a NUL-terminated UTF-16 path.
    let attributes = unsafe { GetFileAttributesW(wide.as_ptr()) };
    if attributes == INVALID_FILE_ATTRIBUTES {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
}

fn remove_real_directory_tree(path: &Path) -> anyhow::Result<()> {
    if is_reparse_point(path)? || !fs::symlink_metadata(path)?.is_dir() {
        anyhow::bail!("拒绝删除非常规 MCP 临时目录")
    }
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let child = entry.path();
        let metadata = fs::symlink_metadata(&child)?;
        if is_reparse_point(&child)? {
            anyhow::bail!("MCP 临时目录包含 reparse point，已拒绝清理")
        }
        if metadata.is_dir() {
            remove_real_directory_tree(&child)?;
        } else if metadata.is_file() {
            fs::remove_file(&child)?;
        } else {
            anyhow::bail!("MCP 临时目录包含非常规条目，已拒绝清理")
        }
    }
    fs::remove_dir(path)?;
    Ok(())
}

fn random_hex(bytes: usize) -> String {
    use rand::RngCore;
    let mut raw = vec![0_u8; bytes];
    rand::rngs::OsRng.fill_bytes(&mut raw);
    raw.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub struct McpSession {
    path: PathBuf,
    lifecycle_lock: Option<SessionLifecycleLock>,
}

struct SessionLifecycleLock(HANDLE);

impl SessionLifecycleLock {
    fn acquire_shared(path: &Path) -> anyhow::Result<Self> {
        Self::acquire(path, false)?.ok_or_else(|| anyhow::anyhow!("无法建立 MCP 会话生命周期锁"))
    }

    fn try_acquire_exclusive(path: &Path) -> anyhow::Result<Option<Self>> {
        Self::acquire(path, true)
    }

    fn acquire(path: &Path, exclusive: bool) -> anyhow::Result<Option<Self>> {
        reject_symlink(path)?;
        let wide = wide_path(path)?;
        // SAFETY: the session directory was verified before this fixed file is opened.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_ALWAYS,
                0,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error().into());
        }
        let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
        let mut flags = LOCKFILE_FAIL_IMMEDIATELY;
        if exclusive {
            flags |= LOCKFILE_EXCLUSIVE_LOCK;
        }
        // SAFETY: handle is valid and byte zero is reserved for lifecycle state.
        if unsafe { LockFileEx(handle, flags, 0, 1, 0, &mut overlapped) } == 0 {
            let error = std::io::Error::last_os_error();
            unsafe { CloseHandle(handle) };
            if error.raw_os_error() == Some(33) {
                return Ok(None);
            }
            return Err(error.into());
        }
        Ok(Some(Self(handle)))
    }
}

impl Drop for SessionLifecycleLock {
    fn drop(&mut self) {
        let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
        // SAFETY: this wrapper uniquely owns its valid file handle.
        unsafe {
            UnlockFileEx(self.0, 0, 1, 0, &mut overlapped);
            CloseHandle(self.0);
        }
    }
}

impl McpSession {
    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for McpSession {
    fn drop(&mut self) {
        self.lifecycle_lock.take();
        let _ = remove_real_directory_tree(&self.path);
    }
}

/// A short-lived, exclusive runtime lock for embedded EXE/manifest release.
/// It is deliberately separate from the long-lived MCP/update coordination
/// lock, and the operating system releases it if a process is terminated.
pub struct ComponentReleaseLock(HANDLE);

impl ComponentReleaseLock {
    fn acquire(path: &Path, timeout: Duration) -> anyhow::Result<Self> {
        reject_symlink(path)?;
        let wide = wide_path(path)?;
        // SAFETY: path is NUL-terminated and this process owns the returned handle.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_ALWAYS,
                0,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error().into());
        }
        let deadline = Instant::now() + timeout;
        loop {
            let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
            // SAFETY: byte zero is exclusively reserved by this fixed lock file.
            if unsafe {
                LockFileEx(
                    handle,
                    LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
                    0,
                    1,
                    0,
                    &mut overlapped,
                )
            } != 0
            {
                return Ok(Self(handle));
            }
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() != Some(33) || Instant::now() >= deadline {
                unsafe { CloseHandle(handle) };
                return Err(if error.raw_os_error() == Some(33) {
                    anyhow::anyhow!("等待内部组件释放锁超时")
                } else {
                    error.into()
                });
            }
            thread::sleep(COMPONENT_RELEASE_LOCK_RETRY);
        }
    }
}

impl Drop for ComponentReleaseLock {
    fn drop(&mut self) {
        let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
        // SAFETY: this wrapper owns the successful LockFileEx handle.
        unsafe {
            UnlockFileEx(self.0, 0, 1, 0, &mut overlapped);
            CloseHandle(self.0);
        }
    }
}

/// Cross-process byte-range lock.  Shared locks protect active MCP sessions;
/// the updater obtains an immediate exclusive lock before it asks GUI to exit.
pub struct InstallCoordinationLock(HANDLE);

impl InstallCoordinationLock {
    fn acquire(path: &Path, exclusive: bool) -> anyhow::Result<Self> {
        reject_symlink(path)?;
        let wide = wide_path(path)?;
        // SAFETY: the path is NUL-terminated and the returned handle is owned below.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_ALWAYS,
                0,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(std::io::Error::last_os_error().into());
        }
        let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
        let mut flags = LOCKFILE_FAIL_IMMEDIATELY;
        if exclusive {
            flags |= LOCKFILE_EXCLUSIVE_LOCK;
        }
        // SAFETY: handle is valid and overlapped is initialized for byte zero.
        if unsafe { LockFileEx(handle, flags, 0, 1, 0, &mut overlapped) } == 0 {
            unsafe { CloseHandle(handle) };
            anyhow::bail!(if exclusive {
                "当前仍有 MCP 会话，暂不能安装更新"
            } else {
                "正在安装更新，MCP 会话已被安全拒绝"
            });
        }
        Ok(Self(handle))
    }
}

impl Drop for InstallCoordinationLock {
    fn drop(&mut self) {
        if self.0 != INVALID_HANDLE_VALUE && !self.0.is_null() {
            let mut overlapped: OVERLAPPED = unsafe { std::mem::zeroed() };
            // SAFETY: this process owns the lock and closes the handle once.
            unsafe {
                UnlockFileEx(self.0, 0, 1, 0, &mut overlapped);
                CloseHandle(self.0);
            }
        }
    }
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

fn atomic_write(destination: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let parent = destination
        .parent()
        .ok_or_else(|| anyhow::anyhow!("无法确定运行文件目录"))?;
    ensure_real_directory(parent)?;
    reject_symlink(destination)?;
    let filename = destination
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow::anyhow!("运行文件名无效"))?;
    for _ in 0..16 {
        let counter = TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed);
        let temporary = parent.join(format!(".{filename}.{}.{}.tmp", process::id(), counter));
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary);
        let mut file = match file {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        };
        let result = (|| -> anyhow::Result<()> {
            file.write_all(bytes)?;
            file.sync_all()?;
            drop(file);
            replace_file_atomically(&temporary, destination)
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        return result;
    }
    anyhow::bail!("无法创建后端运行临时文件")
}

fn replace_file_atomically(source: &Path, destination: &Path) -> anyhow::Result<()> {
    let source = wide_path(source)?;
    let destination = wide_path(destination)?;
    // SAFETY: paths are NUL-terminated UTF-16; source and destination share a
    // directory, and the API atomically replaces only the destination entry.
    if unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

fn wide_path(path: &Path) -> anyhow::Result<Vec<u16>> {
    if path.as_os_str().is_empty() {
        anyhow::bail!("运行文件路径为空");
    }
    let mut path: Vec<u16> = OsStr::new(path).encode_wide().collect();
    if path.contains(&0) {
        anyhow::bail!("运行文件路径包含无效 NUL 字符");
    }
    path.push(0);
    Ok(path)
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BackendHandshake {
    pub schema: u32,
    pub port: u16,
    pub pid: u32,
    pub version: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PortableManifest {
    pub schema: u32,
    pub version: String,
    pub published_at: String,
    pub notes_url: String,
    pub asset: PortableAsset,
    pub minimum_windows: String,
    pub signature: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PortableAsset {
    pub name: String,
    pub url: String,
    pub size: u64,
    pub sha256: String,
}

impl PortableManifest {
    pub fn signed_payload(&self) -> String {
        format!(
            "{}|{}|{}|{}|{}",
            self.schema, self.version, self.asset.name, self.asset.size, self.asset.sha256
        )
    }

    pub fn validate(&self) -> anyhow::Result<()> {
        if self.schema != 1 {
            anyhow::bail!("不支持的便携更新清单版本");
        }
        if self.version.trim().is_empty() || self.asset.size == 0 {
            anyhow::bail!("更新清单缺少版本或文件大小");
        }
        if !is_safe_asset_name(&self.asset.name) {
            anyhow::bail!("更新包文件名不安全");
        }
        if self.asset.sha256.len() != 64
            || !self
                .asset
                .sha256
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit())
        {
            anyhow::bail!("更新清单中的 SHA-256 无效");
        }
        for value in [&self.asset.url, &self.notes_url] {
            let url = Url::parse(value)?;
            if url.scheme() != "https" {
                anyhow::bail!("更新链接必须使用 HTTPS");
            }
        }
        Ok(())
    }

    pub fn verify_signature(&self, public_key_b64: &str) -> anyhow::Result<()> {
        self.validate()?;
        let key_bytes = STANDARD
            .decode(public_key_b64)
            .map_err(|_| anyhow::anyhow!("应用没有有效的便携更新公钥"))?;
        let key_bytes: [u8; 32] = key_bytes
            .try_into()
            .map_err(|_| anyhow::anyhow!("应用没有有效的便携更新公钥"))?;
        let signature_bytes = STANDARD
            .decode(&self.signature)
            .map_err(|_| anyhow::anyhow!("更新清单签名无效"))?;
        let signature = Signature::from_slice(&signature_bytes)
            .map_err(|_| anyhow::anyhow!("更新清单签名无效"))?;
        VerifyingKey::from_bytes(&key_bytes)
            .map_err(|_| anyhow::anyhow!("更新清单公钥无效"))?
            .verify(self.signed_payload().as_bytes(), &signature)
            .map_err(|_| anyhow::anyhow!("更新清单签名校验失败"))
    }
}

pub fn is_safe_asset_name(name: &str) -> bool {
    Path::new(name)
        .components()
        .all(|component| matches!(component, Component::Normal(_)))
        && name.to_ascii_lowercase().ends_with(".exe")
        && !name.is_empty()
}

pub fn sha256_file(path: &Path) -> anyhow::Result<String> {
    let mut file = fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

/// The preview MCP server may only receive an explicit local, immutable SQLite
/// backup.  Keep this validation in the shell so child stderr never needs to
/// reveal a user supplied path.
pub fn validate_mcp_database_path(path: &Path) -> anyhow::Result<PathBuf> {
    if !path.is_absolute() {
        anyhow::bail!("MCP 数据库副本必须是绝对本地路径")
    }
    let Some(Component::Prefix(prefix)) = path.components().next() else {
        anyhow::bail!("MCP 数据库副本必须位于本地磁盘")
    };
    let Prefix::Disk(letter) = prefix.kind() else {
        anyhow::bail!("MCP 数据库副本不允许使用 UNC 或设备路径")
    };
    let root = [letter as u16, b':' as u16, b'\\' as u16, 0];
    // SAFETY: root is a fixed NUL-terminated drive root.
    if !matches!(
        unsafe { GetDriveTypeW(root.as_ptr()) },
        DRIVE_FIXED | DRIVE_REMOVABLE
    ) {
        anyhow::bail!("MCP 数据库副本必须位于固定或可移动本地磁盘")
    }
    let mut current = PathBuf::from(format!("{}:\\", letter as char));
    let mut components = path.components();
    let _ = components.next(); // verified drive prefix above
    if !matches!(components.next(), Some(Component::RootDir)) {
        anyhow::bail!("MCP 数据库副本必须使用驱动器绝对路径")
    }
    for component in components {
        let Component::Normal(part) = component else {
            anyhow::bail!("MCP 数据库副本路径不能包含相对段")
        };
        current.push(part);
        let metadata = fs::symlink_metadata(&current)?;
        if metadata.file_type().is_symlink() || is_reparse_point(&current)? {
            anyhow::bail!("MCP 数据库副本路径不能包含 reparse point")
        }
    }
    let metadata = fs::symlink_metadata(&current)?;
    if !metadata.is_file() {
        anyhow::bail!("MCP 数据库副本必须是普通文件")
    }
    // The component path has already been checked segment by segment. Keep
    // this normal drive-absolute form: `canonicalize` would add Windows' `\\?\\`
    // verbatim prefix, which the Python read-only MCP boundary intentionally rejects.
    Ok(current)
}

pub fn version_is_newer(candidate: &str, current: &str) -> bool {
    let parse = |version: &str| Version::parse(version.trim_start_matches('v'));
    match (parse(candidate), parse(current)) {
        (Ok(candidate), Ok(current)) => candidate > current,
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use rand::rngs::OsRng;

    fn manifest() -> PortableManifest {
        PortableManifest {
            schema: 1,
            version: "0.1.0".into(),
            published_at: "2026-08-08T00:00:00Z".into(),
            notes_url: "https://example.com/notes".into(),
            asset: PortableAsset {
                name: "BiliOpinionMonitor-0.1.0-windows-x64.exe".into(),
                url: "https://example.com/app.exe".into(),
                size: 42,
                sha256: "a".repeat(64),
            },
            minimum_windows: "10.0.17134".into(),
            signature: String::new(),
        }
    }

    #[test]
    fn verifies_signed_manifest() {
        let signing = SigningKey::generate(&mut OsRng);
        let mut item = manifest();
        item.signature = STANDARD.encode(signing.sign(item.signed_payload().as_bytes()).to_bytes());
        assert!(item
            .verify_signature(&STANDARD.encode(signing.verifying_key().to_bytes()))
            .is_ok());
    }

    #[test]
    fn compares_prerelease_versions() {
        assert!(version_is_newer("0.1.0", "0.1.0-beta.1"));
        assert!(version_is_newer("0.1.0-beta.2", "0.1.0-beta.1"));
        assert!(version_is_newer("0.2.0", "0.1.0"));
        assert!(!version_is_newer("0.0.9", "0.1.0"));
    }

    #[test]
    fn embedded_backend_is_released_and_verified_before_reuse() {
        let root = std::env::temp_dir().join(format!(
            "bili-opinion-portable-test-{}-{}",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let paths = PortablePaths::from_install_root(root.clone()).unwrap();
        let executable = paths
            .materialize_embedded_backend(b"backend-v1", "0.1.0")
            .unwrap();
        assert_eq!(fs::read(&executable).unwrap(), b"backend-v1");

        fs::write(&executable, b"tampered").unwrap();
        let executable = paths
            .materialize_embedded_backend(b"backend-v1", "0.1.0")
            .unwrap();
        assert_eq!(fs::read(&executable).unwrap(), b"backend-v1");

        paths
            .materialize_embedded_backend(b"backend-v2", "0.1.1")
            .unwrap();
        assert_eq!(fs::read(&executable).unwrap(), b"backend-v2");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn embedded_components_use_separate_allowlisted_manifests() {
        let root = std::env::temp_dir().join(format!(
            "bili-opinion-components-test-{}-{}",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let paths = PortablePaths::from_install_root(root.clone()).unwrap();
        let backend = paths
            .materialize_embedded_component(EmbeddedComponent::Backend, b"backend", "0.1.0")
            .unwrap();
        let mcp = paths
            .materialize_embedded_component(EmbeddedComponent::AgentMcp, b"mcp", "0.1.0")
            .unwrap();
        assert_ne!(backend, mcp);
        assert_eq!(fs::read(backend).unwrap(), b"backend");
        assert_eq!(fs::read(mcp).unwrap(), b"mcp");
        assert!(paths.runtime_dir.join(EMBEDDED_BACKEND_MANIFEST).is_file());
        assert!(paths.runtime_dir.join(EMBEDDED_MCP_MANIFEST).is_file());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn component_release_lock_serializes_concurrent_materialization() {
        let root = std::env::temp_dir().join(format!(
            "bili-opinion-component-lock-test-{}-{}",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let paths = PortablePaths::from_install_root(root.clone()).unwrap();
        let held = paths.acquire_component_release_lock().unwrap();
        assert!(
            ComponentReleaseLock::acquire(&paths.component_release_lock_path, Duration::ZERO)
                .is_err()
        );
        drop(held);

        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let left_paths = paths.clone();
        let left_barrier = barrier.clone();
        let left = std::thread::spawn(move || {
            left_barrier.wait();
            left_paths.materialize_embedded_component(EmbeddedComponent::AgentMcp, b"mcp", "0.1.0")
        });
        let right_paths = paths.clone();
        let right = std::thread::spawn(move || {
            barrier.wait();
            right_paths.materialize_embedded_component(EmbeddedComponent::AgentMcp, b"mcp", "0.1.0")
        });
        let left = left.join().unwrap().unwrap();
        let right = right.join().unwrap().unwrap();
        assert_eq!(left, right);
        assert_eq!(fs::read(left).unwrap(), b"mcp");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn mcp_sessions_are_distinct_and_hold_the_update_lock_out() {
        let root = std::env::temp_dir().join(format!(
            "bili-opinion-mcp-session-test-{}-{}",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let paths = PortablePaths::from_install_root(root.clone()).unwrap();
        let first = paths.create_mcp_session().unwrap();
        let second = paths.create_mcp_session().unwrap();
        assert_ne!(first.path(), second.path());
        assert!(SessionLifecycleLock::try_acquire_exclusive(
            &first.path().join(MCP_SESSION_LIFECYCLE_LOCK)
        )
        .unwrap()
        .is_none());
        let old_enough = fs::symlink_metadata(first.path())
            .unwrap()
            .modified()
            .unwrap()
            + MCP_SESSION_MAX_AGE
            + std::time::Duration::from_secs(1);
        paths.clear_abandoned_mcp_sessions_at(old_enough).unwrap();
        assert!(first.path().is_dir());
        let _shared = paths.acquire_mcp_lock().unwrap();
        assert!(paths.acquire_update_lock().is_err());
        drop(first);
        drop(second);
        assert!(fs::read_dir(&paths.mcp_temp_root).unwrap().next().is_none());
        drop(_shared);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn mcp_database_path_rejects_relative_paths_without_echoing_them() {
        let sentinel = Path::new("secret-parent/secret-db.sqlite");
        let error = validate_mcp_database_path(sentinel)
            .unwrap_err()
            .to_string();
        assert!(!error.contains("secret-parent"));
    }

    #[test]
    fn mcp_database_path_keeps_a_normal_absolute_drive_path() {
        let root = std::env::temp_dir().join(format!(
            "bili-opinion-mcp-db-path-test-{}-{}",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        let database = root.join("snapshot.sqlite");
        fs::write(&database, b"sqlite backup").unwrap();
        let validated = validate_mcp_database_path(&database).unwrap();
        assert!(validated.is_absolute());
        assert!(!validated.as_os_str().to_string_lossy().starts_with(r"\\?\"));
        assert_eq!(fs::read(&validated).unwrap(), b"sqlite backup");
        fs::remove_dir_all(root).unwrap();
    }
}
