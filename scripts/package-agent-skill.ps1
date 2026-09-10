[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$')]
    [string]$Version,
    [string]$OutputDirectory = "dist/agent-skill"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-Sha256Hex([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    }
    finally { $stream.Dispose() }
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
$allowedOutputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist"))
$separator = [IO.Path]::DirectorySeparatorChar
if (-not $outputRoot.StartsWith($allowedOutputRoot.TrimEnd($separator) + $separator, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must stay inside the repository dist directory."
}

$relativeFiles = @(
    "skills/bili-opinion/SKILL.md",
    "skills/bili-opinion/references/setup.md",
    "skills/bili-opinion/references/workflows.md",
    "skills/bili-opinion/references/troubleshooting.md",
    "skills/bili-opinion/evals/evals.json",
    "docs/mcp/README.md",
    "docs/mcp/contract.md"
)
foreach ($relative in $relativeFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relative) -PathType Leaf)) {
        throw "Required package source is missing."
    }
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$baseName = "bili-opinion-skill-$Version"
$zipPath = Join-Path $outputRoot "$baseName.zip"
$manifestPath = Join-Path $outputRoot "$baseName.manifest.json"
$hashPath = Join-Path $outputRoot "$baseName.sha256"

$contents = foreach ($relative in $relativeFiles) {
    $source = Join-Path $projectRoot $relative
    [ordered]@{ path = $relative.Replace("\\", "/"); bytes = (Get-Item -LiteralPath $source).Length; sha256 = Get-Sha256Hex $source }
}
$manifest = [ordered]@{
    package = "bili-opinion-skill"
    version = $Version
    mcp_contract_version = 2
    contents = @($contents)
}
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))

if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
$archive = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $packageTimestamp = [DateTimeOffset]::new(1980, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
    foreach ($relative in $relativeFiles + @((Split-Path -Leaf $manifestPath))) {
        $source = if ($relative -eq (Split-Path -Leaf $manifestPath)) { $manifestPath } else { Join-Path $projectRoot $relative }
        $entryName = if ($source -eq $manifestPath) { "manifest.json" } else { $relative.Replace("\\", "/") }
        $entry = $archive.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = $packageTimestamp
        $input = [IO.File]::OpenRead($source)
        $output = $entry.Open()
        try { $input.CopyTo($output) }
        finally {
            $output.Dispose()
            $input.Dispose()
        }
    }
}
finally { $archive.Dispose() }

$zipHash = Get-Sha256Hex $zipPath
[IO.File]::WriteAllText($hashPath, "$zipHash  $(Split-Path -Leaf $zipPath)`n", [Text.UTF8Encoding]::new($false))
Write-Output "PACKAGE=$zipPath"
Write-Output "MANIFEST=$manifestPath"
Write-Output "SHA256=$zipHash"
