[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$sourceReader = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\read-dev-logs.ps1"))
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ("bili-read-dev-logs-" + [guid]::NewGuid().ToString("N"))))
$sandboxRoot = Join-Path $temporaryRoot "project"
$sandboxScripts = Join-Path $sandboxRoot "scripts"
$sandboxLogs = Join-Path $sandboxRoot "logs\dev"
$reader = Join-Path $sandboxScripts "read-dev-logs.ps1"
$script:assertions = 0

function Assert-True([bool]$Condition, [string]$Message) {
    $script:assertions++
    if (-not $Condition) { throw "断言失败：$Message" }
}

function Assert-Contains([string]$Text, [string]$Expected, [string]$Message) {
    Assert-True $Text.Contains($Expected) "$Message，缺少：$Expected"
}

function Assert-NotContains([string]$Text, [string]$Unexpected, [string]$Message) {
    Assert-True (-not $Text.Contains($Unexpected)) "$Message，意外出现：$Unexpected"
}

function Write-JsonLines([string]$Path, [object[]]$Entries, [string[]]$RawLines = @()) {
    $lines = [Collections.Generic.List[string]]::new()
    foreach ($entry in $Entries) { $lines.Add(($entry | ConvertTo-Json -Compress -Depth 12)) }
    foreach ($line in $RawLines) { $lines.Add($line) }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path, (($lines -join [Environment]::NewLine) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}

function Get-FileSnapshot([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "") }
        finally { $sha.Dispose() }
    }
    finally { $stream.Dispose() }
    $item = Get-Item -LiteralPath $Path
    return [pscustomobject]@{ Hash = $hash; Length = $item.Length; LastWriteTicks = $item.LastWriteTimeUtc.Ticks }
}

function Invoke-Reader([hashtable]$Arguments = @{}, [string]$WorkingDirectory = $sandboxRoot) {
    Push-Location $WorkingDirectory
    try { return ((& $reader @Arguments *>&1) | Out-String) }
    finally { Pop-Location }
}

try {
    [IO.Directory]::CreateDirectory($sandboxScripts) | Out-Null
    [IO.Directory]::CreateDirectory($sandboxLogs) | Out-Null
    Copy-Item -LiteralPath $sourceReader -Destination $reader

    $sessionA = "20260101-000000-aaaaaa"
    $sessionB = "20260102-000000-bbbbbb"
    $sessionAPath = Join-Path $sandboxLogs $sessionA
    $sessionBPath = Join-Path $sandboxLogs $sessionB
    [IO.Directory]::CreateDirectory($sessionAPath) | Out-Null
    [IO.Directory]::CreateDirectory($sessionBPath) | Out-Null

    Write-JsonLines (Join-Path $sessionAPath "launcher.log") @(
        [ordered]@{ timestamp="2026-01-01T00:00:01+00:00"; level="INFO"; component="launcher"; event="launcher.session_started"; dev_session_id=$sessionA; message="started"; details=[ordered]@{ branch="codex/dev-diagnostics"; commit="abc1234"; dirty=$true; stage="session_started" } }
    )
    Write-JsonLines (Join-Path $sessionAPath "backend.log.1") @(
        [ordered]@{ timestamp="2026-01-01T00:00:02+00:00"; level="WARNING"; component="bilibili"; event="bilibili.fetch_page_failed"; dev_session_id=$sessionA; message="timeout"; request_id="req-root"; analysis_id=41; stage="fetch_started" }
    )
    Write-JsonLines (Join-Path $sessionAPath "backend.log") @(
        [ordered]@{ timestamp="2026-01-01T00:00:03+00:00"; level="INFO"; component="analysis"; event="analysis.local_nlp_started"; dev_session_id=$sessionA; message="nlp"; request_id="req-nested"; analysis_id=42; stage="local_nlp_started" },
        [ordered]@{ timestamp="2026-01-01T00:00:05+00:00"; level="ERROR"; component="analysis"; event="analysis.task_failed"; dev_session_id=$sessionA; message=("api_key=NEVER_SHOW" + [char]27 + "[31mred"); request_id="req-root"; analysis_id=42; stage="task_failed" }
    ) @('{broken-json', '{"timestamp":"bad","level":"ERROR"}', '{"timestamp":"2026-01-01T00:00:07+00:00","level":"NOPE"}')
    Write-JsonLines (Join-Path $sessionAPath "frontend.log") @(
        [ordered]@{ timestamp="2026-01-01T00:00:04+00:00"; level="ERROR"; component="frontend"; event="react.error_boundary"; dev_session_id=$sessionA; message="render"; breadcrumbs=@([ordered]@{ event="api.request_failed"; request_id="req-nested"; analysis_id=42; status=500 }); state=[ordered]@{ route="/"; view_type="single"; analysis_id=42; loading=$false } },
        [ordered]@{ timestamp="2026-01-03T00:00:00+00:00"; level="DEBUG"; component="frontend"; event="context.latest_marker"; dev_session_id=$sessionA; message="latest by timestamp" }
    )
    Write-JsonLines (Join-Path $sessionBPath "launcher.log") @(
        [ordered]@{ timestamp="2026-01-02T00:00:00+00:00"; level="ERROR"; component="launcher"; event="other.session"; dev_session_id=$sessionB; message="newer directory but older log" }
    )
    $olderWriteTime = [datetime]::UtcNow.AddMinutes(-2)
    $newerWriteTime = [datetime]::UtcNow.AddMinutes(2)
    foreach ($file in (Get-ChildItem -LiteralPath $sessionAPath -File)) { $file.LastWriteTimeUtc = $olderWriteTime }
    foreach ($file in (Get-ChildItem -LiteralPath $sessionBPath -File)) { $file.LastWriteTimeUtc = $newerWriteTime }
    (Get-Item -LiteralPath $sessionAPath).LastWriteTimeUtc = $olderWriteTime
    (Get-Item -LiteralPath $sessionBPath).LastWriteTimeUtc = $newerWriteTime

    $trackedFiles = @(Get-ChildItem -LiteralPath $sessionAPath -File)
    $before = @{}
    foreach ($file in $trackedFiles) { $before[$file.FullName] = Get-FileSnapshot $file.FullName }

    $latest = Invoke-Reader @{ Session="latest"; Level="DEBUG"; Tail=1; Context=0 } ([IO.Path]::GetTempPath())
    Assert-Contains $latest "会话：$sessionB" "latest 应采用白名单文件或目录的最新修改时间"
    Assert-Contains $latest "other.session" "日志内的未来时间戳不得劫持 latest"

    $defaultOutput = Invoke-Reader @{ Session=$sessionA; Context=0 }
    Assert-Contains $defaultOutput "bilibili.fetch_page_failed" "默认 WARNING 阈值应包含警告"
    Assert-Contains $defaultOutput "analysis.task_failed" "默认 WARNING 阈值应包含错误"
    Assert-NotContains $defaultOutput "analysis.local_nlp_started" "默认 WARNING 阈值不应包含 INFO"
    Assert-Contains $defaultOutput "JSON 1，时间戳 1，级别 1" "损坏行应分类计数且不中止"
    Assert-Contains $defaultOutput "codex/dev-diagnostics / abc1234 / True" "应读取会话启动元数据"
    Assert-NotContains $defaultOutput "NEVER_SHOW" "输出必须防御性隐藏秘密"

    $launcherOutput = Invoke-Reader @{ Session=$sessionA; Level="INFO"; Context=0 }
    Assert-Contains $launcherOutput "阶段=session_started" "launcher details 中的白名单阶段应可回溯"

    $liveLogPath = Join-Path $sessionAPath "backend.log"
    $liveShare = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $liveWriter = [IO.FileStream]::new($liveLogPath, [IO.FileMode]::Open, [IO.FileAccess]::Write, $liveShare)
    try {
        $liveOutput = Invoke-Reader @{ Session=$sessionA; Level="ERROR"; Tail=1; Context=0 }
        Assert-Contains $liveOutput "analysis.task_failed" "运行中 writer 持有日志时仍应支持只读回溯"
    }
    finally { $liveWriter.Dispose() }
    Assert-NotContains $defaultOutput (([string][char]27) + "[31m") "输出必须移除 ANSI 控制序列"

    $analysisOutput = Invoke-Reader @{ Session=$sessionA; Level="DEBUG"; AnalysisId="42"; Context=0 }
    Assert-Contains $analysisOutput "analysis.local_nlp_started" "AnalysisId 应匹配顶层字段"
    Assert-Contains $analysisOutput "react.error_boundary" "AnalysisId 应匹配 state 或 breadcrumb"
    Assert-NotContains $analysisOutput "analysis_id=41" "AnalysisId 不应匹配其他分析"

    $requestOutput = Invoke-Reader @{ Session=$sessionA; Level="DEBUG"; RequestId="req-nested"; Context=0 }
    Assert-Contains $requestOutput "analysis.local_nlp_started" "RequestId 应匹配顶层字段"
    Assert-Contains $requestOutput "react.error_boundary" "RequestId 应匹配 breadcrumb"
    Assert-NotContains $requestOutput "bilibili.fetch_page_failed" "RequestId 必须精确匹配"

    $liveLogPath = Join-Path $sessionAPath "backend.log"
    $liveShare = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $liveWriter = [IO.FileStream]::new($liveLogPath, [IO.FileMode]::Open, [IO.FileAccess]::Write, $liveShare)
    try {
        $liveOutput = Invoke-Reader @{ Session=$sessionA; Level="ERROR"; Tail=1; Context=0 }
        Assert-Contains $liveOutput "analysis.task_failed" "运行中 writer 持有日志时仍应只读回溯"
    }
    finally { $liveWriter.Dispose() }

    $timeOutput = Invoke-Reader @{ Session=$sessionA; Level="DEBUG"; Since=[DateTimeOffset]::Parse("2026-01-01T00:00:03+00:00"); Until=[DateTimeOffset]::Parse("2026-01-01T00:00:04+00:00"); Context=0 }
    Assert-Contains $timeOutput "analysis.local_nlp_started" "Since 边界应包含"
    Assert-Contains $timeOutput "react.error_boundary" "Until 边界应包含"
    Assert-NotContains $timeOutput "analysis.task_failed" "时间窗外记录不应命中"

    $tailOutput = Invoke-Reader @{ Session=$sessionA; Level="ERROR"; Tail=1; Context=1 }
    Assert-Contains $tailOutput "命中/显示/损坏：2 / 3" "Tail 后应围绕最后命中扩展上下文并去重"
    Assert-Contains $tailOutput "[上下文] 2026-01-01 00:00:04.000" "前置上下文应明确标记"
    Assert-Contains $tailOutput "analysis.task_failed" "最后一条命中应保留"
    Assert-Contains $tailOutput "[上下文] 2026-01-03 00:00:00.000" "后置上下文应明确标记"

    $invalidRejected = $false
    try { [void](Invoke-Reader @{ Session=".." }) }
    catch { $invalidRejected = $_.Exception.Message.Contains("严格会话 ID") }
    Assert-True $invalidRejected "目录穿越形式的 Session 必须被拒绝"

    $invalidRequestRejected = $false
    try { [void](Invoke-Reader @{ Session=$sessionA; RequestId="../unsafe" }) }
    catch { $invalidRequestRejected = $_.Exception.Message.Contains("格式不安全") }
    Assert-True $invalidRequestRejected "不安全的 RequestId 必须被拒绝"

    $invalidAnalysisRejected = $false
    try { [void](Invoke-Reader @{ Session=$sessionA; AnalysisId="0" }) }
    catch { $invalidAnalysisRejected = $_.Exception.Message.Contains("正整数") }
    Assert-True $invalidAnalysisRejected "非正数 AnalysisId 必须被拒绝"

    $invalidRangeRejected = $false
    try {
        [void](Invoke-Reader @{
            Session=$sessionA
            Since=[DateTimeOffset]::Parse("2026-01-02T00:00:00+00:00")
            Until=[DateTimeOffset]::Parse("2026-01-01T00:00:00+00:00")
        })
    }
    catch { $invalidRangeRejected = $_.Exception.Message.Contains("不能晚于") }
    Assert-True $invalidRangeRejected "反向时间范围必须被拒绝"

    $junctionTarget = Join-Path $temporaryRoot "outside-session"
    [IO.Directory]::CreateDirectory($junctionTarget) | Out-Null
    $junctionPath = Join-Path $sandboxLogs "20260104-000000-cccccc"
    $junctionCreated = $false
    try {
        New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget -ErrorAction Stop | Out-Null
        $junctionCreated = $true
    }
    catch { Write-Warning "当前环境无法创建 junction，跳过重解析点运行时断言。" }
    if ($junctionCreated) {
        $junctionRejected = $false
        try { [void](Invoke-Reader @{ Session="20260104-000000-cccccc" }) }
        catch { $junctionRejected = $_.Exception.Message.Contains("重解析点") }
        Assert-True $junctionRejected "会话目录重解析点必须被拒绝"
    }

    $readerSource = [IO.File]::ReadAllText($sourceReader, [Text.Encoding]::UTF8)
    Assert-NotContains $readerSource "[Array]::IndexOf" "上下文定位不得为每条命中线性回查"
    Assert-Contains $readerSource "日志发生轮转或写入" "读取期间文件变化必须触发有界重试提示"

    $savedBackendLog = Join-Path $sessionAPath "backend.saved"
    [IO.File]::Move((Join-Path $sessionAPath "backend.log"), $savedBackendLog)
    $outsideLogDirectory = Join-Path $temporaryRoot "outside-log-directory"
    [IO.Directory]::CreateDirectory($outsideLogDirectory) | Out-Null
    $logJunction = Join-Path $sessionAPath "backend.log"
    New-Item -ItemType Junction -Path $logJunction -Target $outsideLogDirectory -ErrorAction Stop | Out-Null
    try {
        $logJunctionRejected = $false
        try { [void](Invoke-Reader @{ Session=$sessionA }) }
        catch { $logJunctionRejected = $_.Exception.Message.Contains("重解析点日志文件") }
        Assert-True $logJunctionRejected "固定日志路径上的重解析点必须被拒绝"
    }
    finally {
        if (Test-Path -LiteralPath $logJunction) { [IO.Directory]::Delete($logJunction) }
        [IO.File]::Move($savedBackendLog, (Join-Path $sessionAPath "backend.log"))
    }

    $realLogs = Join-Path $temporaryRoot "real-dev-logs"
    [IO.Directory]::Move($sandboxLogs, $realLogs)
    $rootJunctionCreated = $false
    try {
        New-Item -ItemType Junction -Path $sandboxLogs -Target $realLogs -ErrorAction Stop | Out-Null
        $rootJunctionCreated = $true
        $rootRejected = $false
        try { [void](Invoke-Reader @{ Session=$sessionA }) }
        catch { $rootRejected = $_.Exception.Message.Contains("重解析点日志根目录") }
        Assert-True $rootRejected "日志根目录重解析点必须在读取前被拒绝"
    }
    finally {
        if ($rootJunctionCreated -and (Test-Path -LiteralPath $sandboxLogs)) {
            [IO.Directory]::Delete($sandboxLogs)
        }
        if (-not (Test-Path -LiteralPath $sandboxLogs)) {
            [IO.Directory]::Move($realLogs, $sandboxLogs)
        }
    }

    foreach ($file in $trackedFiles) {
        $after = Get-FileSnapshot $file.FullName
        $prior = $before[$file.FullName]
        Assert-True ($after.Hash -eq $prior.Hash) "读取后文件哈希必须不变：$($file.Name)"
        Assert-True ($after.Length -eq $prior.Length) "读取后文件长度必须不变：$($file.Name)"
        Assert-True ($after.LastWriteTicks -eq $prior.LastWriteTicks) "读取后修改时间必须不变：$($file.Name)"
    }

    Write-Output "read-dev-logs 沙盒测试通过：$script:assertions 项断言。"
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporary = (Resolve-Path -LiteralPath $temporaryRoot).ProviderPath
        $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedTemporary.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝清理临时目录之外的路径：$resolvedTemporary"
        }
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
