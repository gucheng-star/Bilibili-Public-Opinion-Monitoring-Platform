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
    path::{Component, Path, PathBuf},
    process,
    sync::atomic::{AtomicU64, Ordering},
};
use url::Url;
use windows_sys::Win32::Storage::FileSystem::{
    MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
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
static TEMP_FILE_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Clone)]
pub struct PortablePaths {
    pub data_dir: PathBuf,
    pub webview_dir: PathBuf,
    pub update_cache_dir: PathBuf,
    pub update_runner_dir: PathBuf,
    pub runtime_dir: PathBuf,
    pub backend_temp_dir: PathBuf,
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
        for directory in [
            &data_dir,
            &logs_dir,
            &webview_dir,
            &update_cache_dir,
            &update_runner_dir,
            &runtime_dir,
            &backend_temp_dir,
        ] {
            fs::create_dir_all(directory)?;
        }
        ensure_real_directory(&runtime_dir)?;
        ensure_real_directory(&backend_temp_dir)?;

        Ok(Self {
            handshake_path: data_dir.join("backend-handshake.json"),
            data_dir,
            webview_dir,
            update_cache_dir,
            update_runner_dir,
            runtime_dir,
            backend_temp_dir,
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
        let executable = self.runtime_dir.join(EMBEDDED_BACKEND_NAME);
        let manifest_path = self.runtime_dir.join(EMBEDDED_BACKEND_MANIFEST);
        let expected_sha256 = sha256_bytes(embedded_bytes);

        if embedded_backend_is_current(&executable, &manifest_path, app_version, &expected_sha256)?
        {
            return Ok(executable);
        }

        reject_symlink(&executable)?;
        reject_symlink(&manifest_path)?;
        atomic_write(&executable, embedded_bytes)?;
        let manifest = EmbeddedBackendManifest {
            schema: 1,
            app_version: app_version.to_owned(),
            sha256: expected_sha256,
        };
        atomic_write(&manifest_path, &serde_json::to_vec(&manifest)?)?;
        Ok(executable)
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
            if metadata.file_type().is_symlink() {
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
struct EmbeddedBackendManifest {
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
    let manifest: EmbeddedBackendManifest = match serde_json::from_slice(&fs::read(manifest_path)?)
    {
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
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        anyhow::bail!("运行目录必须是实际目录：{}", path.display());
    }
    Ok(())
}

fn reject_symlink(path: &Path) -> anyhow::Result<()> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            anyhow::bail!("运行文件不能是符号链接：{}", path.display())
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
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
}
