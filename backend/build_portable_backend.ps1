param(
    [string]$OutputDirectory = "dist-portable"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$BuildPath = Join-Path $OutputPath "build"
$DesktopResourceDirectory = Join-Path $Root "..\frontend\src-tauri\resources"
$DesktopResourcePath = Join-Path $DesktopResourceDirectory "BiliOpinionBackend.exe"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $OutputPath ".pyinstaller-cache"
New-Item -ItemType Directory -Force -Path $OutputPath, $BuildPath, $env:PYINSTALLER_CONFIG_DIR, $DesktopResourceDirectory | Out-Null

# The onefile artifact is copied to a Tauri compile-time resource path. The
# shell embeds these bytes, so the release package needs no backend directory.
& .\venv\Scripts\python.exe -m PyInstaller .\portable_backend.spec `
    --noconfirm `
    --clean `
    --distpath $OutputPath `
    --workpath $BuildPath

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码: $LASTEXITCODE"
}

$BackendExecutable = Join-Path $OutputPath "BiliOpinionBackend.exe"
if (-not (Test-Path -LiteralPath $BackendExecutable)) {
    throw "未找到 PyInstaller 单文件后端：$BackendExecutable"
}
Copy-Item -LiteralPath $BackendExecutable -Destination $DesktopResourcePath -Force
