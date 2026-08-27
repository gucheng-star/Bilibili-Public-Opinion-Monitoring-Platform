[CmdletBinding()]
param(
    [string]$Session = "latest",
    [ValidateSet("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")]
    [string]$Level = "WARNING",
    [DateTimeOffset]$Since,
    [DateTimeOffset]$Until,
    [string]$RequestId,
    [string]$AnalysisId,
    [ValidateRange(1, 5000)]
    [int]$Tail = 200,
    [ValidateRange(0, 100)]
    [int]$Context = 5
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$script:levelRanks = @{ DEBUG = 0; INFO = 1; WARNING = 2; ERROR = 3; CRITICAL = 4 }
$script:sessionPattern = '^\d{8}-\d{6}-[0-9a-f]{6}$'
$script:requestIdPattern = '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'
$script:logNames = @("launcher.log.1", "launcher.log", "backend.log.1", "backend.log", "frontend.log.1", "frontend.log")
$script:convertFromJsonParameters = (Get-Command ConvertFrom-Json).Parameters
$script:supportsJsonDepth = $script:convertFromJsonParameters.ContainsKey("Depth")
$script:supportsJsonDateKind = $script:convertFromJsonParameters.ContainsKey("DateKind")
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$devLogsRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "logs\dev"))
$script:devLogsPrefix = $devLogsRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar

function Get-EntryProperty([object]$Entry, [string]$Name) {
    if ($null -eq $Entry) { return $null }
    $property = $Entry.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Protect-Text([object]$Value, [int]$MaximumLength = 1200) {
    if ($null -eq $Value) { return "" }
    $text = [string]$Value
    $text = [regex]::Replace($text, '\x1B(?:\[[0-?]*[ -/]*[@-~]|[@-_])', '')
    $text = [regex]::Replace($text, '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '')
    $text = $text -replace '[\r\n\t]+', ' '
    # Do not preserve a sensitive field name either: logs are diagnostic input, not trusted display data.
    $text = [regex]::Replace($text, '(?i)(?:api[_-]?key|token|secret|password|passwd|cookie|sessdata|bili_jct|qrcode[_-]?key|authorization)\s*[:=]\s*[^\s,;\]\}]+', '<敏感字段>=<已隐藏>')
    $text = [regex]::Replace($text, '(?i)bearer\s+[^\s,;\]\}]+', 'Bearer <已隐藏>')
    $text = [regex]::Replace($text, '(?i)([?&])(?:api[_-]?key|token|secret|password|passwd|cookie|sessdata|bili_jct|qrcode[_-]?key|authorization)=[^&\s]+', '$1<敏感参数>=<已隐藏>')
    $text = [regex]::Replace($text, '(?i)(?<![A-Za-z0-9_])(?:api[_-]?key|token|secret|password|passwd|cookie|sessdata|bili_jct|qrcode[_-]?key|authorization)(?![A-Za-z0-9_])', '<敏感字段>')
    if ($text.Length -gt $MaximumLength) { return $text.Substring(0, $MaximumLength) + "…" }
    return $text
}

function Get-SafeScalar([object]$Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [string] -or $Value -is [ValueType]) { return (Protect-Text $Value 300) }
    return $null
}

function Assert-PathInDevLogs([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($script:devLogsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝访问 logs/dev 之外的路径：$absolute"
    }
    if (-not (Test-Path -LiteralPath $absolute)) { return $absolute }
    # Resolve once as a second containment check. Reparse points are rejected by callers before use.
    $resolved = (Resolve-Path -LiteralPath $absolute -ErrorAction Stop).ProviderPath
    if (-not $resolved.StartsWith($script:devLogsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝访问解析后位于 logs/dev 之外的路径：$resolved"
    }
    return $absolute
}

function Test-ReparsePoint([IO.FileSystemInfo]$Item) {
    return (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Assert-SafeDevLogsRoot {
    if (-not (Test-Path -LiteralPath $devLogsRoot -PathType Container)) {
        throw "开发日志目录不存在：$devLogsRoot"
    }
    $item = Get-Item -LiteralPath $devLogsRoot -Force -ErrorAction Stop
    if (Test-ReparsePoint $item) { throw "拒绝重解析点日志根目录：$devLogsRoot" }
    $resolved = (Resolve-Path -LiteralPath $item.FullName -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
    $expected = $devLogsRoot.TrimEnd('\', '/')
    if (-not $resolved.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝解析后偏离项目 logs/dev 的日志根目录：$resolved"
    }
    return $item
}

function Read-SharedLogLines([string]$Path) {
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
    $reader = [IO.StreamReader]::new($stream, [Text.UTF8Encoding]::new($false), $true)
    try {
        while (-not $reader.EndOfStream) { Write-Output $reader.ReadLine() }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Get-SessionLogFiles([IO.DirectoryInfo]$SessionDirectory) {
    if (Test-ReparsePoint $SessionDirectory) { throw "拒绝重解析点会话目录：$($SessionDirectory.FullName)" }
    [void](Assert-PathInDevLogs $SessionDirectory.FullName)
    $files = [Collections.Generic.List[object]]::new()
    $order = 0
    foreach ($name in $script:logNames) {
        $candidate = Assert-PathInDevLogs (Join-Path $SessionDirectory.FullName $name)
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
            if (Test-ReparsePoint $item) { throw "拒绝重解析点日志文件：$candidate" }
            if ($item.PSIsContainer) { throw "固定日志路径不是文件：$candidate" }
            [void](Assert-PathInDevLogs $item.FullName)
            $files.Add([pscustomobject]@{ Item = $item; Order = $order })
        }
        $order++
    }
    return $files
}

function Convert-ToLogTimestamp([object]$Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [DateTimeOffset]) { return $Value }
    if ($Value -is [DateTime]) { return [DateTimeOffset]$Value }
    $parsed = [DateTimeOffset]::MinValue
    if ([DateTimeOffset]::TryParse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind, [ref]$parsed)) {
        return $parsed
    }
    return $null
}

function ConvertFrom-LogJson([string]$Line) {
    if ($script:supportsJsonDateKind) {
        return ($Line | ConvertFrom-Json -ErrorAction Stop -Depth 32 -DateKind String)
    }
    if ($script:supportsJsonDepth) {
        return ($Line | ConvertFrom-Json -ErrorAction Stop -Depth 32)
    }
    return ($Line | ConvertFrom-Json -ErrorAction Stop)
}

function Get-SessionLatestWriteTime([IO.DirectoryInfo]$SessionDirectory) {
    $latest = $SessionDirectory.LastWriteTimeUtc
    foreach ($fileInfo in (Get-SessionLogFiles $SessionDirectory)) {
        if ($fileInfo.Item.LastWriteTimeUtc -gt $latest) { $latest = $fileInfo.Item.LastWriteTimeUtc }
    }
    return $latest
}

function Get-LogFileSnapshot([IO.DirectoryInfo]$SessionDirectory) {
    $files = @(Get-SessionLogFiles $SessionDirectory)
    $parts = [Collections.Generic.List[string]]::new()
    foreach ($fileInfo in $files) {
        $item = Get-Item -LiteralPath $fileInfo.Item.FullName -Force -ErrorAction Stop
        if (Test-ReparsePoint $item) { throw "拒绝重解析点日志文件：$($item.FullName)" }
        [void](Assert-PathInDevLogs $item.FullName)
        $parts.Add("$($fileInfo.Order)|$($item.Name)|$($item.Length)|$($item.LastWriteTimeUtc.Ticks)")
    }
    return [pscustomobject]@{
        Files = $files
        Signature = ($parts -join "`n")
    }
}

function Read-SessionRecordsOnce([IO.DirectoryInfo]$SessionDirectory) {
    $before = Get-LogFileSnapshot $SessionDirectory
    $badJson = 0
    $badTimestamp = 0
    $badLevel = 0
    $records = [Collections.Generic.List[object]]::new()
    foreach ($fileInfo in $before.Files) {
        $lineNumber = 0
        foreach ($line in (Read-SharedLogLines $fileInfo.Item.FullName)) {
            $lineNumber++
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try { $entry = ConvertFrom-LogJson $line }
            catch { $badJson++; continue }
            $timestamp = Convert-ToLogTimestamp (Get-EntryProperty $entry "timestamp")
            if ($null -eq $timestamp) { $badTimestamp++; continue }
            $entryLevel = [string](Get-EntryProperty $entry "level")
            $entryLevel = $entryLevel.ToUpperInvariant()
            if (-not $script:levelRanks.ContainsKey($entryLevel)) { $badLevel++; continue }
            $records.Add([pscustomobject]@{
                Timestamp = $timestamp; Level = $entryLevel; Component = [string](Get-EntryProperty $entry "component")
                Raw = $entry; FileOrder = $fileInfo.Order; LineNumber = $lineNumber; Index = -1
            })
        }
    }
    $after = Get-LogFileSnapshot $SessionDirectory
    return [pscustomobject]@{
        Records = @($records)
        BadJson = $badJson
        BadTimestamp = $badTimestamp
        BadLevel = $badLevel
        Changed = ($before.Signature -ne $after.Signature)
    }
}

function Test-TransientLogReadFailure([object]$ErrorRecord) {
    $exception = Get-EntryProperty $ErrorRecord "Exception"
    while ($null -ne $exception) {
        if ($exception -is [IO.IOException] -or $exception -is [Management.Automation.ItemNotFoundException]) {
            return $true
        }
        $exception = $exception.InnerException
    }
    return $false
}

function Get-FilterSources([object]$Entry) {
    $sources = [Collections.Generic.List[object]]::new()
    $sources.Add($Entry)
    $state = Get-EntryProperty $Entry "state"
    if ($null -ne $state) { $sources.Add($state) }
    $details = Get-EntryProperty $Entry "details"
    if ($null -ne $details) { $sources.Add($details) }
    $breadcrumbs = @(Get-EntryProperty $Entry "breadcrumbs")
    if ($breadcrumbs.Count -gt 0) {
        foreach ($breadcrumb in $breadcrumbs) { if ($null -ne $breadcrumb) { $sources.Add($breadcrumb) } }
    }
    return $sources
}

function Get-WhitelistedValues([object]$Entry, [string[]]$Names) {
    $values = [Collections.Generic.List[string]]::new()
    foreach ($source in (Get-FilterSources $Entry)) {
        foreach ($name in $Names) {
            $safe = Get-SafeScalar (Get-EntryProperty $source $name)
            if ($null -ne $safe -and -not $values.Contains($safe)) { $values.Add($safe) }
        }
    }
    return $values
}

function Test-EntryMatch([object]$Entry, [DateTimeOffset]$Timestamp, [string]$EntryLevel, [Nullable[Int64]]$RequestedAnalysisId) {
    if ($script:levelRanks[$EntryLevel] -lt $script:levelRanks[$Level]) { return $false }
    if ($script:hasSince -and $Timestamp -lt $Since) { return $false }
    if ($script:hasUntil -and $Timestamp -gt $Until) { return $false }
    if ($script:hasRequestId) {
        $requestValues = Get-WhitelistedValues $Entry @("request_id", "requestId")
        if (-not (@($requestValues | Where-Object { $_ -ieq $RequestId }).Count -gt 0)) { return $false }
    }
    if ($null -ne $RequestedAnalysisId) {
        $matched = $false
        foreach ($value in (Get-WhitelistedValues $Entry @("analysis_id", "analysisId"))) {
            $parsed = 0L
            if ([Int64]::TryParse($value, [ref]$parsed) -and $parsed -eq [Int64]$RequestedAnalysisId) { $matched = $true; break }
        }
        if (-not $matched) { return $false }
    }
    return $true
}

function Get-SessionMetadata([object[]]$Records) {
    foreach ($record in $Records) {
        if ((Get-EntryProperty $record.Raw "event") -ne "launcher.session_started") { continue }
        $details = Get-EntryProperty $record.Raw "details"
        if ($null -eq $details) { break }
        return [pscustomobject]@{
            Branch = (Get-SafeScalar (Get-EntryProperty $details "branch"))
            Commit = (Get-SafeScalar (Get-EntryProperty $details "commit"))
            Dirty = (Get-SafeScalar (Get-EntryProperty $details "dirty"))
        }
    }
    return [pscustomobject]@{ Branch = $null; Commit = $null; Dirty = $null }
}

function Format-Values([string]$Label, [Collections.Generic.List[string]]$Values) {
    if ($Values.Count -eq 0) { return $null }
    return "$Label=" + ($Values -join ",")
}

function Write-LogRecord([object]$Record, [bool]$IsContext) {
    $entry = $Record.Raw
    $prefix = if ($IsContext) { "[上下文] " } else { "" }
    $event = Get-SafeScalar (Get-EntryProperty $entry "event")
    $message = Get-SafeScalar (Get-EntryProperty $entry "message")
    if ([string]::IsNullOrWhiteSpace($event)) { $event = "-" }
    if ([string]::IsNullOrWhiteSpace($message)) { $message = "-" }
    Write-Output ("{0}{1} [{2}] [{3}] {4} - {5}" -f $prefix, $Record.Timestamp.ToString("yyyy-MM-dd HH:mm:ss.fff zzz"), $Record.Level, (Protect-Text $Record.Component 100), $event, $message)

    $parts = [Collections.Generic.List[string]]::new()
    $requestIds = Get-WhitelistedValues $entry @("request_id", "requestId")
    $analysisIds = Get-WhitelistedValues $entry @("analysis_id", "analysisId")
    $stages = Get-WhitelistedValues $entry @("stage")
    $statuses = Get-WhitelistedValues $entry @("status")
    foreach ($part in @(
        (Format-Values "请求ID" $requestIds),
        (Format-Values "分析ID" $analysisIds),
        (Format-Values "阶段" $stages),
        (Format-Values "状态" $statuses)
    )) { if ($null -ne $part) { $parts.Add($part) } }
    if ($parts.Count -gt 0) { Write-Output ("  " + ($parts -join "；")) }

    $stack = Get-SafeScalar (Get-EntryProperty $entry "stack")
    if ($null -ne $stack) { Write-Output ("  堆栈摘要：" + (Protect-Text $stack 600)) }

    $crumbs = @(Get-EntryProperty $entry "breadcrumbs")
    if ($crumbs.Count -gt 0) {
        $summaries = [Collections.Generic.List[string]]::new()
        foreach ($crumb in $crumbs) {
            $crumbParts = [Collections.Generic.List[string]]::new()
            foreach ($name in @("event", "path", "method", "request_id", "requestId", "analysis_id", "analysisId", "stage", "status", "duration_ms")) {
                $value = Get-SafeScalar (Get-EntryProperty $crumb $name)
                if ($null -ne $value) { $crumbParts.Add("$name=" + (Protect-Text $value 160)) }
            }
            if ($crumbParts.Count -gt 0) { $summaries.Add(($crumbParts -join ",")) }
        }
        if ($summaries.Count -gt 0) { Write-Output ("  面包屑摘要：" + (($summaries -join " | ") | Select-Object -First 1)) }
    }

    $state = Get-EntryProperty $entry "state"
    if ($null -ne $state) {
        $stateParts = [Collections.Generic.List[string]]::new()
        foreach ($name in @("route", "view_type", "analysis_mode", "keyword_status", "loading", "reanalyzing", "stage", "status")) {
            $value = Get-SafeScalar (Get-EntryProperty $state $name)
            if ($null -ne $value) { $stateParts.Add("$name=" + (Protect-Text $value 160)) }
        }
        if ($stateParts.Count -gt 0) { Write-Output ("  前端状态摘要：" + ($stateParts -join ",")) }
    }
}

if ($Session -ne "latest" -and $Session -notmatch $script:sessionPattern) {
    throw "Session 只能是 latest 或严格会话 ID（yyyyMMdd-HHmmss-6位十六进制）。"
}
if ($PSBoundParameters.ContainsKey("RequestId") -and $RequestId -notmatch $script:requestIdPattern) {
    throw "RequestId 格式不安全；只允许 1 至 128 位字母、数字、下划线或连字符，且首位必须是字母或数字。"
}
$requestedAnalysisId = $null
if ($PSBoundParameters.ContainsKey("AnalysisId")) {
    $parsedAnalysisId = 0L
    if ($AnalysisId -notmatch '^[1-9]\d*$' -or -not [Int64]::TryParse($AnalysisId, [ref]$parsedAnalysisId)) {
        throw "AnalysisId 必须是正整数。"
    }
    $requestedAnalysisId = [Nullable[Int64]]$parsedAnalysisId
}
if ($PSBoundParameters.ContainsKey("Since") -and $PSBoundParameters.ContainsKey("Until") -and $Since -gt $Until) {
    throw "Since 不能晚于 Until。"
}
$script:hasSince = $PSBoundParameters.ContainsKey("Since")
$script:hasUntil = $PSBoundParameters.ContainsKey("Until")
$script:hasRequestId = $PSBoundParameters.ContainsKey("RequestId")
$devLogsItem = Assert-SafeDevLogsRoot

$sessionDirectory = $null
if ($Session -eq "latest") {
    $candidates = [Collections.Generic.List[object]]::new()
    foreach ($directory in (Get-ChildItem -LiteralPath $devLogsRoot -Directory -Force | Where-Object { $_.Name -match $script:sessionPattern })) {
        if (Test-ReparsePoint $directory) { continue }
        try {
            $writeTime = Get-SessionLatestWriteTime $directory
            $candidates.Add([pscustomobject]@{ Directory = $directory; WriteTime = $writeTime; Name = $directory.Name })
        }
        catch { Write-Warning "已跳过不安全的会话目录：$($directory.Name)" }
    }
    if ($candidates.Count -eq 0) { throw "logs/dev 中没有可读取的开发会话。" }
    $sessionDirectory = ($candidates | Sort-Object @{ Expression = "WriteTime"; Descending = $true }, @{ Expression = "Name"; Descending = $true } | Select-Object -First 1).Directory
}
else {
    $candidate = Assert-PathInDevLogs (Join-Path $devLogsRoot $Session)
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { throw "开发会话不存在：$Session" }
    $sessionDirectory = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
    if (Test-ReparsePoint $sessionDirectory) { throw "拒绝重解析点会话目录：$candidate" }
    [void](Assert-PathInDevLogs $sessionDirectory.FullName)
}

$readResult = $null
for ($attempt = 0; $attempt -lt 2; $attempt++) {
    try {
        $readResult = Read-SessionRecordsOnce $sessionDirectory
    }
    catch {
        if ($attempt -eq 0 -and (Test-TransientLogReadFailure $_)) {
            Write-Warning "检测到读取期间日志文件发生轮转，正在重试一次。"
            continue
        }
        throw
    }
    if (-not $readResult.Changed) { break }
    if ($attempt -eq 0) {
        Write-Warning "检测到读取期间日志发生轮转或写入，正在重试一次。"
    }
    else {
        Write-Warning "重试期间日志仍在变化；输出第二次读取到的有界快照。"
    }
}
$badJson = $readResult.BadJson
$badTimestamp = $readResult.BadTimestamp
$badLevel = $readResult.BadLevel
$records = @($readResult.Records)

$orderedRecords = @($records | Sort-Object Timestamp, FileOrder, LineNumber)
for ($i = 0; $i -lt $orderedRecords.Count; $i++) { $orderedRecords[$i].Index = $i }
$metadata = Get-SessionMetadata $orderedRecords
$range = if ($orderedRecords.Count -eq 0) { "无有效日志" } else { "{0} 至 {1}" -f $orderedRecords[0].Timestamp.ToString("yyyy-MM-dd HH:mm:ss.fff zzz"), $orderedRecords[-1].Timestamp.ToString("yyyy-MM-dd HH:mm:ss.fff zzz") }
$matches = @($orderedRecords | Where-Object { Test-EntryMatch $_.Raw $_.Timestamp $_.Level $requestedAnalysisId })
$selectedMatches = @($matches | Select-Object -Last $Tail)
$selectedIndexes = [Collections.Generic.HashSet[int]]::new()
$primaryIndexes = [Collections.Generic.HashSet[int]]::new()
foreach ($match in $selectedMatches) {
    $index = $match.Index
    if ($index -ge 0) {
        [void]$primaryIndexes.Add($index)
        $start = [Math]::Max(0, $index - $Context)
        $end = [Math]::Min($orderedRecords.Count - 1, $index + $Context)
        for ($i = $start; $i -le $end; $i++) { [void]$selectedIndexes.Add($i) }
    }
}

Write-Output ("会话：" + $sessionDirectory.Name)
Write-Output ("分支/commit/dirty：{0} / {1} / {2}" -f $(if ($null -ne $metadata.Branch) { $metadata.Branch } else { "-" }), $(if ($null -ne $metadata.Commit) { $metadata.Commit } else { "-" }), $(if ($null -ne $metadata.Dirty) { $metadata.Dirty } else { "-" }))
Write-Output ("日志范围：" + $range)
Write-Output ("命中/显示/损坏：{0} / {1} / JSON {2}，时间戳 {3}，级别 {4}" -f $matches.Count, $selectedIndexes.Count, $badJson, $badTimestamp, $badLevel)

if ($orderedRecords.Count -eq 0) {
    Write-Output "此会话没有可解析的日志记录。"
    return
}
if ($matches.Count -eq 0) {
    Write-Output "没有符合筛选条件的日志记录。"
    return
}
for ($i = 0; $i -lt $orderedRecords.Count; $i++) {
    if ($selectedIndexes.Contains($i)) { Write-LogRecord $orderedRecords[$i] (-not $primaryIndexes.Contains($i)) }
}
