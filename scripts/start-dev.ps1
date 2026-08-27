[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173,
    [ValidateSet("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")]
    [string]$LogLevel = "INFO"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $backendRoot "venv\Scripts\python.exe"
$frontendPackage = Join-Path $frontendRoot "package.json"
$devLogsRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "logs\dev"))
$sessionPattern = '^\d{8}-\d{6}-[0-9a-f]{6}$'
$managedLogNames = @("launcher.log.1", "launcher.log", "backend.log.1", "backend.log", "frontend.log.1", "frontend.log")

if (-not ('BiliDevJob.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace BiliDevJob
{
    public static class Cancellation
    {
        public static volatile bool Requested;
        private static ConsoleCancelEventHandler handler;

        public static void Install()
        {
            Requested = false;
            handler = (sender, args) => { args.Cancel = true; Requested = true; };
            Console.CancelKeyPress += handler;
        }

        public static void Uninstall()
        {
            if (handler != null) Console.CancelKeyPress -= handler;
            handler = null;
        }
    }

    public static class NativeMethods
    {
        private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private const int JobObjectExtendedLimitInformation = 9;

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job, int informationClass,
            ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information,
            uint informationLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        public static IntPtr CreateKillOnCloseJob()
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            var information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            uint size = (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref information, size))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(job);
                throw new Win32Exception(error);
            }
            return job;
        }

        public static void Assign(IntPtr job, Process process)
        {
            if (!AssignProcessToJobObject(job, process.Handle))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        public static void Close(IntPtr job)
        {
            if (job != IntPtr.Zero) CloseHandle(job);
        }
    }
}
'@
}

function Test-TcpPortInUse([int]$Port) {
    $listener = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    return @($listener.GetActiveTcpListeners() | Where-Object { $_.Port -eq $Port }).Count -gt 0
}

function Invoke-CapturedVersion([string]$FileName, [string[]]$Arguments) {
    $output = & $FileName @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read tool version: $FileName"
    }
    return (@($output)[0].ToString().Trim())
}

function Write-LauncherEvent(
    [string]$Event,
    [string]$Level,
    [string]$Message,
    [Collections.IDictionary]$Details = @{}
) {
    try {
        $entry = [ordered]@{
            timestamp = [DateTimeOffset]::Now.ToString("o")
            level = $Level
            component = "launcher"
            event = $Event
            dev_session_id = $script:devSessionId
            message = $Message
        }
        if ($Details.Count -gt 0) {
            $entry.details = $Details
        }
        $line = ($entry | ConvertTo-Json -Compress -Depth 5) + [Environment]::NewLine
        [IO.File]::AppendAllText($script:launcherLog, $line, [Text.UTF8Encoding]::new($false))
    }
    catch {
        try { [Console]::Error.WriteLine("无法写入启动器诊断日志，开发进程管理将继续。") }
        catch { }
    }
}

function Start-ManagedProcess(
    [string]$FileName,
    [string]$Arguments,
    [string]$WorkingDirectory
) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FileName
    $startInfo.Arguments = $Arguments
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $false
    $startInfo.EnvironmentVariables["BILI_DEV_LOGGING"] = "1"
    $startInfo.EnvironmentVariables["BILI_DEV_SESSION_ID"] = $script:devSessionId
    $startInfo.EnvironmentVariables["BILI_DEV_LOG_DIR"] = $script:sessionDirectory
    $startInfo.EnvironmentVariables["BILI_DEV_LOG_LEVEL"] = $LogLevel
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Failed to start process: $FileName"
    }
    try {
        [BiliDevJob.NativeMethods]::Assign($script:jobHandle, $process)
    }
    catch {
        if (-not $process.HasExited) { $process.Kill() }
        $process.Dispose()
        throw
    }
    return $process
}

function Wait-DevelopmentReady(
    [Diagnostics.Process]$BackendProcess,
    [Diagnostics.Process]$FrontendProcess,
    [int]$TimeoutSeconds = 30
) {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(1)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    try {
        while ([DateTimeOffset]::Now -lt $deadline) {
            if ([BiliDevJob.Cancellation]::Requested) {
                throw [OperationCanceledException]::new("Development session stop requested.")
            }
            if ($BackendProcess.HasExited) {
                throw "Backend process exited before becoming ready (code $($BackendProcess.ExitCode))."
            }
            if ($FrontendProcess.HasExited) {
                throw "Frontend process exited before becoming ready (code $($FrontendProcess.ExitCode))."
            }
            $backendReady = $false
            $frontendReady = $false
            try {
                $response = $client.GetAsync("http://127.0.0.1:$BackendPort/api/runtime/health").GetAwaiter().GetResult()
                try { $backendReady = $response.IsSuccessStatusCode }
                finally { $response.Dispose() }
            }
            catch { $backendReady = $false }
            try {
                $response = $client.GetAsync("http://127.0.0.1:$FrontendPort/").GetAwaiter().GetResult()
                try { $frontendReady = $response.IsSuccessStatusCode }
                finally { $response.Dispose() }
            }
            catch { $frontendReady = $false }
            if ($backendReady -and $frontendReady) {
                return
            }
            Start-Sleep -Milliseconds 250
        }
        throw "Development services did not become ready within $TimeoutSeconds seconds."
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Test-ReparsePoint([IO.FileSystemInfo]$Item) {
    return (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Assert-SafeProjectPathChain {
    $projectItem = Get-Item -LiteralPath $projectRoot -Force -ErrorAction Stop
    if (Test-ReparsePoint $projectItem) { throw "拒绝通过重解析点项目目录创建开发日志：$projectRoot" }
    $resolvedProject = (Resolve-Path -LiteralPath $projectItem.FullName -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
    $expectedProject = $projectRoot.TrimEnd('\', '/')
    if (-not $resolvedProject.Equals($expectedProject, [StringComparison]::OrdinalIgnoreCase)) {
        throw "项目目录解析结果不符合预期：$resolvedProject"
    }

    $logsRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "logs"))
    if (Test-Path -LiteralPath $logsRoot) {
        $logsItem = Get-Item -LiteralPath $logsRoot -Force -ErrorAction Stop
        if (-not $logsItem.PSIsContainer) { throw "开发日志父路径不是目录：$logsRoot" }
        if (Test-ReparsePoint $logsItem) { throw "拒绝通过重解析点 logs 目录创建开发日志：$logsRoot" }
        $resolvedLogs = (Resolve-Path -LiteralPath $logsItem.FullName -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
        if (-not $resolvedLogs.Equals($logsRoot.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)) {
            throw "logs 目录解析结果不符合预期：$resolvedLogs"
        }
    }
}

function Assert-SafeDevLogsRoot([bool]$AllowMissing = $false) {
    Assert-SafeProjectPathChain
    if (-not (Test-Path -LiteralPath $devLogsRoot)) {
        if ($AllowMissing) { return $null }
        throw "开发日志根目录不存在：$devLogsRoot"
    }
    $item = Get-Item -LiteralPath $devLogsRoot -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw "开发日志根路径不是目录：$devLogsRoot" }
    if (Test-ReparsePoint $item) { throw "拒绝重解析点日志根目录：$devLogsRoot" }
    $resolved = (Resolve-Path -LiteralPath $item.FullName -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
    $expected = $devLogsRoot.TrimEnd('\', '/')
    if (-not $resolved.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝解析后偏离项目 logs/dev 的日志根目录：$resolved"
    }
    return $item
}

function Assert-SafeSessionDirectory([string]$Path) {
    [void](Assert-SafeDevLogsRoot)
    $absolute = [IO.Path]::GetFullPath($Path)
    $prefix = $devLogsRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $absolute.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝访问 logs/dev 之外的会话目录：$absolute"
    }
    $item = Get-Item -LiteralPath $absolute -Force -ErrorAction Stop
    if (-not $item.PSIsContainer) { throw "开发会话路径不是目录：$absolute" }
    if ($item.Name -notmatch $sessionPattern) { throw "开发会话目录名称不合法：$($item.Name)" }
    if (Test-ReparsePoint $item) { throw "拒绝重解析点开发会话目录：$absolute" }
    $resolved = (Resolve-Path -LiteralPath $item.FullName -ErrorAction Stop).ProviderPath
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝解析后位于 logs/dev 之外的会话目录：$resolved"
    }
    return $item
}

function Get-SafeSessionLogFiles([IO.DirectoryInfo]$SessionDirectory) {
    $safeSession = Assert-SafeSessionDirectory $SessionDirectory.FullName
    $sessionPrefix = $safeSession.FullName.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $files = [Collections.Generic.List[IO.FileInfo]]::new()
    foreach ($name in $managedLogNames) {
        $candidate = [IO.Path]::GetFullPath((Join-Path $safeSession.FullName $name))
        if (-not $candidate.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝访问开发会话之外的日志文件：$candidate"
        }
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
        if (Test-ReparsePoint $item) { throw "拒绝重解析点日志文件：$candidate" }
        if ($item.PSIsContainer) { throw "固定日志路径不是文件：$candidate" }
        $resolved = (Resolve-Path -LiteralPath $item.FullName -ErrorAction Stop).ProviderPath
        if (-not $resolved.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝解析后位于开发会话之外的日志文件：$resolved"
        }
        $files.Add($item)
    }
    return $files
}

function New-SafeEmptyLogFile([IO.DirectoryInfo]$SessionDirectory, [string]$Name) {
    if ($managedLogNames -notcontains $Name -or $Name.EndsWith(".1")) {
        throw "不允许创建的开发日志文件：$Name"
    }
    $safeSession = Assert-SafeSessionDirectory $SessionDirectory.FullName
    $sessionPrefix = $safeSession.FullName.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $candidate = [IO.Path]::GetFullPath((Join-Path $safeSession.FullName $Name))
    if (-not $candidate.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝在开发会话之外创建日志文件：$candidate"
    }
    if (Test-Path -LiteralPath $candidate) {
        $existing = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
        if (Test-ReparsePoint $existing) { throw "拒绝重解析点日志文件：$candidate" }
        throw "开发日志文件已存在，拒绝覆盖：$candidate"
    }
    $stream = [IO.FileStream]::new($candidate, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $stream.Dispose()
    $created = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
    if (Test-ReparsePoint $created) { throw "拒绝创建重解析点日志文件：$candidate" }
    $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).ProviderPath
    if (-not $resolved.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "创建后的日志文件偏离开发会话：$resolved"
    }
    return $created
}

function Test-SessionContainsError([IO.DirectoryInfo]$SessionDirectory) {
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    foreach ($file in (Get-SafeSessionLogFiles $SessionDirectory)) {
        $stream = [IO.FileStream]::new($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
        $reader = [IO.StreamReader]::new($stream, [Text.UTF8Encoding]::new($false), $true)
        try {
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ($line.Contains('"level":"ERROR"') -or $line.Contains('"level":"CRITICAL"')) { return $true }
            }
        }
        finally {
            $reader.Dispose()
            $stream.Dispose()
        }
    }
    return $false
}

function Remove-ExpiredDevSessions {
    [void](Assert-SafeDevLogsRoot)
    $rootWithSeparator = $devLogsRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $safeSessions = [Collections.Generic.List[IO.DirectoryInfo]]::new()
    foreach ($candidate in (Get-ChildItem -LiteralPath $devLogsRoot -Directory -Force -ErrorAction Stop | Where-Object { $_.Name -match $sessionPattern })) {
        $safeSessions.Add((Assert-SafeSessionDirectory $candidate.FullName))
    }
    $sessions = @($safeSessions | Sort-Object @{ Expression = "LastWriteTimeUtc"; Descending = $true }, @{ Expression = "Name"; Descending = $true })
    $latestFailed = $null
    foreach ($session in $sessions) {
        if (Test-SessionContainsError $session) {
            $latestFailed = $session.FullName
            break
        }
    }
    foreach ($session in ($sessions | Select-Object -Skip 20)) {
        [void](Assert-SafeDevLogsRoot)
        $currentItem = Assert-SafeSessionDirectory $session.FullName
        $resolved = (Resolve-Path -LiteralPath $currentItem.FullName -ErrorAction Stop).ProviderPath
        if (-not $resolved.StartsWith($rootWithSeparator, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a directory outside logs/dev: $resolved"
        }
        if ($resolved -ne $script:sessionDirectory -and $resolved -ne $latestFailed) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Missing backend Python environment: $pythonPath"
}
if (-not (Test-Path -LiteralPath $frontendPackage -PathType Leaf)) {
    throw "Missing frontend package file: $frontendPackage"
}
$pnpmCommand = Get-Command pnpm.cmd -ErrorAction Stop
if (Test-TcpPortInUse $BackendPort) {
    throw "Backend port $BackendPort is already in use."
}
if (Test-TcpPortInUse $FrontendPort) {
    throw "Frontend port $FrontendPort is already in use."
}

[void](Assert-SafeDevLogsRoot $true)
[IO.Directory]::CreateDirectory($devLogsRoot) | Out-Null
[void](Assert-SafeDevLogsRoot)
$script:devSessionId = "{0}-{1}" -f [DateTime]::Now.ToString("yyyyMMdd-HHmmss"), ([Guid]::NewGuid().ToString("N").Substring(0, 6))
$script:sessionDirectory = [IO.Path]::GetFullPath((Join-Path $devLogsRoot $script:devSessionId))
if (Test-Path -LiteralPath $script:sessionDirectory) { throw "开发会话目录已存在，拒绝复用：$script:sessionDirectory" }
[IO.Directory]::CreateDirectory($script:sessionDirectory) | Out-Null
$sessionItem = Assert-SafeSessionDirectory $script:sessionDirectory
$script:launcherLog = Join-Path $script:sessionDirectory "launcher.log"
[void](New-SafeEmptyLogFile $sessionItem "backend.log")
[void](New-SafeEmptyLogFile $sessionItem "frontend.log")
[void](New-SafeEmptyLogFile $sessionItem "launcher.log")

$branch = (& git -C $projectRoot branch --show-current 2>$null).Trim()
$commit = (& git -C $projectRoot rev-parse --short HEAD 2>$null).Trim()
$dirty = @(& git -C $projectRoot status --porcelain 2>$null).Count -gt 0
$pythonVersion = Invoke-CapturedVersion $pythonPath @("--version")
$nodeVersion = Invoke-CapturedVersion "node.exe" @("--version")
$pnpmVersion = Invoke-CapturedVersion $pnpmCommand.Source @("--version")
$relativeLogDirectory = "logs/dev/$script:devSessionId"

Write-LauncherEvent "launcher.session_started" "INFO" "开发会话已创建" ([ordered]@{
    branch = $branch
    commit = $commit
    dirty = $dirty
    python_version = $pythonVersion
    node_version = $nodeVersion
    pnpm_version = $pnpmVersion
    backend_command = "uvicorn-loopback-reload"
    frontend_command = "vite-loopback"
    reload = $true
    log_directory = $relativeLogDirectory
})
Remove-ExpiredDevSessions

$backendProcess = $null
$frontendProcess = $null
$script:jobHandle = [IntPtr]::Zero
$script:launcherStage = "initializing_job"
$exitLevel = "INFO"
try {
    [BiliDevJob.Cancellation]::Install()
    $script:jobHandle = [BiliDevJob.NativeMethods]::CreateKillOnCloseJob()
    $backendArguments = "-m uvicorn main:app --host 127.0.0.1 --port $BackendPort --reload"
    $frontendArguments = "run dev --host 127.0.0.1 --port $FrontendPort --strictPort"
    $script:launcherStage = "starting_backend"
    $backendProcess = Start-ManagedProcess $pythonPath $backendArguments $backendRoot
    $script:launcherStage = "starting_frontend"
    $frontendProcess = Start-ManagedProcess $pnpmCommand.Source $frontendArguments $frontendRoot
    Write-LauncherEvent "launcher.processes_started" "INFO" "前后端开发进程已启动" ([ordered]@{
        backend_pid = $backendProcess.Id
        frontend_pid = $frontendProcess.Id
        backend_port = $BackendPort
        frontend_port = $FrontendPort
    })
    $script:launcherStage = "waiting_for_services"
    Wait-DevelopmentReady $backendProcess $frontendProcess
    Write-LauncherEvent "launcher.services_ready" "INFO" "前后端开发服务已就绪"
    $script:launcherStage = "running"

    Write-Host "前端：http://127.0.0.1:$FrontendPort/#/"
    Write-Host "后端：http://127.0.0.1:$BackendPort"
    Write-Host "日志：$script:sessionDirectory"
    Write-Host "按 Ctrl+C 停止本次开发会话。"

    while ((-not [BiliDevJob.Cancellation]::Requested) -and (-not $backendProcess.HasExited) -and (-not $frontendProcess.HasExited)) {
        Start-Sleep -Milliseconds 250
    }
    if ([BiliDevJob.Cancellation]::Requested) {
        Write-LauncherEvent "launcher.stop_requested" "INFO" "开发者请求停止本次会话"
    }
    else {
        $backendExit = if ($backendProcess.HasExited) { $backendProcess.ExitCode } else { $null }
        $frontendExit = if ($frontendProcess.HasExited) { $frontendProcess.ExitCode } else { $null }
        $exitLevel = if (($null -ne $backendExit -and $backendExit -ne 0) -or ($null -ne $frontendExit -and $frontendExit -ne 0)) { "ERROR" } else { "WARNING" }
        Write-LauncherEvent "launcher.child_exited" $exitLevel "开发子进程已退出，正在停止本次会话" ([ordered]@{
            backend_exit_code = $backendExit
            frontend_exit_code = $frontendExit
        })
    }
}
catch [OperationCanceledException] {
    $exitLevel = "INFO"
    Write-LauncherEvent "launcher.stop_requested" "INFO" "开发者请求停止本次会话"
}
catch {
    $exitLevel = "ERROR"
    $backendExit = if ($backendProcess -and $backendProcess.HasExited) { $backendProcess.ExitCode } else { $null }
    $frontendExit = if ($frontendProcess -and $frontendProcess.HasExited) { $frontendProcess.ExitCode } else { $null }
    Write-LauncherEvent "launcher.failed" "ERROR" "开发会话启动或监控失败" ([ordered]@{
        error_type = $_.Exception.GetType().FullName
        stage = $script:launcherStage
        backend_exit_code = $backendExit
        frontend_exit_code = $frontendExit
    })
    throw
}
finally {
    Write-LauncherEvent "launcher.session_stopping" $exitLevel "正在停止本次开发会话"
    try {
        [BiliDevJob.NativeMethods]::Close($script:jobHandle)
        foreach ($process in @($backendProcess, $frontendProcess)) {
            if ($process -and -not $process.HasExited) {
                [void]$process.WaitForExit(5000)
            }
        }
    }
    finally {
        [BiliDevJob.Cancellation]::Uninstall()
        foreach ($process in @($backendProcess, $frontendProcess)) {
            if ($process) { $process.Dispose() }
        }
    }
    Write-LauncherEvent "launcher.session_stopped" $exitLevel "本次开发会话已停止"
}
