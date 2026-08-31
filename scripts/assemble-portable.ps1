[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Configuration = "release",
    [string]$OutputDirectory = "dist/portable"
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

$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopExecutable = Join-Path $projectRoot "frontend/src-tauri/target/$Configuration/bili-opinion-desktop.exe"
$cargoManifest = Join-Path $projectRoot "frontend/src-tauri/Cargo.toml"
$tauriConfig = Join-Path $projectRoot "frontend/src-tauri/tauri.conf.json"
$outputRoot = Join-Path $projectRoot $OutputDirectory
$outputExecutable = Join-Path $outputRoot "BiliOpinionMonitor-$Version-windows-x64.exe"

if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$') {
    throw "Version must be a semantic version: $Version"
}

$cargoVersionMatch = [regex]::Match(
    [IO.File]::ReadAllText($cargoManifest),
    '(?m)^version\s*=\s*"([^"]+)"'
)
if (-not $cargoVersionMatch.Success) {
    throw "Unable to read the package version from $cargoManifest"
}
$cargoVersion = $cargoVersionMatch.Groups[1].Value
$tauriVersion = ([IO.File]::ReadAllText($tauriConfig) | ConvertFrom-Json).version
if ($Version -ne $cargoVersion -or $Version -ne $tauriVersion) {
    throw "Release version mismatch: requested=$Version cargo=$cargoVersion tauri=$tauriVersion"
}

if (-not (Test-Path -LiteralPath $desktopExecutable -PathType Leaf)) {
    throw "Missing single-file portable desktop executable: $desktopExecutable"
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
if (Test-Path -LiteralPath $outputExecutable) {
    Remove-Item -LiteralPath $outputExecutable -Force
}
Copy-Item -LiteralPath $desktopExecutable -Destination $outputExecutable

if (-not (Test-Path -LiteralPath $outputExecutable -PathType Leaf)) {
    throw "Failed to create expected versioned portable executable: $outputExecutable"
}

$sourceHash = Get-Sha256Hex $desktopExecutable
$hash = Get-Sha256Hex $outputExecutable
if ($sourceHash -cne $hash) {
    throw "Versioned portable executable does not match the Tauri build output."
}
Write-Output $outputExecutable
Write-Output "SHA256=$hash"
