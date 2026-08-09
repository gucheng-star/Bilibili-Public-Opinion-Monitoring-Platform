[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [Parameter(Mandatory = $true)] [string]$AssetPath,
    [Parameter(Mandatory = $true)] [string]$ReleaseBaseUrl,
    [Parameter(Mandatory = $true)] [string]$NotesUrl,
    [Parameter(Mandatory = $true)] [string]$SignatureBase64,
    [Parameter(Mandatory = $true)] [string]$OutputPath
)

$ErrorActionPreference = "Stop"

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

$asset = Get-Item -LiteralPath $AssetPath
$hash = Get-Sha256Hex $asset.FullName
$manifest = [ordered]@{
    schema = 1
    version = $Version
    published_at = [DateTime]::UtcNow.ToString("o")
    notes_url = $NotesUrl
    asset = [ordered]@{
        name = $asset.Name
        url = "$($ReleaseBaseUrl.TrimEnd('/'))/$($asset.Name)"
        size = [UInt64]$asset.Length
        sha256 = $hash
    }
    minimum_windows = "10.0.17134"
    signature = $SignatureBase64
}
$json = $manifest | ConvertTo-Json -Depth 4
[IO.File]::WriteAllText(
    [IO.Path]::GetFullPath($OutputPath),
    $json,
    [Text.UTF8Encoding]::new($false)
)
