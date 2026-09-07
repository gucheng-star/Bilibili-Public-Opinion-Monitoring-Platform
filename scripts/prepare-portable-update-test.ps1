[CmdletBinding()]
param(
    [int]$Port = 18443,
    [string]$TestRoot = (Join-Path $env:TEMP "bili-opinion-update-test")
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\venv\Scripts\python.exe"
$assetName = "BiliOpinionMonitor-0.2.2-windows-x64.exe"
$testCurrentVersion = "0.2.1"
$serverRoot = Join-Path $TestRoot "server"
$installRoot = Join-Path $TestRoot "install"
$server = $null

if (Test-Path -LiteralPath $TestRoot) {
    throw "Test directory already exists: $TestRoot. Remove it only after stopping prior test processes."
}
foreach ($path in @($TestRoot, $serverRoot, $installRoot)) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}

try {
    $fixtureTool = Join-Path $projectRoot "scripts\portable_update_test_fixture.py"
    $fixture = & $python $fixtureTool init --root $TestRoot | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Test fixture initialization failed" }
    $publicKeyBase64 = $fixture.public_key_b64
    $caBase64 = $fixture.ca_pem_b64
    $previous = @{
        BILI_PORTABLE_UPDATE_PUBLIC_KEY = $env:BILI_PORTABLE_UPDATE_PUBLIC_KEY
        BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64 = $env:BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64
        BILI_PORTABLE_UPDATE_TEST_CURRENT_VERSION = $env:BILI_PORTABLE_UPDATE_TEST_CURRENT_VERSION
    }
    $env:BILI_PORTABLE_UPDATE_PUBLIC_KEY = $publicKeyBase64
    $env:BILI_PORTABLE_UPDATE_TEST_CA_PEM_BASE64 = $caBase64
    $env:BILI_PORTABLE_UPDATE_TEST_CURRENT_VERSION = $testCurrentVersion
    try { & pnpm --dir "$projectRoot\frontend" run tauri:build; if ($LASTEXITCODE -ne 0) { throw "Test EXE build failed" } }
    finally { foreach ($name in $previous.Keys) { if ($null -eq $previous[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $previous[$name] } } }
    $built = "$projectRoot\frontend\src-tauri\target\release\bili-opinion-desktop.exe"
    Copy-Item -LiteralPath $built -Destination "$TestRoot\server\$assetName"
    Copy-Item -LiteralPath $built -Destination "$TestRoot\install\$assetName"
    $asset = Get-Item "$TestRoot\server\$assetName"
    & $python $fixtureTool manifest --root $TestRoot --asset $asset.FullName --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Test manifest signing failed" }
    $serverLog = Join-Path $TestRoot "update-server.log"
    $serverErrorLog = Join-Path $TestRoot "update-server-error.log"
    $serverArguments = "`"$projectRoot\scripts\serve-portable-update-test.py`" --directory `"$TestRoot\server`" --port $Port --cert `"$TestRoot\tls-cert.pem`" --key `"$TestRoot\tls-key.pem`""
    $server = Start-Process -FilePath $python -ArgumentList $serverArguments -WindowStyle Hidden -RedirectStandardOutput $serverLog -RedirectStandardError $serverErrorLog -PassThru
    Start-Sleep -Milliseconds 500
    if ($server.HasExited) {
        $serverFailure = if (Test-Path -LiteralPath $serverErrorLog) { Get-Content -LiteralPath $serverErrorLog -Raw } else { "no server error output" }
        throw "Test update server exited early: $serverFailure"
    }
    $previousManifest = $env:BILI_PORTABLE_UPDATE_MANIFEST_URL
    $env:BILI_PORTABLE_UPDATE_MANIFEST_URL = "https://127.0.0.1:$Port/latest-portable.json"
    try {
        $testRun = Start-Process -FilePath "$TestRoot\install\$assetName" -ArgumentList "--portable-update-self-test" -WorkingDirectory "$TestRoot\install" -PassThru
        Wait-Process -Id $testRun.Id -Timeout 90 -ErrorAction Stop
        $testRun.Refresh()
        if ($testRun.ExitCode -ne 0) { throw "Update self-test exited with code $($testRun.ExitCode)" }
    }
    finally { if ($null -eq $previousManifest) { Remove-Item Env:BILI_PORTABLE_UPDATE_MANIFEST_URL -ErrorAction SilentlyContinue } else { Set-Item Env:BILI_PORTABLE_UPDATE_MANIFEST_URL $previousManifest } }
    $healthy = Join-Path $TestRoot "install\data\update-cache\healthy-version.json"
    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Path -LiteralPath $healthy) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Path -LiteralPath $healthy)) { throw "Updated program did not report healthy startup within 90 seconds" }
    $health = Get-Content -LiteralPath $healthy -Raw | ConvertFrom-Json
    if ($health.version -ne "0.2.2") { throw "Updated program reported unexpected version: $($health.version)" }
    Write-Output "TEST_ROOT=$TestRoot"
    Write-Output "UPDATE_TEST=PASS"
    Write-Output "UPDATED_VERSION=$($health.version)"
    Write-Output "UPDATE_LOG=$(Join-Path $TestRoot 'install\data\logs\update.log')"
}
finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
}
