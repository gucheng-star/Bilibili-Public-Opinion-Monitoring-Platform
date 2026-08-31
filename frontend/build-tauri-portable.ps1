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
$AgentMcpBuildScript = Join-Path $BackendRoot "build_agent_mcp.ps1"
$BackendOutputDirectory = "dist"
$AgentMcpOutputDirectory = "dist-agent-mcp"
Set-Location $FrontendRoot
$EmbeddedBackend = Join-Path $FrontendRoot "src-tauri/resources/BiliOpinionBackend.exe"
$EmbeddedAgentMcp = Join-Path $FrontendRoot "src-tauri/resources/BiliOpinionAgentMcp.exe"

if (-not (Test-Path -LiteralPath $BackendBuildScript -PathType Leaf)) {
    throw "Missing portable backend build script: $BackendBuildScript"
}
if (-not (Test-Path -LiteralPath $AgentMcpBuildScript -PathType Leaf)) {
    throw "Missing Agent MCP build script: $AgentMcpBuildScript"
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

# The stdio MCP server is a second internal Python component. Rebuild and
# verify it separately so the Tauri shell never embeds a stale copy.
& $AgentMcpBuildScript -OutputDirectory $AgentMcpOutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Agent MCP build failed with exit code $LASTEXITCODE"
}
Set-Location $FrontendRoot

$GeneratedAgentMcp = Join-Path $BackendRoot "$AgentMcpOutputDirectory/BiliOpinionAgentMcp.exe"
if (-not (Test-Path -LiteralPath $GeneratedAgentMcp -PathType Leaf)) {
    throw "Missing generated Agent MCP component: $GeneratedAgentMcp"
}
if (-not (Test-Path -LiteralPath $EmbeddedAgentMcp -PathType Leaf)) {
    throw "Missing copied embedded Agent MCP component: $EmbeddedAgentMcp"
}

$GeneratedAgentMcpHash = Get-Sha256Hex $GeneratedAgentMcp
$EmbeddedAgentMcpHash = Get-Sha256Hex $EmbeddedAgentMcp
if ($GeneratedAgentMcpHash -ne $EmbeddedAgentMcpHash) {
    throw "Embedded Agent MCP component does not match the component generated for this build."
}

# Tauri builds the single portable executable and embeds both the frontend and
# the two prebuilt Python components. The main executable also contains updater
# and stdio MCP routing modes.
& pnpm exec tauri build --no-bundle
if ($LASTEXITCODE -ne 0) {
    throw "Tauri build failed with exit code $LASTEXITCODE"
}
