using System.Globalization;
using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Agent;

/// <summary>
/// 代理命令实现。代理从不直接读取游戏内存，也从不编造扫描结果：
/// 它调用读取器、透传退出码，并负责把读取器写出的 JSON 投递到后端。
/// </summary>
public sealed class AgentApplication
{
    private const int ReaderScanFailed = 5;

    private readonly TextWriter _stdout;
    private readonly TextWriter _stderr;
    private readonly string _baseDirectory;
    private readonly TimeSpan _statusTimeout = TimeSpan.FromSeconds(120);
    private readonly TimeSpan _syncTimeout = TimeSpan.FromSeconds(60);

    /// <summary>创建代理应用。</summary>
    /// <param name="stdout">标准输出。</param>
    /// <param name="stderr">标准错误。</param>
    /// <param name="baseDirectory">代理可执行文件所在目录，用于定位配置与读取器。</param>
    public AgentApplication(TextWriter stdout, TextWriter stderr, string baseDirectory)
    {
        _stdout = stdout ?? throw new ArgumentNullException(nameof(stdout));
        _stderr = stderr ?? throw new ArgumentNullException(nameof(stderr));
        _baseDirectory = baseDirectory;
    }

    /// <summary>执行命令行。</summary>
    /// <param name="args">进程参数（不含程序名）。</param>
    /// <param name="cancellationToken">取消令牌（Ctrl+C）。</param>
    /// <returns>进程退出码。</returns>
    public async Task<int> RunAsync(string[] args, CancellationToken cancellationToken)
    {
        var parsed = AgentCommandLine.Parse(args);
        if (!parsed.Ok)
        {
            WriteUsageError(parsed.Error!);
            return AgentExitCodes.UsageError;
        }

        var options = parsed.Options!;
        switch (options.Command)
        {
            case AgentCommand.Help:
                WriteUsage(_stdout);
                return AgentExitCodes.Success;

            case AgentCommand.Status:
                return await RunStatusAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Scan:
                return await RunScanAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Watch:
                return await RunWatchAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Auto:
                return await RunAutoAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Sync:
                return await RunSyncAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.ConfigShow:
                return RunConfigShow();

            default:
                WriteUsageError("未知子命令。");
                return AgentExitCodes.UsageError;
        }
    }

    private async Task<int> RunStatusAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration();
        if (configuration.ReaderPath.Length == 0)
        {
            return ReportMissingReader(configuration);
        }

        var runner = new ReaderRunner(configuration.ReaderPath, _statusTimeout);
        var invocation = await runner.RunAsync(new[] { "status", "--json" }, cancellationToken).ConfigureAwait(false);

        var failure = MapReaderTransportFailure(invocation);
        if (failure is not null)
        {
            _stderr.WriteLine(failure.Value.Message);
            return failure.Value.ExitCode;
        }

        var status = TryDeserialize<ReaderStatus>(invocation.Stdout);
        if (status is null)
        {
            _stderr.WriteLine("读取器返回的 status 不是可解析的 JSON。");
            WriteReaderStderr(invocation);
            return invocation.ExitCode == 0 ? ReaderScanFailed : invocation.ExitCode;
        }

        if (options.Json)
        {
            _stdout.WriteLine(JsonSerializer.Serialize(status, ScoutMindJson.Options));
        }
        else
        {
            WriteStatusHuman(status);
        }

        return invocation.ExitCode;
    }

    private async Task<int> RunScanAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration();
        if (configuration.ReaderPath.Length == 0)
        {
            return ReportMissingReader(configuration);
        }

        var queue = new ScanQueue(configuration.QueueDirectory);
        queue.EnsureCreated();

        var readerTimeout = TimeSpan.FromSeconds(Math.Max(180, configuration.Config.TimeoutSeconds + 120));
        var runner = new ReaderRunner(configuration.ReaderPath, readerTimeout);
        var invocation = await runner
            .RunAsync(new[] { "scan", "--output", queue.ScanDirectory, "--json" }, cancellationToken)
            .ConfigureAwait(false);

        var failure = MapReaderTransportFailure(invocation);
        if (failure is not null)
        {
            _stderr.WriteLine(failure.Value.Message);
            return failure.Value.ExitCode;
        }

        var result = TryDeserialize<ScanResult>(invocation.Stdout);
        if (result is null)
        {
            _stderr.WriteLine("读取器返回的 scan 结果不是可解析的 JSON。");
            WriteReaderStderr(invocation);
            return invocation.ExitCode == 0 ? ReaderScanFailed : invocation.ExitCode;
        }

        if (result.State != ReaderState.ScanCompleted)
        {
            _stderr.WriteLine($"读取器未完成扫描：{result.State}。{result.FailureReason}");
            WriteReaderStderr(invocation);
            return invocation.ExitCode == 0 ? ReaderScanFailed : invocation.ExitCode;
        }

        if (options.Json)
        {
            _stdout.WriteLine(JsonSerializer.Serialize(result, ScoutMindJson.Options));
        }
        else
        {
            WriteScanResultHuman(result);
        }

        if (!options.Sync)
        {
            if (result.OutputFile is not null)
            {
                _stdout.WriteLine("未请求同步；可用 `ScoutMind.Agent sync` 或 `sync --file <路径>` 上传。");
            }

            return AgentExitCodes.Success;
        }

        if (result.OutputFile is null)
        {
            _stderr.WriteLine("读取器未给出扫描输出文件路径，无法同步。");
            return ReaderScanFailed;
        }

        var synced = await SyncOneAsync(result.OutputFile, configuration, queue, cancellationToken).ConfigureAwait(false);
        return synced ? AgentExitCodes.Success : AgentExitCodes.SyncFailed;
    }

    private async Task<int> RunWatchAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var minutes = options.IntervalMinutes ?? 0;
        if (minutes <= 0)
        {
            WriteUsageError("watch 需要 --interval-minutes <分钟>。");
            return AgentExitCodes.UsageError;
        }

        var interval = TimeSpan.FromMinutes(minutes);
        _stdout.WriteLine($"开始监视：每 {minutes.ToString(CultureInfo.InvariantCulture)} 分钟执行一次扫描并同步。按 Ctrl+C 停止。");

        var round = 0;
        while (!cancellationToken.IsCancellationRequested)
        {
            round++;
            var scanOptions = options with { Command = AgentCommand.Scan, Sync = true };
            var code = await RunScanAsync(scanOptions, cancellationToken).ConfigureAwait(false);
            _stdout.WriteLine(
                $"[第 {round.ToString(CultureInfo.InvariantCulture)} 轮] {ScoutMindJson.FormatTimestamp(DateTimeOffset.UtcNow)} 退出码 {code.ToString(CultureInfo.InvariantCulture)}");

            try
            {
                await Task.Delay(interval, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }

        _stdout.WriteLine("监视已停止。");
        return AgentExitCodes.Success;
    }

    private async Task<int> RunAutoAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration();
        if (configuration.ReaderPath.Length == 0)
        {
            return ReportMissingReader(configuration);
        }

        var queue = new ScanQueue(configuration.QueueDirectory);
        queue.EnsureCreated();
        if (!string.IsNullOrWhiteSpace(options.AutoControl))
        {
            switch (options.AutoControl)
            {
                case "pause":
                    CaptureControl.Set(configuration.QueueDirectory, "paused");
                    _stdout.WriteLine("自动采集已请求暂停。");
                    return AgentExitCodes.Success;
                case "resume":
                    CaptureControl.Set(configuration.QueueDirectory, "running");
                    _stdout.WriteLine("自动采集已恢复；正在运行的 auto 会在下一轮继续。");
                    return AgentExitCodes.Success;
                case "status":
                    _stdout.WriteLine($"自动采集控制状态：{CaptureControl.Status(configuration.QueueDirectory)}");
                    return AgentExitCodes.Success;
                default:
                    WriteUsageError($"未知 auto 控制参数：{options.AutoControl}");
                    return AgentExitCodes.UsageError;
            }
        }

        var minutes = options.IntervalMinutes ?? 0;
        if (minutes <= 0)
        {
            WriteUsageError("auto 需要 --interval-minutes <分钟>，或 --pause/--resume/--status。");
            return AgentExitCodes.UsageError;
        }

        var captureLock = CaptureLock.TryAcquire(configuration.QueueDirectory, out var lockMessage);
        if (captureLock is null)
        {
            _stderr.WriteLine(lockMessage);
            return AgentExitCodes.UsageError;
        }

        using var _lock = captureLock;
        var stateStore = new CaptureStateStore(configuration.QueueDirectory);
        var readerTimeout = TimeSpan.FromSeconds(Math.Max(180, configuration.Config.TimeoutSeconds + 120));
        var runner = new ReaderRunner(configuration.ReaderPath, readerTimeout);
        var interval = TimeSpan.FromMinutes(minutes);
        var maxRetries = 3;
        var state = stateStore.Load();
        _stdout.WriteLine($"自动采集启动：每 {minutes} 分钟检查；同存档同游戏日期只导入一次。按 Ctrl+C 停止。");

        // Recover files left by a previous crash: retry before starting a new scan.
        foreach (var pending in queue.ListOutstanding())
        {
            _stdout.WriteLine($"恢复待同步文件：{Path.GetFileName(pending)}");
            await SyncOneAsync(pending, configuration, queue, cancellationToken).ConfigureAwait(false);
        }

        var round = 0;
        while (!cancellationToken.IsCancellationRequested)
        {
            if (CaptureControl.IsPaused(configuration.QueueDirectory))
            {
                if (state.Status != "paused")
                {
                    state = state with { Status = "paused" };
                    stateStore.Save(state);
                    _stdout.WriteLine("自动采集已暂停；不启动新扫描，待处理文件保留。");
                }
                await DelayAsync(TimeSpan.FromSeconds(5), cancellationToken).ConfigureAwait(false);
                continue;
            }
            round++;
            var invocation = await runner
                .RunAsync(new[] { "scan", "--output", queue.ScanDirectory, "--json" }, cancellationToken)
                .ConfigureAwait(false);
            var transport = MapReaderTransportFailure(invocation);
            if (transport is not null)
            {
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] {transport.Value.Message}；{RetryDelay(state.ConsecutiveFailures)} 后重试。");
                await DelayAsync(RetryDelay(state.ConsecutiveFailures), cancellationToken).ConfigureAwait(false);
                continue;
            }

            var result = TryDeserialize<ScanResult>(invocation.Stdout);
            if (result is null || result.State != ReaderState.ScanCompleted || result.OutputFile is null)
            {
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 扫描未完成：{result?.FailureReason ?? "无有效结果"}；{RetryDelay(state.ConsecutiveFailures)} 后重试。");
                await DelayAsync(RetryDelay(state.ConsecutiveFailures), cancellationToken).ConfigureAwait(false);
                continue;
            }

            ScanFileInfo info;
            try
            {
                info = await ScanFileReader.ReadInfoAsync(result.OutputFile, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is IOException or JsonException or InvalidDataException)
            {
                queue.EnqueuePending(result.OutputFile);
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 无法读取游戏日期：{ex.Message}；文件留在 pending。");
                await DelayAsync(RetryDelay(state.ConsecutiveFailures), cancellationToken).ConfigureAwait(false);
                continue;
            }

            var saveKey = string.IsNullOrWhiteSpace(configuration.Config.SaveName) ? "default" : configuration.Config.SaveName;
            var sameDate = string.Equals(saveKey, state.SaveName, StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(info.GameDate)
                && string.Equals(info.GameDate, state.LastGameDate, StringComparison.Ordinal);
            if (sameDate)
            {
                var duplicate = queue.ArchiveDuplicate(result.OutputFile);
                state = state with { Status = "completed", ConsecutiveFailures = 0 };
                stateStore.Save(state);
                _stdout.WriteLine($"[第 {round} 轮] 游戏日期 {info.GameDate} 未变化，重复扫描已隔离到 {duplicate}。");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            state = state with { SaveName = saveKey, LastScanId = info.ScanId, Status = "importing" };
            stateStore.Save(state);
            var synced = await SyncOneAsync(result.OutputFile, configuration, queue, cancellationToken).ConfigureAwait(false);
            if (synced)
            {
                state = state with
                {
                    LastGameDate = info.GameDate ?? state.LastGameDate,
                    Status = "completed",
                    ConsecutiveFailures = 0,
                };
                stateStore.Save(state);
                _stdout.WriteLine($"[第 {round} 轮] 已采集 {info.GameDate ?? "日期未知"}（scan_id={info.ScanId}）。");
            }
            else
            {
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                if (state.ConsecutiveFailures >= maxRetries)
                {
                    state = state with { Status = "failed" };
                    stateStore.Save(state);
                    _stderr.WriteLine($"[第 {round} 轮] 连续失败 {state.ConsecutiveFailures} 次，保留 pending 文件等待人工处理。");
                }
            }

            var delay = state.Status == "retry_pending" ? RetryDelay(state.ConsecutiveFailures) : interval;
            await DelayAsync(delay, cancellationToken).ConfigureAwait(false);
        }

        _stdout.WriteLine("自动采集已停止。");
        return AgentExitCodes.Success;
    }

    private static TimeSpan RetryDelay(int failures)
    {
        var seconds = Math.Min(60, Math.Max(5, 5 * (1 << Math.Min(4, Math.Max(0, failures - 1)))));
        return TimeSpan.FromSeconds(seconds);
    }

    private static async Task DelayAsync(TimeSpan delay, CancellationToken cancellationToken)
    {
        try
        {
            await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task<int> RunSyncAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration();
        var queue = new ScanQueue(configuration.QueueDirectory);
        queue.EnsureCreated();

        if (options.FilePath is not null)
        {
            string fullPath;
            try
            {
                fullPath = Path.GetFullPath(options.FilePath);
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
            {
                _stderr.WriteLine($"文件路径非法：{ex.Message}");
                return AgentExitCodes.UsageError;
            }

            if (!File.Exists(fullPath))
            {
                _stderr.WriteLine($"文件不存在：{fullPath}");
                return AgentExitCodes.UsageError;
            }

            var synced = await SyncOneAsync(fullPath, configuration, queue, cancellationToken).ConfigureAwait(false);
            return synced ? AgentExitCodes.Success : AgentExitCodes.SyncFailed;
        }

        var outstanding = queue.ListOutstanding();
        if (outstanding.Count == 0)
        {
            _stdout.WriteLine("没有待同步的扫描结果。");
            return AgentExitCodes.Success;
        }

        var succeeded = 0;
        var failed = 0;
        foreach (var file in outstanding)
        {
            if (await SyncOneAsync(file, configuration, queue, cancellationToken).ConfigureAwait(false))
            {
                succeeded++;
            }
            else
            {
                failed++;
            }
        }

        _stdout.WriteLine($"同步完成：成功 {succeeded.ToString(CultureInfo.InvariantCulture)}，失败 {failed.ToString(CultureInfo.InvariantCulture)}。");
        return failed == 0 ? AgentExitCodes.Success : AgentExitCodes.SyncFailed;
    }

    private int RunConfigShow()
    {
        // The diagnostics are part of the JSON view, so they are not echoed to stderr here.
        var configuration = LoadConfiguration(echoDiagnostics: false);
        var view = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["readerPath"] = configuration.ReaderPath,
            ["engine"] = string.IsNullOrWhiteSpace(configuration.Config.ScannerPath) ? "native" : "external",
            ["scannerPath"] = configuration.Config.ScannerPath,
            ["probeArguments"] = configuration.Config.ProbeArguments,
            ["scanArgumentsTemplate"] = configuration.Config.ScanArgumentsTemplate,
            ["timeoutSeconds"] = configuration.Config.TimeoutSeconds,
            ["backendBaseUrl"] = configuration.Config.BackendBaseUrl,
            ["apiToken"] = string.IsNullOrWhiteSpace(configuration.Config.ApiToken) ? null : "***（已配置，已隐藏）",
            ["saveName"] = configuration.Config.SaveName,
            ["queueDirectory"] = configuration.QueueDirectory,
            ["diagnostics"] = configuration.Diagnostics,
        };

        _stdout.WriteLine(JsonSerializer.Serialize(view, ScoutMindJson.Options));
        return AgentExitCodes.Success;
    }

    private async Task<bool> SyncOneAsync(
        string path,
        AgentRuntimeConfiguration configuration,
        ScanQueue queue,
        CancellationToken cancellationToken)
    {
        var claimed = queue.Claim(path);
        if (claimed is null)
        {
            _stderr.WriteLine($"扫描文件不存在：{path}");
            return false;
        }

        var metaPath = ScanQueue.MetaPathFor(claimed);
        var manifestPath = ScanQueue.ManifestPathFor(claimed);
        ScanManifest manifest;
        try
        {
            manifest = await ScanManifest.EnsureAsync(claimed, metaPath, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Text.Json.JsonException)
        {
            _stderr.WriteLine($"无法为 {Path.GetFileName(claimed)} 建立 manifest：{ex.Message}");
            queue.EnqueuePending(claimed);
            return false;
        }

        var integrity = await ScanIntegrityValidator
            .ValidateAsync(claimed, metaPath, manifestPath, cancellationToken)
            .ConfigureAwait(false);
        if (!integrity.Valid)
        {
            var folder = queue.QuarantineAll(claimed, new
            {
                quarantined_at = DateTimeOffset.UtcNow.ToString("O"),
                code = integrity.Code,
                message = integrity.Message,
                actual_sha256 = integrity.ActualSha256,
                actual_size = integrity.ActualSize,
                scan_id = integrity.ScanId,
                manifest_scan_id = manifest.ScanId,
                manifest_payload_sha256 = manifest.PayloadSha256,
                source_envelope = claimed,
                source_meta = metaPath,
            });
            _stderr.WriteLine($"完整性校验失败（{Path.GetFileName(claimed)}）：{integrity.Code} {integrity.Message}；已隔离到 {folder}");
            return false;
        }

        ScanFilePayload payload;
        try
        {
            payload = await ScanFileReader.LoadAsync(claimed, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or InvalidDataException or UnauthorizedAccessException)
        {
            _stderr.WriteLine($"读取扫描文件失败（{claimed}）：{ex.Message}");
            queue.EnqueuePending(claimed);
            return false;
        }

        using var client = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);

        BackendSyncResult result;
        try
        {
            result = await client.PostScanAsync(payload.Json, cancellationToken).ConfigureAwait(false);
        }
        catch (ArgumentException ex)
        {
            _stderr.WriteLine($"后端地址配置错误：{ex.Message}");
            queue.EnqueuePending(claimed);
            return false;
        }

        if (result.Ok)
        {
            var duplicateNote = result.Duplicate ? "（后端报告 duplicate=true，未重复写入）" : string.Empty;
            var statusCode = result.StatusCode?.ToString(CultureInfo.InvariantCulture) ?? "—";
            var archived = queue.ArchiveAll(claimed);
            _stdout.WriteLine($"已同步 {Path.GetFileName(claimed)}：scan_id={payload.ScanId}，HTTP {statusCode}{duplicateNote}；归档 {archived}");
            return true;
        }

        // A timeout is not a verdict: ask the backend whether the import already finished.
        var job = await client.GetJobAsync(payload.ScanId, cancellationToken).ConfigureAwait(false);
        if (job is { IsComplete: true })
        {
            var archived = queue.ArchiveAll(claimed);
            _stdout.WriteLine(
                $"上传未收到响应，但后端已完成导入：任务 #{job.Id} status={job.Status}，球员 {job.PlayerCount}；归档 {archived}");
            return true;
        }

        if (job is { Status: "failed" })
        {
            var folder = queue.FailAll(claimed, new
            {
                failed_at = DateTimeOffset.UtcNow.ToString("O"),
                code = "backend_import_failed",
                message = result.Error,
                http_status = result.StatusCode,
                response = result.ResponseBody,
                job_id = job.Id,
                job_status = job.Status,
            });
            _stderr.WriteLine($"后端导入失败（任务 #{job.Id}）：{result.Error}；已移入 {folder}");
            return false;
        }

        if (result.StatusCode is 400 or 422)
        {
            var folder = queue.FailAll(claimed, new
            {
                failed_at = DateTimeOffset.UtcNow.ToString("O"),
                code = "backend_rejected",
                message = result.Error,
                http_status = result.StatusCode,
                response = result.ResponseBody,
            });
            _stderr.WriteLine($"后端拒绝该报文（HTTP {result.StatusCode}）：{result.Error}；已移入 {folder}");
            return false;
        }

        if (job is not null)
        {
            _stderr.WriteLine($"后端仍在导入（任务 #{job.Id} status={job.Status}）：保留待重试，不归档。");
        }
        else
        {
            _stderr.WriteLine($"同步失败（{Path.GetFileName(claimed)}）：{result.Error}");
        }

        if (result.ResponseBody is not null)
        {
            _stderr.WriteLine($"后端响应：{result.ResponseBody}");
        }

        var pending = queue.EnqueuePending(claimed);
        if (pending is not null)
        {
            _stderr.WriteLine($"已加入待重试队列：{pending}");
        }

        return false;
    }

    private AgentRuntimeConfiguration LoadConfiguration(bool echoDiagnostics = true)
    {
        var configuration = AgentConfiguration.Load(_baseDirectory);
        if (!echoDiagnostics)
        {
            return configuration;
        }

        foreach (var diagnostic in configuration.Diagnostics)
        {
            _stderr.WriteLine($"· {diagnostic}");
        }

        return configuration;
    }

    private int ReportMissingReader(AgentRuntimeConfiguration configuration)
    {
        _stderr.WriteLine("未找到 ScoutMind 读取器，无法继续。");
        foreach (var diagnostic in configuration.Diagnostics)
        {
            _stderr.WriteLine($"· {diagnostic}");
        }

        return AgentExitCodes.ConfigurationError;
    }

    private static (int ExitCode, string Message)? MapReaderTransportFailure(ReaderInvocation invocation)
    {
        if (invocation.StartError is not null)
        {
            return (AgentExitCodes.ConfigurationError, invocation.StartError);
        }

        if (invocation.TimedOut)
        {
            return (ReaderScanFailed, "读取器调用超时，已终止其进程树。");
        }

        return null;
    }

    private void WriteReaderStderr(ReaderInvocation invocation)
    {
        if (!string.IsNullOrWhiteSpace(invocation.Stderr))
        {
            _stderr.WriteLine(invocation.Stderr.Trim());
        }
    }

    private static T? TryDeserialize<T>(string json)
        where T : class
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<T>(json, ScoutMindJson.Options);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private void WriteStatusHuman(ReaderStatus status)
    {
        _stdout.WriteLine($"状态        : {status.State}");
        _stdout.WriteLine($"说明        : {status.Message}");
        _stdout.WriteLine($"检测时间    : {ScoutMindJson.FormatTimestamp(status.DetectedAt)}");
        _stdout.WriteLine($"FM27 进程   : {(status.Process is null ? "未运行" : $"pid {status.Process.Pid.ToString(CultureInfo.InvariantCulture)}")}");
        _stdout.WriteLine($"游戏        : {(status.Game is null ? "—" : $"appId={status.Game.AppId} build={status.Game.BuildId ?? "—"}")}");
        _stdout.WriteLine($"插件        : {status.Plugin?.ProductVersion ?? "—"}");
        _stdout.WriteLine($"兼容性      : {status.Compatibility?.Reason ?? "未判定"}");

        if (status.Diagnostics.Count > 0)
        {
            _stdout.WriteLine("诊断：");
            foreach (var diagnostic in status.Diagnostics)
            {
                _stdout.WriteLine($"  - {diagnostic}");
            }
        }
    }

    private void WriteScanResultHuman(ScanResult result)
    {
        _stdout.WriteLine($"扫描状态    : {result.State}");
        _stdout.WriteLine($"扫描 ID     : {result.ScanId}");
        _stdout.WriteLine($"球员数量    : {result.PlayersCount.ToString(CultureInfo.InvariantCulture)}");
        _stdout.WriteLine($"转会数量    : {result.TransfersCount.ToString(CultureInfo.InvariantCulture)}");
        _stdout.WriteLine($"输出文件    : {result.OutputFile ?? "—"}");

        if (result.Warnings.Count > 0)
        {
            _stdout.WriteLine("告警：");
            foreach (var warning in result.Warnings)
            {
                _stdout.WriteLine($"  - {warning}");
            }
        }
    }

    private void WriteUsageError(string message)
    {
        _stderr.WriteLine($"参数错误：{message}");
        WriteUsage(_stderr);
    }

    private void WriteUsage(TextWriter writer)
    {
        writer.WriteLine("用法：");
        writer.WriteLine("  ScoutMind.Agent status [--json]");
        writer.WriteLine("  ScoutMind.Agent scan [--sync] [--json]");
        writer.WriteLine("  ScoutMind.Agent watch --interval-minutes <分钟>");
        writer.WriteLine("  ScoutMind.Agent auto --interval-minutes <分钟>   # 同存档同游戏日期只导入一次");
        writer.WriteLine("  ScoutMind.Agent sync [--file <路径>]");
        writer.WriteLine("  ScoutMind.Agent config show");
        writer.WriteLine();
        writer.WriteLine("退出码：");
        writer.WriteLine("  0  成功");
        writer.WriteLine("  2  未找到 FM27（透传读取器）");
        writer.WriteLine("  3  构建或版本不受支持 / 无法确定（透传读取器）");
        writer.WriteLine("  4  probe 失败（透传读取器）");
        writer.WriteLine("  5  扫描失败（透传读取器）");
        writer.WriteLine("  6  后端同步失败");
        writer.WriteLine("  64 用法错误");
        writer.WriteLine("  65 配置错误（找不到读取器或配置非法）");
    }
}
