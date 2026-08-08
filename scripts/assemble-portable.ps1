[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$Configuration = "release",
    [string]$OutputDirectory = "dist/portable"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$desktopTarget = Join-Path $projectRoot "frontend/src-tauri/target/$Configuration"
$backendDist = Join-Path $projectRoot "backend/dist/BiliOpinionBackend"
$stageRoot = Join-Path $projectRoot "$OutputDirectory/BiliOpinionMonitor-$Version-windows-x64"
$archivePath = Join-Path $projectRoot "$OutputDirectory/BiliOpinionMonitor-$Version-windows-x64.zip"

foreach ($required in @(
    (Join-Path $desktopTarget "bili-opinion-desktop.exe"),
    (Join-Path $desktopTarget "BiliOpinionUpdater.exe"),
    (Join-Path $backendDist "BiliOpinionBackend.exe"),
    (Join-Path $projectRoot "PORTABLE-README.txt"),
    (Join-Path $projectRoot "LICENSE")
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "缺少便携发布所需文件：$required"
    }
}

if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $desktopTarget "bili-opinion-desktop.exe") -Destination (Join-Path $stageRoot "BiliOpinionMonitor.exe")
Copy-Item -LiteralPath (Join-Path $desktopTarget "BiliOpinionUpdater.exe") -Destination (Join-Path $stageRoot "BiliOpinionUpdater.exe")
Copy-Item -LiteralPath $backendDist -Destination (Join-Path $stageRoot "backend") -Recurse
New-Item -ItemType Directory -Path (Join-Path $stageRoot "data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stageRoot "data/logs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stageRoot "data/webview") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stageRoot "data/update-cache") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "portable.ini.example") -Destination (Join-Path $stageRoot "portable.ini")
Copy-Item -LiteralPath (Join-Path $projectRoot "PORTABLE-README.txt") -Destination (Join-Path $stageRoot "README.txt")
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination (Join-Path $stageRoot "LICENSE")

New-Item -ItemType Directory -Path (Split-Path -Parent $archivePath) -Force | Out-Null
Compress-Archive -LiteralPath $stageRoot -DestinationPath $archivePath -CompressionLevel Optimal
Write-Output $archivePath
