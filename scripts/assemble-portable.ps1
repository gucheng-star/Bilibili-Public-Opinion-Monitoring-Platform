[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Configuration = "release",
    [string]$OutputDirectory = "dist/portable"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopExecutable = Join-Path $projectRoot "frontend/src-tauri/target/$Configuration/bili-opinion-desktop.exe"
$outputRoot = Join-Path $projectRoot $OutputDirectory
$outputExecutable = Join-Path $outputRoot "BiliOpinionMonitor-$Version-windows-x64.exe"

if (-not (Test-Path -LiteralPath $desktopExecutable -PathType Leaf)) {
    throw "缺少单文件便携版主程序：$desktopExecutable"
}

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
if (Test-Path -LiteralPath $outputExecutable) {
    Remove-Item -LiteralPath $outputExecutable -Force
}
Copy-Item -LiteralPath $desktopExecutable -Destination $outputExecutable

$hash = (Get-FileHash -LiteralPath $outputExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output $outputExecutable
Write-Output "SHA256=$hash"
