param(
    [string]$OutputDirectory = "dist-portable"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$BuildPath = Join-Path $OutputPath "build"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $OutputPath ".pyinstaller-cache"
New-Item -ItemType Directory -Force -Path $OutputPath, $BuildPath, $env:PYINSTALLER_CONFIG_DIR | Out-Null

# ``onedir`` avoids onefile unpacking into a temporary directory on C: at
# every launch.  The release assembler copies this directory beside the shell.
& .\venv\Scripts\python.exe -m PyInstaller .\portable_backend.spec `
    --noconfirm `
    --clean `
    --distpath $OutputPath `
    --workpath $BuildPath

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码: $LASTEXITCODE"
}
