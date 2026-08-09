$ErrorActionPreference = "Stop"
$FrontendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $FrontendRoot
$EmbeddedBackend = Join-Path $FrontendRoot "src-tauri/resources/BiliOpinionBackend.exe"

if (-not (Test-Path -LiteralPath $EmbeddedBackend -PathType Leaf)) {
    throw "Missing embedded backend: $EmbeddedBackend. Build the portable backend first."
}

# Tauri builds the single portable executable and embeds both the frontend and
# the prebuilt Python backend. The main executable also contains updater mode.
& pnpm exec tauri build --no-bundle
if ($LASTEXITCODE -ne 0) {
    throw "Tauri build failed with exit code $LASTEXITCODE"
}
