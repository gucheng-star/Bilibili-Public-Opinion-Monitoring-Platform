//! Internal portable updater mode of the main executable.
//!
//! The main executable is copied to `data/update-runner` before launch, so the
//! copied process can atomically replace the original executable after its
//! parent exits.
use crate::portable::sha256_file;
use std::{
    env,
    ffi::OsStr,
    fs,
    io::{self, Read, Write},
    os::windows::ffi::OsStrExt,
    path::{Path, PathBuf},
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use windows_sys::Win32::{
    Foundation::CloseHandle,
    Storage::FileSystem::{ReplaceFileW, REPLACEFILE_WRITE_THROUGH},
    System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE},
};

const HEALTH_WAIT: Duration = Duration::from_secs(60);
pub const RUNNER_ARGUMENT: &str = "--portable-update-runner";
static TEMP_FILE_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Debug)]
struct Arguments {
    staged_executable: PathBuf,
    target_executable: PathBuf,
    data_dir: PathBuf,
    parent_pid: u32,
    expected_version: String,
    expected_sha256: String,
}

pub fn run_update_runner() -> anyhow::Result<()> {
    run().map_err(|error| {
        let _ = write_update_log(&format!("更新失败：{error}"));
        error
    })
}

fn run() -> anyhow::Result<()> {
    let arguments = parse_arguments()?;
    wait_for_parent(arguments.parent_pid);

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
    ensure_real_directory(&backup_root)?;
    let replacement = prepare_replacement(
        &arguments.staged_executable,
        &arguments.target_executable,
        &arguments.expected_sha256,
    )?;
    let backup = backup_root.join(
        arguments
            .target_executable
            .file_name()
            .ok_or_else(|| anyhow::anyhow!("当前主程序路径无效"))?,
    );
    replace_file_atomically(&replacement, &arguments.target_executable, Some(&backup))?;
    let replace_result = (|| -> anyhow::Result<()> {
        write_pending_health(
            &arguments.data_dir,
            &arguments.expected_version,
            &backup_root,
        )?;
        Command::new(&arguments.target_executable)
            .current_dir(
                arguments
                    .target_executable
                    .parent()
                    .ok_or_else(|| anyhow::anyhow!("无法确定主程序目录"))?,
            )
            .spawn()
            .map_err(|error| anyhow::anyhow!("已替换文件但无法启动新版本：{error}"))?;
        Ok(())
    })();
    if let Err(error) = replace_result {
        let rollback = rollback_program_file(&arguments.target_executable, &backup);
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

    rollback_program_file(&arguments.target_executable, &backup)?;
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
    if iterator.next().as_deref() != Some(RUNNER_ARGUMENT) {
        anyhow::bail!("未指定内部更新器模式");
    }
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
    let data_dir = PathBuf::from(required("--data-dir")?);
    let (staged_executable, target_executable) = validate_runner_paths(
        &data_dir,
        &env::current_exe()?,
        &PathBuf::from(required("--staged-exe")?),
        &PathBuf::from(required("--target-exe")?),
    )?;
    let expected_sha256 = required("--expected-sha256")?.to_ascii_lowercase();
    if expected_sha256.len() != 64 || !expected_sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        anyhow::bail!("更新校验值格式无效");
    }
    Ok(Arguments {
        staged_executable,
        target_executable,
        data_dir: fs::canonicalize(data_dir)?,
        parent_pid: required("--parent-pid")?.parse()?,
        expected_version: required("--expected-version")?,
        expected_sha256,
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

fn validate_runner_paths(
    data_dir: &Path,
    current_executable: &Path,
    staged_executable: &Path,
    target_executable: &Path,
) -> anyhow::Result<(PathBuf, PathBuf)> {
    let data_dir = canonical_directory(data_dir, "数据目录")?;
    let runner_dir = canonical_directory(&data_dir.join("update-runner"), "更新器目录")?;
    let cache_dir = canonical_directory(&data_dir.join("update-cache"), "更新缓存目录")?;
    let current_executable = canonical_regular_file(current_executable, "内部更新器")?;
    if current_executable.parent() != Some(runner_dir.as_path()) {
        anyhow::bail!("内部更新器必须从 data/update-runner 目录启动");
    }
    let staged_executable = canonical_regular_file(staged_executable, "更新程序")?;
    if staged_executable.parent() != Some(cache_dir.as_path()) {
        anyhow::bail!("更新程序必须位于 data/update-cache 目录");
    }
    let target_executable = canonical_regular_file(target_executable, "当前主程序")?;
    let install_root = data_dir
        .parent()
        .ok_or_else(|| anyhow::anyhow!("数据目录没有安装根目录"))?;
    if target_executable.parent() != Some(install_root) || target_executable.starts_with(&data_dir)
    {
        anyhow::bail!("当前主程序必须位于 data 目录的上一级");
    }
    if !target_executable
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("exe"))
    {
        anyhow::bail!("当前主程序必须是 EXE 文件");
    }
    Ok((staged_executable, target_executable))
}

fn canonical_directory(path: &Path, label: &str) -> anyhow::Result<PathBuf> {
    let metadata =
        fs::symlink_metadata(path).map_err(|error| anyhow::anyhow!("{label}不可用：{error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        anyhow::bail!("{label}必须是实际目录");
    }
    Ok(fs::canonicalize(path)?)
}

fn canonical_regular_file(path: &Path, label: &str) -> anyhow::Result<PathBuf> {
    let metadata =
        fs::symlink_metadata(path).map_err(|error| anyhow::anyhow!("{label}不可用：{error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        anyhow::bail!("{label}必须是普通文件，不能是符号链接");
    }
    Ok(fs::canonicalize(path)?)
}

fn assert_staged_executable(path: &Path, expected_sha256: &str) -> anyhow::Result<()> {
    let mut file = fs::File::open(path)?;
    let mut header = [0_u8; 2];
    file.read_exact(&mut header)?;
    if header != *b"MZ" {
        anyhow::bail!("已签名更新文件不是 Windows 可执行程序");
    }
    if sha256_file(path)? != expected_sha256 {
        anyhow::bail!("更新程序哈希与已签名清单不一致");
    }
    Ok(())
}

fn prepare_replacement(
    source: &Path,
    target: &Path,
    expected_sha256: &str,
) -> anyhow::Result<PathBuf> {
    assert_staged_executable(source, expected_sha256)?;
    let target_directory = target
        .parent()
        .ok_or_else(|| anyhow::anyhow!("无法确定主程序目录"))?;
    let target_name = target
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| anyhow::anyhow!("当前主程序文件名无效"))?;
    let source_size = fs::metadata(source)?.len();
    for _ in 0..16 {
        let temporary = target_directory.join(format!(
            ".{target_name}.{}.{}.update",
            std::process::id(),
            TEMP_FILE_COUNTER.fetch_add(1, Ordering::Relaxed)
        ));
        let mut output = match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
        {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        };
        let result = (|| -> anyhow::Result<()> {
            let mut input = fs::File::open(source)?;
            io::copy(&mut input, &mut output)?;
            output.flush()?;
            output.sync_all()?;
            drop(output);
            if fs::metadata(&temporary)?.len() != source_size {
                anyhow::bail!("更新程序临时副本大小不一致");
            }
            assert_staged_executable(&temporary, expected_sha256)
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result?;
        return Ok(temporary);
    }
    anyhow::bail!("无法创建更新程序临时副本")
}

fn replace_file_atomically(
    replacement: &Path,
    target: &Path,
    backup: Option<&Path>,
) -> anyhow::Result<()> {
    let replacement = wide_path(replacement)?;
    let target = wide_path(target)?;
    let backup = backup.map(wide_path).transpose()?;
    // SAFETY: all paths are NUL-terminated UTF-16 paths on the same volume.
    // ReplaceFileW leaves the target as either a complete old or complete new file.
    if unsafe {
        ReplaceFileW(
            target.as_ptr(),
            replacement.as_ptr(),
            backup
                .as_ref()
                .map_or(std::ptr::null(), |path| path.as_ptr()),
            REPLACEFILE_WRITE_THROUGH,
            std::ptr::null(),
            std::ptr::null(),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

fn rollback_program_file(target: &Path, backup: &Path) -> anyhow::Result<()> {
    if !backup.is_file() {
        anyhow::bail!("未找到可回滚的主程序备份");
    }
    replace_file_atomically(backup, target, None)
}

fn wide_path(path: &Path) -> anyhow::Result<Vec<u16>> {
    let mut value: Vec<u16> = OsStr::new(path).encode_wide().collect();
    if value.contains(&0) {
        anyhow::bail!("更新程序路径包含无效 NUL 字符");
    }
    value.push(0);
    Ok(value)
}

fn ensure_real_directory(path: &Path) -> anyhow::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        anyhow::bail!("更新运行目录必须是实际目录");
    }
    Ok(())
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
    fn atomic_replacement_and_rollback_restore_only_the_target_executable() {
        let root = std::env::temp_dir().join(format!("bili-updater-test-{}", unix_timestamp()));
        let install = root.join("install");
        let backup = root.join("backup");
        fs::create_dir_all(install.join("data")).unwrap();
        fs::create_dir_all(&backup).unwrap();
        let target = install.join("custom-name.exe");
        fs::write(&target, "old").unwrap();
        fs::write(install.join("neighbor.txt"), "preserve").unwrap();
        fs::write(install.join("data").join("history.txt"), "history").unwrap();
        let replacement = root.join("downloaded-update.exe");
        fs::write(&replacement, b"MZnew").unwrap();
        let checksum = sha256_file(&replacement).unwrap();

        let temporary = prepare_replacement(&replacement, &target, &checksum).unwrap();
        let backup_file = backup.join("custom-name.exe");
        replace_file_atomically(&temporary, &target, Some(&backup_file)).unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"MZnew");
        assert_eq!(fs::read(&backup_file).unwrap(), b"old");

        rollback_program_file(&target, &backup_file).unwrap();
        assert_eq!(fs::read_to_string(&target).unwrap(), "old");
        assert_eq!(
            fs::read_to_string(install.join("neighbor.txt")).unwrap(),
            "preserve"
        );
        assert_eq!(
            fs::read_to_string(install.join("data").join("history.txt")).unwrap(),
            "history"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_runner_paths_outside_the_data_boundaries() {
        let root = std::env::temp_dir().join(format!("bili-updater-paths-{}", unix_timestamp()));
        let data = root.join("data");
        let cache = data.join("update-cache");
        let runner = data.join("update-runner");
        fs::create_dir_all(&cache).unwrap();
        fs::create_dir_all(&runner).unwrap();
        let current = runner.join("runner.exe");
        let staged = cache.join("staged.exe");
        let target = root.join("app.exe");
        fs::write(&current, "runner").unwrap();
        fs::write(&staged, b"MZnew").unwrap();
        fs::write(&target, "old").unwrap();

        assert!(validate_runner_paths(&data, &current, &staged, &target).is_ok());
        assert!(validate_runner_paths(&data, &current, &root.join("staged.exe"), &target).is_err());
        assert!(validate_runner_paths(&data, &current, &staged, &data.join("target.exe")).is_err());
        assert!(validate_runner_paths(&data, &target, &staged, &target).is_err());
        let _ = fs::remove_dir_all(root);
    }
}
