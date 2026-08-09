param(
    [string]$OutputDirectory = "dist-portable"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Get-Sha256Hex([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
        }
        finally { $algorithm.Dispose() }
    }
    finally { $stream.Dispose() }
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$BuildPath = Join-Path $OutputPath "build"
$DesktopResourceDirectory = Join-Path $Root "..\frontend\src-tauri\resources"
$DesktopResourcePath = Join-Path $DesktopResourceDirectory "BiliOpinionBackend.exe"
$BackendExecutable = Join-Path $OutputPath "BiliOpinionBackend.exe"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $OutputPath ".pyinstaller-cache"
New-Item -ItemType Directory -Force -Path $OutputPath, $BuildPath, $env:PYINSTALLER_CONFIG_DIR, $DesktopResourceDirectory | Out-Null

# Do not let a previous artifact survive a partial build and be copied again.
if (Test-Path -LiteralPath $BackendExecutable -PathType Leaf) {
    Remove-Item -LiteralPath $BackendExecutable -Force
}
$BuildStartedAt = [DateTime]::UtcNow

# The onefile artifact is copied to a Tauri compile-time resource path. The
# shell embeds these bytes, so the release package needs no backend directory.
& .\venv\Scripts\python.exe -m PyInstaller .\portable_backend.spec `
    --noconfirm `
    --clean `
    --distpath $OutputPath `
    --workpath $BuildPath

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $BackendExecutable)) {
    throw "Missing PyInstaller onefile backend: $BackendExecutable"
}

$BackendItem = Get-Item -LiteralPath $BackendExecutable
if ($BackendItem.LastWriteTimeUtc -lt $BuildStartedAt.AddSeconds(-2)) {
    throw "PyInstaller returned an outdated backend executable: $BackendExecutable"
}
Copy-Item -LiteralPath $BackendExecutable -Destination $DesktopResourcePath -Force

$GeneratedHash = Get-Sha256Hex $BackendExecutable
$ResourceHash = Get-Sha256Hex $DesktopResourcePath
if ($GeneratedHash -ne $ResourceHash) {
    throw "Failed to copy the generated backend to the Tauri resource path."
}
