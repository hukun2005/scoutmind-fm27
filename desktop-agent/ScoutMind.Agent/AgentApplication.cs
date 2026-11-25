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

            case AgentCommand.Diagnostics:
                return await RunDiagnosticsAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Jobs:
                return await RunJobsAsync(options, cancellationToken).ConfigureAwait(false);

            case AgentCommand.Network:
                return await RunNetworkAsync(cancellationToken).ConfigureAwait(false);

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

        // 手动同步也走身份链路：能拿到 verified 身份时登记会话并按 save_id 上传，
        // 避免把另一个存档的数据写进「当前存档」（D-01）。
        SaveContextQuery? context = null;
        using var identityClient = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);
        var identitySync = new SaveIdentitySync(identityClient);
        runner.AutomaticSnapshot = true;
        var gate = await EvaluateAutoGateAsync(runner, cancellationToken).ConfigureAwait(false);
        if (gate.Identity.Allowed)
        {
            var binding = await identitySync
                .EnsureAsync(gate.Identity, cancellationToken, configuration.Config.SaveName)
                .ConfigureAwait(false);
            if (binding.Ok)
            {
                context = identitySync.Context;
            }
            else
            {
                _stderr.WriteLine($"存档身份/会话登记失败，本次按无上下文上传：{binding.Error}");
            }
        }
        else
        {
            _stderr.WriteLine(
                $"存档身份未通过安全门（{gate.Identity.Status}），本次按无上下文上传；需要多存档隔离时请先确认身份：{string.Join("；", gate.Identity.Reasons)}");
        }

        var synced = await SyncOneAsync(result.OutputFile, configuration, queue, cancellationToken, context)
            .ConfigureAwait(false);
        await identitySync.InvalidateAsync("scan_sync_finished", CancellationToken.None).ConfigureAwait(false);
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
        var runner = new ReaderRunner(configuration.ReaderPath, readerTimeout)
        {
            // auto 是用户显式开启的自动采集路径；读取器仍只对 verified 身份报告可快照。
            AutomaticSnapshot = true,
        };
        using var identityClient = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);
        var identitySync = new SaveIdentitySync(identityClient);
        var interval = TimeSpan.FromMinutes(minutes);
        var maxRetries = 3;
        var state = stateStore.Load();
        _stdout.WriteLine($"自动采集启动：每 {minutes} 分钟检查；存档身份未验证或日期未通过跨进程验证前不会导入。按 Ctrl+C 停止。");

        // V3.2.7.4：重启后不信任遗留任务，也不允许无上下文上传。
        // 缺少 context 边车 → 隔离；有上下文 → 等身份重新验证后按指纹决定是否恢复。
        var pendingRecovery = new List<(string Path, ScanTaskContext Context)>();
        foreach (var pending in queue.ListOutstanding())
        {
            var saved = ScanTaskContext.TryLoad(ScanQueue.ContextPathFor(pending));
            if (saved is null)
            {
                var folder = queue.QuarantineAll(pending, new
                {
                    quarantined_at = DateTimeOffset.UtcNow.ToString("O"),
                    code = "context_missing",
                    message = "重启后发现任务缺少写入上下文；为避免旧任务改绑当前存档，未自动上传。",
                });
                _stderr.WriteLine($"恢复中止：{Path.GetFileName(pending)} 缺少上下文，已隔离到 {folder}");
                continue;
            }

            pendingRecovery.Add((pending, saved));
            _stdout.WriteLine($"发现待恢复任务：{Path.GetFileName(pending)}（operation_id={saved.OperationId}）");
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
            var gate = await EvaluateAutoGateAsync(runner, cancellationToken).ConfigureAwait(false);
            if (!gate.Allowed)
            {
                var gateStatus = gate.Identity.Allowed ? "date_unverified" : "identity_blocked";
                if (state.Status != gateStatus)
                {
                    state = state with { Status = gateStatus };
                    stateStore.Save(state);
                }

                var label = gate.Identity.Allowed ? "日期" : "存档身份";
                _stdout.WriteLine(
                    $"[第 {round} 轮] {label}未通过安全门（{gate.Status}）：自动快照保持关闭；{string.Join("；", gate.Reasons)}");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            var binding = await identitySync
                .EnsureAsync(gate.Identity, cancellationToken, configuration.Config.SaveName)
                .ConfigureAwait(false);
            if (!binding.Ok)
            {
                // 后端不可达或会话未 verified：本轮不得写入，也不得伪造成功。
                state = state with { Status = "identity_sync_failed" };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 存档身份/会话未能在后端建立：{binding.Error}");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            // 身份与会话已经服务端确认：只有同一指纹的遗留任务才恢复，其余隔离。
            foreach (var (path, saved) in pendingRecovery.ToList())
            {
                if (!saved.BelongsTo(gate.Identity.Fingerprint))
                {
                    var folder = queue.QuarantineAll(path, new
                    {
                        quarantined_at = DateTimeOffset.UtcNow.ToString("O"),
                        code = "context_mismatch",
                        message = "任务上下文与当前已验证存档不一致；旧任务不得自动改绑到新的存档。",
                        saved_fingerprint = saved.Fingerprint,
                        current_fingerprint = gate.Identity.Fingerprint,
                        operation_id = saved.OperationId,
                    });
                    pendingRecovery.Remove((path, saved));
                    _stderr.WriteLine($"恢复中止：{Path.GetFileName(path)} 属于其他存档，已隔离到 {folder}");
                    continue;
                }

                _stdout.WriteLine($"恢复上传（同一存档，operation_id={saved.OperationId}）：{Path.GetFileName(path)}");
                var recovered = await SyncOneAsync(
                        path,
                        configuration,
                        queue,
                        cancellationToken,
                        identitySync.Context,
                        gate.Identity.Fingerprint,
                        saved)
                    .ConfigureAwait(false);
                if (recovered)
                {
                    pendingRecovery.Remove((path, saved));
                }
            }

            // 采集开始时登记 capture_context；没有 capture_id 就不进入扫描后的写入路径。
            var capture = await identityClient.StartCaptureAsync(
                new
                {
                    game_build = gate.Identity.GameBuild,
                    scan_scope = "players",
                    status = "scanning",
                    metadata = new
                    {
                        session_key = gate.Identity.SessionKey,
                        fingerprint = gate.Identity.Fingerprint,
                    },
                },
                cancellationToken,
                identitySync.Context).ConfigureAwait(false);
            var captureId = capture.Ok ? capture.ReadInt("id") : null;
            if (captureId is null)
            {
                state = state with { Status = "identity_sync_failed" };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 无法登记采集上下文：{capture.Error}");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            async Task MarkCaptureAsync(string status, string? errorCode = null)
            {
                await identityClient.UpdateCaptureAsync(
                    captureId.Value,
                    new { status, error_code = errorCode },
                    CancellationToken.None,
                    identitySync.Context).ConfigureAwait(false);
            }

            var invocation = await runner
                .RunAsync(new[] { "scan", "--output", queue.ScanDirectory, "--json" }, cancellationToken)
                .ConfigureAwait(false);
            var transport = MapReaderTransportFailure(invocation);
            if (transport is not null)
            {
                await MarkCaptureAsync("failed", "reader_transport_failed").ConfigureAwait(false);
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] {transport.Value.Message}；{RetryDelay(state.ConsecutiveFailures)} 后重试。");
                await DelayAsync(RetryDelay(state.ConsecutiveFailures), cancellationToken).ConfigureAwait(false);
                continue;
            }

            var result = TryDeserialize<ScanResult>(invocation.Stdout);
            if (result is null || result.State != ReaderState.ScanCompleted || result.OutputFile is null)
            {
                await MarkCaptureAsync("failed", "reader_scan_incomplete").ConfigureAwait(false);
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
                await MarkCaptureAsync("failed", "scan_manifest_unreadable").ConfigureAwait(false);
                queue.EnqueuePending(result.OutputFile);
                state = state with { Status = "retry_pending", ConsecutiveFailures = state.ConsecutiveFailures + 1 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 无法读取游戏日期：{ex.Message}；文件留在 pending。");
                await DelayAsync(RetryDelay(state.ConsecutiveFailures), cancellationToken).ConfigureAwait(false);
                continue;
            }

            // 采集后复核：扫描期间若存档发生切换，本轮结果必须作废，不能写入旧存档。
            var afterScan = await ReadSaveIdentityAsync(runner, cancellationToken).ConfigureAwait(false);
            if (gate.Identity.ChangeKey is { } beforeKey
                && afterScan.ChangeKey is { } afterKey
                && !string.Equals(beforeKey, afterKey, StringComparison.Ordinal))
            {
                var folder = queue.FailAll(result.OutputFile, new
                {
                    failed_at = DateTimeOffset.UtcNow.ToString("O"),
                    code = "save_changed_during_capture",
                    message = "扫描期间检测到存档身份或会话变化，本轮结果已作废。",
                    previous_identity = beforeKey,
                    current_identity = afterKey,
                    scan_id = info.ScanId,
                });
                await identitySync.InvalidateAsync("save_switched", cancellationToken).ConfigureAwait(false);
                await identityClient.UpdateCaptureAsync(
                    captureId.Value,
                    new { status = "failed", error_code = "save_changed_during_capture", scan_id = info.ScanId },
                    CancellationToken.None,
                    null).ConfigureAwait(false);
                state = state with { Status = "identity_changed", ConsecutiveFailures = 0 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 扫描期间存档发生变化：{beforeKey} → {afterKey}；结果已移入 {folder}");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            var saveKey = string.IsNullOrWhiteSpace(gate.Identity.Fingerprint)
                ? (string.IsNullOrWhiteSpace(configuration.Config.SaveName) ? "default" : configuration.Config.SaveName)
                : gate.Identity.Fingerprint;
            var sameDate = string.Equals(saveKey, state.SaveName, StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(info.GameDate)
                && string.Equals(info.GameDate, state.LastGameDate, StringComparison.Ordinal);
            if (sameDate)
            {
                var duplicate = queue.ArchiveDuplicate(result.OutputFile);
                await MarkCaptureAsync("completed").ConfigureAwait(false);
                state = state with { Status = "completed", ConsecutiveFailures = 0 };
                stateStore.Save(state);
                _stdout.WriteLine($"[第 {round} 轮] 游戏日期 {info.GameDate} 未变化，重复扫描已隔离到 {duplicate}。");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            // 结果落盘后、导入前再次确认会话可写：扫描可能耗时较久，期间会话可能被切换或超时失效。
            var submit = await identitySync
                .EnsureAsync(afterScan, cancellationToken, configuration.Config.SaveName)
                .ConfigureAwait(false);
            if (!submit.Ok)
            {
                var folder = queue.FailAll(result.OutputFile, new
                {
                    failed_at = DateTimeOffset.UtcNow.ToString("O"),
                    code = "save_session_invalidated",
                    message = "提交前复核失败：会话或身份不可写，本轮结果已作废。",
                    detail = submit.Error,
                    scan_id = info.ScanId,
                });
                await MarkCaptureAsync("failed", "save_session_invalidated").ConfigureAwait(false);
                state = state with { Status = "identity_changed", ConsecutiveFailures = 0 };
                stateStore.Save(state);
                _stderr.WriteLine($"[第 {round} 轮] 提交前会话复核失败：{submit.Error}；结果已移入 {folder}");
                await DelayAsync(interval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            state = state with { SaveName = saveKey, LastScanId = info.ScanId, Status = "importing" };
            stateStore.Save(state);
            var synced = await SyncOneAsync(result.OutputFile, configuration, queue, cancellationToken, identitySync.Context)
                .ConfigureAwait(false);
            if (synced)
            {
                await identityClient.UpdateCaptureAsync(
                    captureId.Value,
                    new { status = "completed", scan_id = info.ScanId },
                    CancellationToken.None,
                    identitySync.Context).ConfigureAwait(false);
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
                await MarkCaptureAsync("failed", "import_failed").ConfigureAwait(false);
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
        await identitySync.InvalidateAsync("agent_stopped", CancellationToken.None).ConfigureAwait(false);
        return AgentExitCodes.Success;
    }

    private static async Task<AutoGate> EvaluateAutoGateAsync(
        ReaderRunner runner,
        CancellationToken cancellationToken)
    {
        var identity = await ReadSaveIdentityAsync(runner, cancellationToken).ConfigureAwait(false);
        if (!identity.Allowed)
        {
            return new AutoGate(identity, SnapshotGate.Blocked("存档身份安全门未通过，未继续验证日期。"));
        }

        var invocation = await runner
            .RunAsync(new[] { "world-date", "--diagnostics", "--json" }, cancellationToken)
            .ConfigureAwait(false);
        if (invocation.StartError is not null)
        {
            return new AutoGate(identity, SnapshotGate.Blocked($"无法启动读取器做日期验证：{invocation.StartError}"));
        }

        if (invocation.TimedOut)
        {
            return new AutoGate(identity, SnapshotGate.Blocked("读取器日期验证超时。"));
        }

        return new AutoGate(identity, ReaderSnapshotGate.Parse(invocation.Stdout));
    }

    private static async Task<SaveIdentityGate> ReadSaveIdentityAsync(
        ReaderRunner runner,
        CancellationToken cancellationToken)
    {
        var invocation = await runner
            .RunAsync(new[] { "save-identity", "--diagnostics", "--json" }, cancellationToken)
            .ConfigureAwait(false);
        if (invocation.StartError is not null)
        {
            return SaveIdentityGate.Blocked($"无法启动读取器做身份验证：{invocation.StartError}");
        }

        if (invocation.TimedOut)
        {
            return SaveIdentityGate.Blocked("读取器身份验证超时。");
        }

        return ReaderSaveIdentityGate.Parse(invocation.Stdout);
    }

    /// <summary>身份安全门与日期安全门的合并结论：两者都允许才允许采集。</summary>
    private sealed record AutoGate(SaveIdentityGate Identity, SnapshotGate Date)
    {
        public bool Allowed => Identity.Allowed && Date.Allowed;

        public string Status => Identity.Allowed ? Date.Status : Identity.Status;

        public IReadOnlyList<string> Reasons => Identity.Allowed ? Date.Reasons : Identity.Reasons;
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
        CancellationToken cancellationToken,
        SaveContextQuery? context = null,
        string? fingerprint = null,
        ScanTaskContext? taskContext = null)
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
            // V3.2.7.3/4：operation_id 固定写入 context 边车；同一文件重试沿用同一 ID，后端据此幂等。
            // 内容一旦变化（manifest.PayloadSha256 改变）就会生成新的 ID，避免把新内容当旧请求。
            var contextPath = ScanQueue.ContextPathFor(claimed);
            var savedContext = taskContext ?? ScanTaskContext.TryLoad(contextPath);
            var operationId = savedContext?.OperationId
                ?? "op-" + manifest.PayloadSha256[..Math.Min(32, manifest.PayloadSha256.Length)];
            if (context is not null && savedContext is null && !string.IsNullOrWhiteSpace(fingerprint))
            {
                new ScanTaskContext(
                        context.SaveId ?? 0,
                        context.IdentityId,
                        context.SessionId,
                        fingerprint,
                        operationId,
                        manifest.PayloadSha256,
                        DateTimeOffset.UtcNow.ToString("O"))
                    .Save(contextPath);
            }

            // 存档 id 必须随请求一起发送：后端据此写入对应 fm_save，而不是回落到「当前存档」（D-01）。
            var saveId = context?.SaveId ?? savedContext?.SaveId;
            var uploadContext = context is null
                ? null
                : new SaveContextQuery(context.IdentityId, context.SessionId, operationId, saveId is > 0 ? saveId : null);
            result = await client.PostScanAsync(payload.Json, cancellationToken, uploadContext).ConfigureAwait(false);
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

        if (job is { Status: "rejected" })
        {
            var folder = queue.FailAll(claimed, new
            {
                failed_at = DateTimeOffset.UtcNow.ToString("O"),
                code = job.RejectedReason ?? "write_rejected",
                message = "后端因写入安全策略拒绝了该 operation；需要重新识别存档并重新采集。",
                http_status = result.StatusCode,
                job_id = job.Id,
                job_status = job.Status,
            });
            _stderr.WriteLine($"后端拒绝写入（任务 #{job.Id}，{job.RejectedReason}）：已移入 {folder}");
            return false;
        }

        // 取消/上下文失效/内容冲突都不是“稍后重试就好”的临时错误：停止重试并保留证据。
        var failureCode = TryReadErrorCode(result.ResponseBody);
        if (failureCode is "import_cancelled" or "operation_rejected" or "operation_conflict" or "scan_payload_mismatch")
        {
            var folder = queue.FailAll(claimed, new
            {
                failed_at = DateTimeOffset.UtcNow.ToString("O"),
                code = failureCode,
                message = "后端明确拒绝该任务，自动重试不会成功；请重新采集或重新识别存档。",
                http_status = result.StatusCode,
                response = result.ResponseBody,
                job_id = job?.Id,
                job_status = job?.Status,
            });
            _stderr.WriteLine($"任务终止（{failureCode}）：已移入 {folder}");
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

    private static string? TryReadErrorCode(string? body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            return document.RootElement.TryGetProperty("detail", out var detail)
                && detail.ValueKind == JsonValueKind.Object
                && detail.TryGetProperty("code", out var code)
                && code.ValueKind == JsonValueKind.String
                    ? code.GetString()
                    : null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>诊断：队列、任务上下文、采集状态、后端可达性与最近导入任务。</summary>
    private async Task<int> RunDiagnosticsAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration(echoDiagnostics: false);
        var queue = new ScanQueue(configuration.QueueDirectory);
        var state = new CaptureStateStore(configuration.QueueDirectory).Load();
        using var client = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);
        var probe = await client.ProbeAsync(cancellationToken).ConfigureAwait(false);
        var jobs = await client.GetRecentJobsAsync(10, cancellationToken).ConfigureAwait(false);
        var contexts = queue.ListOutstanding()
            .Select(path => new
            {
                file = Path.GetFileName(path),
                context = ScanTaskContext.TryLoad(ScanQueue.ContextPathFor(path)),
            })
            .ToArray();
        var view = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["agent"] = $"agent-{Environment.MachineName}-{Environment.ProcessId}",
            ["backendBaseUrl"] = configuration.Config.BackendBaseUrl,
            ["backend_reachable"] = probe is not null,
            ["backend_http_status"] = probe,
            ["queue"] = new Dictionary<string, int>(StringComparer.Ordinal)
            {
                ["scans"] = CountEnvelopes(queue.ScanDirectory),
                ["pending"] = CountEnvelopes(queue.PendingDirectory),
                ["processing"] = CountEnvelopes(queue.ProcessingDirectory),
                ["failed"] = CountEnvelopes(queue.FailedDirectory),
                ["duplicates"] = CountEnvelopes(queue.DuplicatesDirectory),
                ["quarantine"] = Directory.Exists(queue.QuarantineDirectory)
                    ? Directory.GetDirectories(queue.QuarantineDirectory).Length
                    : 0,
            },
            ["capture_state"] = state,
            ["outstanding_contexts"] = contexts,
            ["recent_jobs"] = jobs,
        };

        if (options.Json)
        {
            _stdout.WriteLine(JsonSerializer.Serialize(view, ScoutMindJson.Options));
        }
        else
        {
            _stdout.WriteLine($"后端：{configuration.Config.BackendBaseUrl}（可达={probe is not null}，HTTP {probe?.ToString(CultureInfo.InvariantCulture) ?? "—"}）");
            _stdout.WriteLine($"队列：scans={CountEnvelopes(queue.ScanDirectory)} pending={CountEnvelopes(queue.PendingDirectory)} processing={CountEnvelopes(queue.ProcessingDirectory)} failed={CountEnvelopes(queue.FailedDirectory)} duplicates={CountEnvelopes(queue.DuplicatesDirectory)}");
            _stdout.WriteLine($"采集状态：{state.Status}，存档={state.SaveName ?? "—"}，最近日期={state.LastGameDate ?? "—"}，连续失败={state.ConsecutiveFailures}");
            if (contexts.Length == 0)
            {
                _stdout.WriteLine("待恢复任务：无");
            }
            else
            {
                _stdout.WriteLine($"待恢复任务：{contexts.Length}");
                foreach (var item in contexts)
                {
                    var operation = item.context?.OperationId ?? "（缺少 context，恢复时会被隔离）";
                    _stdout.WriteLine($"  · {item.file} → {operation}");
                }
            }

            _stdout.WriteLine($"最近导入任务：{jobs.Count}");
            foreach (var job in jobs)
            {
                _stdout.WriteLine($"  · #{job.Id} {job.ScanId} status={job.Status} players={job.PlayerCount} attempts={job.AttemptCount} rejected={job.RejectedReason ?? "—"}");
            }
        }

        return probe is null ? AgentExitCodes.SyncFailed : AgentExitCodes.Success;
    }

    private async Task<int> RunJobsAsync(AgentOptions options, CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration(echoDiagnostics: false);
        using var client = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);

        if (string.Equals(options.AutoControl, "inspect", StringComparison.Ordinal))
        {
            var job = await client.GetJobAsync(options.ScanId!, cancellationToken).ConfigureAwait(false);
            if (job is null)
            {
                _stderr.WriteLine($"未找到 scan_id={options.ScanId} 的导入任务（或后端不可达）。");
                return AgentExitCodes.SyncFailed;
            }

            if (options.Json)
            {
                _stdout.WriteLine(JsonSerializer.Serialize(job, ScoutMindJson.Options));
            }
            else
            {
                _stdout.WriteLine($"#{job.Id} {job.ScanId} status={job.Status} players={job.PlayerCount} transfers={job.TransferCount} attempts={job.AttemptCount} rejected={job.RejectedReason ?? "—"}");
            }

            return job.IsTerminal ? AgentExitCodes.Success : AgentExitCodes.SyncFailed;
        }

        var jobs = await client.GetRecentJobsAsync(20, cancellationToken).ConfigureAwait(false);
        if (options.Json)
        {
            _stdout.WriteLine(JsonSerializer.Serialize(jobs, ScoutMindJson.Options));
        }
        else if (jobs.Count == 0)
        {
            _stdout.WriteLine("后端没有可显示的导入任务（或后端不可达）。");
        }
        else
        {
            foreach (var job in jobs)
            {
                _stdout.WriteLine($"#{job.Id} {job.ScanId} status={job.Status} players={job.PlayerCount} attempts={job.AttemptCount} rejected={job.RejectedReason ?? "—"}");
            }
        }

        return jobs.Count == 0 ? AgentExitCodes.SyncFailed : AgentExitCodes.Success;
    }

    private async Task<int> RunNetworkAsync(CancellationToken cancellationToken)
    {
        var configuration = LoadConfiguration(echoDiagnostics: false);
        using var client = new BackendClient(
            configuration.Config.BackendBaseUrl,
            configuration.Config.ApiToken,
            _syncTimeout);
        var probe = await client.ProbeAsync(cancellationToken).ConfigureAwait(false);
        if (probe is null)
        {
            _stderr.WriteLine($"无法连接后端：{configuration.Config.BackendBaseUrl}");
            return AgentExitCodes.SyncFailed;
        }

        _stdout.WriteLine($"后端可达：{configuration.Config.BackendBaseUrl}（HTTP {probe.Value.ToString(CultureInfo.InvariantCulture)}）");
        return AgentExitCodes.Success;
    }

    private static int CountEnvelopes(string directory) =>
        Directory.Exists(directory)
            ? Directory.GetFiles(directory, "scan-*.json")
                .Count(path => !path.EndsWith(".meta.json", StringComparison.OrdinalIgnoreCase)
                    && !path.EndsWith(".manifest.json", StringComparison.OrdinalIgnoreCase)
                    && !path.EndsWith(".context.json", StringComparison.OrdinalIgnoreCase))
            : 0;

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
        writer.WriteLine("  ScoutMind.Agent diagnostics [--json]              # 队列/上下文/后端可达性/最近任务");
        writer.WriteLine("  ScoutMind.Agent jobs list [--json]");
        writer.WriteLine("  ScoutMind.Agent jobs inspect <scan_id> [--json]");
        writer.WriteLine("  ScoutMind.Agent network status");
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
