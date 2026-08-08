[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [Parameter(Mandatory = $true)] [string]$ArchivePath,
    [Parameter(Mandatory = $true)] [string]$ReleaseBaseUrl,
    [Parameter(Mandatory = $true)] [string]$NotesUrl,
    [Parameter(Mandatory = $true)] [string]$SignatureBase64,
    [Parameter(Mandatory = $true)] [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$archive = Get-Item -LiteralPath $ArchivePath
$hash = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schema = 1
    version = $Version
    published_at = [DateTime]::UtcNow.ToString("o")
    notes_url = $NotesUrl
    asset = [ordered]@{
        name = $archive.Name
        url = "$($ReleaseBaseUrl.TrimEnd('/'))/$($archive.Name)"
        size = [UInt64]$archive.Length
        sha256 = $hash
    }
    minimum_windows = "10.0.17134"
    signature = $SignatureBase64
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
