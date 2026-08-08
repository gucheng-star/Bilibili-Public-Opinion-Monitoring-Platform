$ErrorActionPreference = "Stop"
$FrontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $FrontendRoot

# Tauri builds the configured default application binary and embeds dist/.
& pnpm exec tauri build --no-bundle
if ($LASTEXITCODE -ne 0) {
    throw "Tauri 主程序构建失败，退出码: $LASTEXITCODE"
}

# The portable updater is intentionally a separate process so it can replace
# the main executable after the app exits.
& cargo build --release --manifest-path .\src-tauri\Cargo.toml --bin BiliOpinionUpdater
if ($LASTEXITCODE -ne 0) {
    throw "便携更新器构建失败，退出码: $LASTEXITCODE"
}
