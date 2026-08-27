[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$sourceLauncher = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\start-dev.ps1"))
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ("bili-start-dev-safety-" + [guid]::NewGuid().ToString("N"))))
$script:assertions = 0

function Assert-True([bool]$Condition, [string]$Message) {
    $script:assertions++
    if (-not $Condition) { throw "断言失败：$Message" }
}

function Assert-ThrowsLike([scriptblock]$Action, [string]$Expected, [string]$Message) {
    $thrown = $false
    try { [void](& $Action) }
    catch {
        $thrown = $_.Exception.Message.Contains($Expected)
        if (-not $thrown) { throw "断言失败：$Message，实际错误：$($_.Exception.Message)" }
    }
    Assert-True $thrown $Message
}

function Write-LogLine([string]$Path, [string]$Level = "INFO") {
    $line = '{"timestamp":"2026-01-01T00:00:00+00:00","level":"' + $Level + '","component":"test","event":"test.event","message":"safe"}'
    [IO.File]::WriteAllText($Path, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function New-TestSession([string]$Root, [string]$Name, [datetime]$WriteTime) {
    $path = Join-Path $Root $Name
    [IO.Directory]::CreateDirectory($path) | Out-Null
    Write-LogLine (Join-Path $path "launcher.log")
    (Get-Item -LiteralPath (Join-Path $path "launcher.log")).LastWriteTimeUtc = $WriteTime
    (Get-Item -LiteralPath $path).LastWriteTimeUtc = $WriteTime
    return Get-Item -LiteralPath $path
}

try {
    [IO.Directory]::CreateDirectory($temporaryRoot) | Out-Null
    $smokeScripts = Join-Path $temporaryRoot "smoke-project\scripts"
    [IO.Directory]::CreateDirectory($smokeScripts) | Out-Null
    $smokeLauncher = Join-Path $smokeScripts "start-dev.ps1"
    Copy-Item -LiteralPath $sourceLauncher -Destination $smokeLauncher
    Assert-ThrowsLike { & $smokeLauncher } "Missing backend Python environment" "入口脚本必须能完整解析并运行到依赖门禁"

    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($sourceLauncher, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "start-dev.ps1 无法解析：$($errors[0].Message)" }
    $functions = $ast.FindAll({
        param($node)
        return $node -is [Management.Automation.Language.FunctionDefinitionAst]
    }, $true)
    foreach ($function in $functions) { Invoke-Expression $function.Extent.Text }

    $projectRoot = Join-Path $temporaryRoot "retention-project"
    $devLogsRoot = Join-Path $projectRoot "logs\dev"
    $sessionPattern = '^\d{8}-\d{6}-[0-9a-f]{6}$'
    $managedLogNames = @("launcher.log.1", "launcher.log", "backend.log.1", "backend.log", "frontend.log.1", "frontend.log")
    [IO.Directory]::CreateDirectory($devLogsRoot) | Out-Null

    $probe = New-TestSession $devLogsRoot "20260101-120000-aaaaaa" ([datetime]::UtcNow)
    foreach ($name in $managedLogNames) {
        foreach ($existing in (Get-ChildItem -LiteralPath $probe.FullName -File)) { [IO.File]::Delete($existing.FullName) }
        Write-LogLine (Join-Path $probe.FullName $name) "ERROR"
        Assert-True (Test-SessionContainsError $probe) "失败扫描必须覆盖 $name"
    }
    [IO.Directory]::Delete($probe.FullName, $true)

    $now = [datetime]::UtcNow
    $sessions = [Collections.Generic.List[IO.DirectoryInfo]]::new()
    for ($index = 1; $index -le 22; $index++) {
        $name = "202601{0}-120000-{1}" -f $index.ToString("00"), $index.ToString("x6")
        $sessions.Add((New-TestSession $devLogsRoot $name $now.AddMinutes(-$index)))
    }
    Write-LogLine (Join-Path $sessions[20].FullName "frontend.log.1") "ERROR"
    (Get-Item -LiteralPath (Join-Path $sessions[20].FullName "frontend.log.1")).LastWriteTimeUtc = $now.AddMinutes(-21)
    $script:sessionDirectory = $sessions[0].FullName
    Remove-ExpiredDevSessions
    Assert-True (Test-Path -LiteralPath $sessions[20].FullName -PathType Container) "最近失败会话必须保留，即使错误仅在 frontend.log.1"
    Assert-True (-not (Test-Path -LiteralPath $sessions[21].FullName)) "超过 20 个且非最近失败的会话必须清理"

    $junctionProject = Join-Path $temporaryRoot "junction-project"
    $projectRoot = $junctionProject
    $devLogsRoot = Join-Path $projectRoot "logs\dev"
    [IO.Directory]::CreateDirectory((Join-Path $projectRoot "logs")) | Out-Null
    $outsideRoot = Join-Path $temporaryRoot "outside-dev-root"
    [IO.Directory]::CreateDirectory($outsideRoot) | Out-Null
    $outsideMarker = Join-Path $outsideRoot "keep.txt"
    [IO.File]::WriteAllText($outsideMarker, "keep", [Text.Encoding]::ASCII)
    New-Item -ItemType Junction -Path $devLogsRoot -Target $outsideRoot -ErrorAction Stop | Out-Null
    try {
        Assert-ThrowsLike { Remove-ExpiredDevSessions } "重解析点日志根目录" "清理前必须拒绝日志根目录 junction"
        Assert-True (Test-Path -LiteralPath $outsideMarker -PathType Leaf) "拒绝根 junction 后不得删除外部文件"
    }
    finally {
        if (Test-Path -LiteralPath $devLogsRoot) { [IO.Directory]::Delete($devLogsRoot) }
    }

    $projectRoot = Join-Path $temporaryRoot "session-junction-project"
    $devLogsRoot = Join-Path $projectRoot "logs\dev"
    [IO.Directory]::CreateDirectory($devLogsRoot) | Out-Null
    $outsideSession = Join-Path $temporaryRoot "outside-session"
    [IO.Directory]::CreateDirectory($outsideSession) | Out-Null
    $junctionSession = Join-Path $devLogsRoot "20260201-120000-bbbbbb"
    New-Item -ItemType Junction -Path $junctionSession -Target $outsideSession -ErrorAction Stop | Out-Null
    try {
        Assert-ThrowsLike { Remove-ExpiredDevSessions } "重解析点开发会话目录" "扫描前必须拒绝会话 junction"
    }
    finally {
        if (Test-Path -LiteralPath $junctionSession) { [IO.Directory]::Delete($junctionSession) }
    }

    $safeSession = New-TestSession $devLogsRoot "20260202-120000-cccccc" ([datetime]::UtcNow)
    [IO.File]::Delete((Join-Path $safeSession.FullName "launcher.log"))
    $outsideFile = Join-Path $temporaryRoot "outside.log"
    Write-LogLine $outsideFile "ERROR"
    $linkPath = Join-Path $safeSession.FullName "backend.log"
    $fileLinkCreated = $false
    try {
        New-Item -ItemType SymbolicLink -Path $linkPath -Target $outsideFile -ErrorAction Stop | Out-Null
        $fileLinkCreated = $true
    }
    catch {
        $outsideDirectory = Join-Path $temporaryRoot "outside-log-directory"
        [IO.Directory]::CreateDirectory($outsideDirectory) | Out-Null
        New-Item -ItemType Junction -Path $linkPath -Target $outsideDirectory -ErrorAction Stop | Out-Null
        $fileLinkCreated = $true
    }
    if ($fileLinkCreated) {
        Assert-ThrowsLike { Test-SessionContainsError $safeSession } "重解析点日志文件" "扫描前必须拒绝日志文件符号链接"
        Assert-ThrowsLike { New-SafeEmptyLogFile $safeSession "backend.log" } "重解析点日志文件" "创建前必须拒绝已存在的日志文件符号链接"
    }

    Write-Output "start-dev 安全沙盒测试通过：$script:assertions 项断言。"
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
