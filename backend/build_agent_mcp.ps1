param(
    [string]$OutputDirectory = "dist-agent-mcp"
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

function Assert-ChildPath([string]$ParentDirectory, [string]$Candidate) {
    $separator = [IO.Path]::DirectorySeparatorChar
    $prefix = $ParentDirectory.TrimEnd($separator) + $separator
    if (-not $Candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a path outside the backend build directory."
    }
}

$ScriptDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $PSCommandPath))
$DedicatedOutputDirectory = "dist-agent-mcp"
if ($OutputDirectory -cne $DedicatedOutputDirectory) {
    throw "Only the dedicated MCP output directory is allowed."
}
$OutputPath = Join-Path $ScriptDirectory $DedicatedOutputDirectory
Assert-ChildPath -ParentDirectory $ScriptDirectory -Candidate $OutputPath
$BuildPath = Join-Path $OutputPath "build"
$ConfigPath = Join-Path $OutputPath ".pyinstaller-cache"
$DesktopResourceDirectory = [IO.Path]::GetFullPath((Join-Path $ScriptDirectory "..\frontend\src-tauri\resources"))
$DesktopResourcePath = Join-Path $DesktopResourceDirectory "BiliOpinionAgentMcp.exe"
$Executable = Join-Path $OutputPath "BiliOpinionAgentMcp.exe"
$OriginalLocation = Get-Location
$OriginalPyInstallerConfig = $env:PYINSTALLER_CONFIG_DIR

try {
    # This script may be called from the frontend build script, whose working
    # directory is not backend.  Keep PyInstaller's relative spec and entry
    # paths anchored here, then restore the caller's process state below.
    Set-Location -LiteralPath $ScriptDirectory

    # Only this fixed, dedicated MCP output directory is removed. A failed
    # build never overwrites the last Tauri resource with an older artifact.
    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null
    New-Item -ItemType Directory -Force -Path $BuildPath, $ConfigPath, $DesktopResourceDirectory | Out-Null
    $env:PYINSTALLER_CONFIG_DIR = $ConfigPath
    $BuildStartedAt = [DateTime]::UtcNow

    & .\venv\Scripts\python.exe -m PyInstaller .\agent_mcp.spec `
        --noconfirm `
        --clean `
        --distpath $OutputPath `
        --workpath $BuildPath

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller MCP build failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Missing PyInstaller MCP executable."
    }

    $GeneratedItem = Get-Item -LiteralPath $Executable
    if ($GeneratedItem.LastWriteTimeUtc -lt $BuildStartedAt.AddSeconds(-2)) {
        throw "PyInstaller returned an outdated MCP executable."
    }

    Copy-Item -LiteralPath $Executable -Destination $DesktopResourcePath -Force
    $GeneratedHash = Get-Sha256Hex $Executable
    $ResourceHash = Get-Sha256Hex $DesktopResourcePath
    if ($GeneratedHash -ne $ResourceHash) {
        throw "Failed to copy the generated MCP executable to the Tauri resource path."
    }
}
finally {
    if ($null -eq $OriginalPyInstallerConfig) {
        Remove-Item Env:PYINSTALLER_CONFIG_DIR -ErrorAction SilentlyContinue
    }
    else {
        $env:PYINSTALLER_CONFIG_DIR = $OriginalPyInstallerConfig
    }
    Set-Location -LiteralPath $OriginalLocation.Path
}
