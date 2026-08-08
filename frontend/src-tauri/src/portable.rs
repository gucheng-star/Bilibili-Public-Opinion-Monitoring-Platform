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
    fs::{self, OpenOptions},
    io::Read,
    path::{Component, Path, PathBuf},
};
use url::Url;

pub const DEFAULT_MANIFEST_URL: &str =
    "https://github.com/gucheng-star/Bilibili-Public-Opinion-Monitoring-Platform/releases/latest/download/latest-portable.json";

/// Set at compile time by the release workflow. It is intentionally public;
/// the corresponding Ed25519 private key must never be put in this repository.
pub const UPDATE_PUBLIC_KEY_B64: &str = match option_env!("BILI_PORTABLE_UPDATE_PUBLIC_KEY") {
    Some(value) => value,
    None => "",
};

#[derive(Debug, Clone)]
pub struct PortablePaths {
    pub install_root: PathBuf,
    pub data_dir: PathBuf,
    pub webview_dir: PathBuf,
    pub update_cache_dir: PathBuf,
    pub update_runner_dir: PathBuf,
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

    pub fn from_install_root(install_root: PathBuf) -> anyhow::Result<Self> {
        let portable_ini = install_root.join("portable.ini");
        if !portable_ini.is_file() {
            anyhow::bail!(
                "未找到 portable.ini。请从完整的便携版 ZIP 解压后运行，不要单独移动 BiliOpinionMonitor.exe。"
            );
        }
        OpenOptions::new()
            .append(true)
            .open(&portable_ini)
            .map_err(|error| anyhow::anyhow!("便携程序目录不可写：{error}"))?;

        let data_dir = install_root.join("data");
        let logs_dir = data_dir.join("logs");
        let webview_dir = data_dir.join("webview");
        let update_cache_dir = data_dir.join("update-cache");
        let update_runner_dir = data_dir.join("update-runner");
        for directory in [
            &data_dir,
            &logs_dir,
            &webview_dir,
            &update_cache_dir,
            &update_runner_dir,
        ] {
            fs::create_dir_all(directory)?;
        }

        Ok(Self {
            handshake_path: data_dir.join("backend-handshake.json"),
            install_root,
            data_dir,
            webview_dir,
            update_cache_dir,
            update_runner_dir,
        })
    }

    pub fn backend_executable(&self) -> PathBuf {
        self.install_root
            .join("backend")
            .join("BiliOpinionBackend.exe")
    }

    pub fn updater_executable(&self) -> PathBuf {
        self.install_root.join("BiliOpinionUpdater.exe")
    }
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
        if !is_safe_archive_name(&self.asset.name) {
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

pub fn is_safe_archive_name(name: &str) -> bool {
    Path::new(name)
        .components()
        .all(|component| matches!(component, Component::Normal(_)))
        && name.ends_with(".zip")
        && !name.is_empty()
}

/// Rejects absolute paths, drive prefixes, parent paths, and entries escaping
/// the extraction root. Call this for every ZIP entry before extracting it.
pub fn checked_extract_path(root: &Path, entry_name: &str) -> anyhow::Result<PathBuf> {
    let entry = Path::new(entry_name);
    if entry_name.is_empty()
        || entry.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        anyhow::bail!("更新 ZIP 含有不安全路径：{entry_name}");
    }
    let destination = root.join(entry);
    if !destination.starts_with(root) {
        anyhow::bail!("更新 ZIP 路径越界：{entry_name}");
    }
    Ok(destination)
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
            version: "2.0.0".into(),
            published_at: "2026-08-08T00:00:00Z".into(),
            notes_url: "https://example.com/notes".into(),
            asset: PortableAsset {
                name: "BiliOpinionMonitor-2.0.0-windows-x64.zip".into(),
                url: "https://example.com/app.zip".into(),
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
    fn blocks_zip_slip() {
        let root = Path::new("C:/portable/data/update-cache");
        assert!(checked_extract_path(root, "../evil.exe").is_err());
        assert!(checked_extract_path(root, "C:/evil.exe").is_err());
        assert!(checked_extract_path(root, "safe/app.exe").is_ok());
    }

    #[test]
    fn compares_prerelease_versions() {
        assert!(version_is_newer("2.0.0", "2.0.0-beta.1"));
        assert!(version_is_newer("2.0.0-beta.2", "2.0.0-beta.1"));
        assert!(version_is_newer("2.1.0", "2.0.0"));
        assert!(!version_is_newer("1.9.0", "2.0.0"));
    }
}
