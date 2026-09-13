[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$')]
    [string]$Version,
    [string]$ChangelogPath = "CHANGELOG.md",
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not (Test-Path -LiteralPath $ChangelogPath -PathType Leaf)) {
    throw "Missing changelog: $ChangelogPath"
}

$lines = [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $ChangelogPath))
$headerPattern = "^## \[" + [regex]::Escape($Version) + "\] - \d{4}-\d{2}-\d{2}\s*$"
$start = [Array]::FindIndex($lines, [Predicate[string]]{ param($line) $line -match $headerPattern })
if ($start -lt 0) {
    throw "No release section for $Version in $ChangelogPath"
}

$end = $lines.Length
for ($index = $start + 1; $index -lt $lines.Length; $index++) {
    if ($lines[$index] -match '^## \[') {
        $end = $index
        break
    }
}
$firstChange = $start + 1
$lastChange = $end - 1
while ($firstChange -le $lastChange -and [string]::IsNullOrWhiteSpace($lines[$firstChange])) { $firstChange++ }
while ($lastChange -ge $firstChange -and [string]::IsNullOrWhiteSpace($lines[$lastChange])) { $lastChange-- }
if ($firstChange -gt $lastChange) {
    throw "Release section for $Version has no user-facing changes"
}
$changes = @($lines[$firstChange..$lastChange])

$body = @(
    "## $Version 更新",
    ""
) + $changes + @(
    "",
    "## 升级提示",
    "",
    "请下载 ``BiliOpinionMonitor-$Version-windows-x64.exe`` 覆盖旧程序文件；不要删除或覆盖同级 ``data/`` 目录，其中保存本机数据库、登录信息、模型设置和日志。",
    "",
    "本版本仍为 0.x 预发布版本。请只从本仓库 Release 页面下载，并使用随发布生成的 ``latest-portable.json`` 核对文件大小与 SHA-256。"
)

$directory = Split-Path -Parent $OutputPath
if ($directory) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
[IO.File]::WriteAllLines($OutputPath, $body, [Text.UTF8Encoding]::new($false))
Write-Output "RELEASE_NOTES=$OutputPath"
