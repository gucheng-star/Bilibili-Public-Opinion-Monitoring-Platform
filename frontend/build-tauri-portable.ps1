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

$FrontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $FrontendRoot
$BackendRoot = Join-Path $ProjectRoot "backend"
$BackendBuildScript = Join-Path $BackendRoot "build_portable_backend.ps1"
$BackendOutputDirectory = "dist"
Set-Location $FrontendRoot
$EmbeddedBackend = Join-Path $FrontendRoot "src-tauri/resources/BiliOpinionBackend.exe"

if (-not (Test-Path -LiteralPath $BackendBuildScript -PathType Leaf)) {
    throw "Missing portable backend build script: $BackendBuildScript"
}

# Always rebuild the onefile backend immediately before compiling the Tauri
# shell. This prevents a desktop executable from embedding an old resource.
& $BackendBuildScript -OutputDirectory $BackendOutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Portable backend build failed with exit code $LASTEXITCODE"
}
# The backend script builds from its own directory. Restore the frontend
# working directory before invoking pnpm/Tauri in this same PowerShell process.
Set-Location $FrontendRoot

$GeneratedBackend = Join-Path $BackendRoot "$BackendOutputDirectory/BiliOpinionBackend.exe"
if (-not (Test-Path -LiteralPath $GeneratedBackend -PathType Leaf)) {
    throw "Missing generated portable backend: $GeneratedBackend"
}
if (-not (Test-Path -LiteralPath $EmbeddedBackend -PathType Leaf)) {
    throw "Missing copied embedded backend: $EmbeddedBackend"
}

$GeneratedHash = Get-Sha256Hex $GeneratedBackend
$EmbeddedHash = Get-Sha256Hex $EmbeddedBackend
if ($GeneratedHash -ne $EmbeddedHash) {
    throw "Embedded backend does not match the backend generated for this build."
}

# Tauri builds the single portable executable and embeds both the frontend and
# the prebuilt Python backend. The main executable also contains updater mode.
& pnpm exec tauri build --no-bundle
if ($LASTEXITCODE -ne 0) {
    throw "Tauri build failed with exit code $LASTEXITCODE"
}
