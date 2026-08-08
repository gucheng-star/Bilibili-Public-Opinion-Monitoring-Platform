//! Separate portable updater process.
//!
//! It is copied to `data/update-runner` before launch, so replacing application
//! files never overwrites the executable that is currently running.

#[allow(dead_code)]
#[path = "../portable.rs"]
mod portable;

use portable::checked_extract_path;
use std::{
    env, fs, io,
    path::{Path, PathBuf},
    process::Command,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use windows_sys::Win32::{
    Foundation::CloseHandle,
    System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE},
};

const PRESERVED_ENTRIES: &[&str] = &["data", "portable.ini"];
const HEALTH_WAIT: Duration = Duration::from_secs(60);

#[derive(Debug)]
struct Arguments {
    staged_zip: PathBuf,
    install_root: PathBuf,
    data_dir: PathBuf,
    parent_pid: u32,
    expected_version: String,
}

fn main() {
    if let Err(error) = run() {
        let _ = write_update_log(&format!("更新失败：{error}"));
        eprintln!("便携更新失败：{error}");
        std::process::exit(1);
    }
}

fn run() -> anyhow::Result<()> {
    let arguments = parse_arguments()?;
    wait_for_parent(arguments.parent_pid);

    let unpack_root = arguments.data_dir.join("update-cache").join(format!(
        "unpacked-{}",
        safe_fragment(&arguments.expected_version)
    ));
    if unpack_root.exists() {
        anyhow::bail!(
            "发现未清理的同版本更新目录，请手动检查后重试：{}",
            unpack_root.display()
        );
    }
    fs::create_dir_all(&unpack_root)?;
    extract_safely(&arguments.staged_zip, &unpack_root)?;
    let payload_root = locate_payload_root(&unpack_root)?;
    assert_payload(&payload_root)?;

    let backup_root = arguments
        .data_dir
        .join("update-runner")
        .join("backups")
        .join(format!(
            "{}-{}",
            safe_fragment(&arguments.expected_version),
            unix_timestamp()
        ));
    fs::create_dir_all(&backup_root)?;
    stage_existing_program_files(&arguments.install_root, &backup_root)?;
    let replace_result = (|| -> anyhow::Result<()> {
        copy_payload_entries(&payload_root, &arguments.install_root)?;
        write_pending_health(
            &arguments.data_dir,
            &arguments.expected_version,
            &backup_root,
        )?;
        let app = arguments.install_root.join("BiliOpinionMonitor.exe");
        Command::new(&app)
            .current_dir(&arguments.install_root)
            .spawn()
            .map_err(|error| anyhow::anyhow!("已替换文件但无法启动新版本：{error}"))?;
        Ok(())
    })();
    if let Err(error) = replace_result {
        let rollback = rollback_program_files(&arguments.install_root, &backup_root);
        let _ = fs::remove_file(
            arguments
                .data_dir
                .join("update-cache")
                .join("pending-health.json"),
        );
        if let Err(rollback_error) = rollback {
            anyhow::bail!("{error}；自动回滚也失败：{rollback_error}");
        }
        anyhow::bail!("{error}；已恢复旧版本程序文件");
    }

    if wait_for_health(&arguments.data_dir, &arguments.expected_version) {
        let _ = fs::remove_file(
            arguments
                .data_dir
                .join("update-cache")
                .join("pending-health.json"),
        );
        let _ = write_update_log("更新完成，已通过 60 秒启动健康检查。");
        return Ok(());
    }

    rollback_program_files(&arguments.install_root, &backup_root)?;
    let _ = fs::remove_file(
        arguments
            .data_dir
            .join("update-cache")
            .join("pending-health.json"),
    );
    let _ = write_update_log("新版本未在 60 秒内写入健康标记，已回滚程序文件。数据目录未受影响。");
    anyhow::bail!("新版本未在 60 秒内完成启动，已回滚")
}

fn parse_arguments() -> anyhow::Result<Arguments> {
    let mut values = std::collections::BTreeMap::new();
    let mut iterator = env::args().skip(1);
    while let Some(key) = iterator.next() {
        if !key.starts_with("--") {
            anyhow::bail!("未知的更新器参数：{key}");
        }
        values.insert(
            key,
            iterator
                .next()
                .ok_or_else(|| anyhow::anyhow!("参数缺少值"))?,
        );
    }
    let required = |name: &str| -> anyhow::Result<String> {
        values
            .get(name)
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("缺少更新器参数 {name}"))
    };
    let staged_zip = PathBuf::from(required("--staged-zip")?);
    if !staged_zip.is_file() {
        anyhow::bail!("已校验的更新包不存在");
    }
    Ok(Arguments {
        staged_zip,
        install_root: PathBuf::from(required("--install-root")?),
        data_dir: PathBuf::from(required("--data-dir")?),
        parent_pid: required("--parent-pid")?.parse()?,
        expected_version: required("--expected-version")?,
    })
}

fn wait_for_parent(pid: u32) {
    // The parent may have already exited before OpenProcess is called; that is safe.
    // SAFETY: this only obtains a synchronization handle for the supplied process ID.
    let handle = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, pid) };
    if !handle.is_null() {
        // SAFETY: handle is valid until closed below. 90 seconds is a conservative exit bound.
        unsafe { WaitForSingleObject(handle, 90_000) };
        unsafe { CloseHandle(handle) };
    }
}

fn extract_safely(archive_path: &Path, destination: &Path) -> anyhow::Result<()> {
    let file = fs::File::open(archive_path)?;
    let mut archive = zip::ZipArchive::new(file)?;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)?;
        let target = checked_extract_path(destination, entry.name())?;
        if entry.is_dir() {
            fs::create_dir_all(target)?;
            continue;
        }
        let parent = target
            .parent()
            .ok_or_else(|| anyhow::anyhow!("无效 ZIP 路径"))?;
        fs::create_dir_all(parent)?;
        let mut output = fs::File::create(&target)?;
        io::copy(&mut entry, &mut output)?;
    }
    Ok(())
}

fn locate_payload_root(unpack_root: &Path) -> anyhow::Result<PathBuf> {
    if unpack_root.join("BiliOpinionMonitor.exe").is_file() {
        return Ok(unpack_root.to_path_buf());
    }
    let entries = fs::read_dir(unpack_root)?.collect::<Result<Vec<_>, _>>()?;
    if entries.len() == 1 && entries[0].path().is_dir() {
        return Ok(entries[0].path());
    }
    anyhow::bail!("更新包必须包含唯一的应用根目录")
}

fn assert_payload(root: &Path) -> anyhow::Result<()> {
    for required in [
        root.join("BiliOpinionMonitor.exe"),
        root.join("BiliOpinionUpdater.exe"),
        root.join("backend").join("BiliOpinionBackend.exe"),
        root.join("portable.ini"),
    ] {
        if !required.is_file() {
            anyhow::bail!("更新包缺少必要文件：{}", required.display());
        }
    }
    Ok(())
}

/// Moves every replaceable program entry to backup before any new file is
/// copied. If staging itself fails, entries already moved are restored first.
fn stage_existing_program_files(install_root: &Path, backup_root: &Path) -> anyhow::Result<()> {
    let mut moved = Vec::new();
    for entry in fs::read_dir(install_root)? {
        let entry = entry?;
        let name = entry.file_name();
        if is_preserved(&name) {
            continue;
        }
        let original = entry.path();
        let backup = backup_root.join(&name);
        if let Err(error) = fs::rename(&original, &backup) {
            for (restore_from, restore_to) in moved.into_iter().rev() {
                let _ = fs::rename(restore_from, restore_to);
            }
            return Err(error.into());
        }
        moved.push((backup, original));
    }
    Ok(())
}

fn rollback_program_files(install_root: &Path, backup_root: &Path) -> anyhow::Result<()> {
    for entry in fs::read_dir(install_root)? {
        let entry = entry?;
        if !is_preserved(&entry.file_name()) {
            remove_path(&entry.path())?;
        }
    }
    for entry in fs::read_dir(backup_root)? {
        let entry = entry?;
        fs::rename(entry.path(), install_root.join(entry.file_name()))?;
    }
    Ok(())
}

fn copy_payload_entries(payload_root: &Path, install_root: &Path) -> anyhow::Result<()> {
    for entry in fs::read_dir(payload_root)? {
        let entry = entry?;
        if is_preserved(&entry.file_name()) {
            continue;
        }
        copy_path(&entry.path(), &install_root.join(entry.file_name()))?;
    }
    Ok(())
}

fn copy_path(source: &Path, target: &Path) -> anyhow::Result<()> {
    if source.is_dir() {
        fs::create_dir_all(target)?;
        for entry in fs::read_dir(source)? {
            let entry = entry?;
            copy_path(&entry.path(), &target.join(entry.file_name()))?;
        }
    } else {
        fs::copy(source, target)?;
    }
    Ok(())
}

fn remove_path(path: &Path) -> anyhow::Result<()> {
    if path.is_dir() {
        fs::remove_dir_all(path)?;
    } else {
        fs::remove_file(path)?;
    }
    Ok(())
}

fn is_preserved(name: &std::ffi::OsStr) -> bool {
    PRESERVED_ENTRIES
        .iter()
        .any(|preserved| name.eq_ignore_ascii_case(preserved))
}

fn write_pending_health(data_dir: &Path, version: &str, backup_root: &Path) -> anyhow::Result<()> {
    let pending = serde_json::json!({
        "version": version,
        "backup_dir": backup_root,
        "deadline_unix": unix_timestamp() + 60,
    });
    fs::write(
        data_dir.join("update-cache").join("pending-health.json"),
        serde_json::to_vec(&pending)?,
    )?;
    let _ = fs::remove_file(data_dir.join("update-cache").join("healthy-version.json"));
    Ok(())
}

fn wait_for_health(data_dir: &Path, version: &str) -> bool {
    let marker = data_dir.join("update-cache").join("healthy-version.json");
    let deadline = std::time::Instant::now() + HEALTH_WAIT;
    while std::time::Instant::now() < deadline {
        if fs::read_to_string(&marker)
            .ok()
            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
            .and_then(|value| {
                value
                    .get("version")
                    .and_then(|item| item.as_str())
                    .map(str::to_owned)
            })
            .is_some_and(|healthy_version| healthy_version == version)
        {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn safe_fragment(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '.' | '-' | '_') {
                character
            } else {
                '_'
            }
        })
        .collect()
}

fn unix_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

fn write_update_log(message: &str) -> io::Result<()> {
    let executable = env::current_exe()?;
    let log = executable
        .parent()
        .and_then(Path::parent)
        .map(|directory| directory.join("logs").join("updater.log"));
    if let Some(log) = log {
        if let Some(parent) = log.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(log, format!("{}\n", message))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn staging_and_rollback_restore_only_program_files() {
        let root = std::env::temp_dir().join(format!("bili-updater-test-{}", unix_timestamp()));
        let install = root.join("install");
        let payload = root.join("payload");
        let backup = root.join("backup");
        fs::create_dir_all(install.join("data")).unwrap();
        fs::create_dir_all(&payload).unwrap();
        fs::create_dir_all(&backup).unwrap();
        fs::write(install.join("old.exe"), "old").unwrap();
        fs::write(install.join("portable.ini"), "preserve").unwrap();
        fs::write(install.join("data").join("history.txt"), "history").unwrap();
        fs::write(payload.join("new.exe"), "new").unwrap();

        stage_existing_program_files(&install, &backup).unwrap();
        copy_payload_entries(&payload, &install).unwrap();
        assert!(!install.join("old.exe").exists());
        assert!(install.join("new.exe").is_file());

        rollback_program_files(&install, &backup).unwrap();
        assert_eq!(fs::read_to_string(install.join("old.exe")).unwrap(), "old");
        assert!(!install.join("new.exe").exists());
        assert_eq!(
            fs::read_to_string(install.join("portable.ini")).unwrap(),
            "preserve"
        );
        assert_eq!(
            fs::read_to_string(install.join("data").join("history.txt")).unwrap(),
            "history"
        );
        let _ = fs::remove_dir_all(root);
    }
}
