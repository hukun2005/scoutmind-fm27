using System.Globalization;
using ScoutMind.Contracts;
using ScoutMind.FMReader.Engine;

namespace ScoutMind.Reader;

/// <summary>
/// 扫描后端：外部扫描器或内置只读引擎。两者的 probe/scan 契约一致，CLI 只依赖这一层。
/// </summary>
public interface IScanBackend
{
    /// <summary>后端名称，写入诊断。</summary>
    string Name { get; }

    /// <summary>执行 probe。</summary>
    /// <param name="state">当前状态，必须是 <see cref="ReaderState.Compatible"/>。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>probe 结果。</returns>
    Task<ProbeResult> ProbeAsync(ReaderState state, CancellationToken cancellationToken);

    /// <summary>执行扫描。</summary>
    /// <param name="request">扫描请求。</param>
    /// <param name="state">当前状态，必须是 <see cref="ReaderState.ProbePassed"/>。</param>
    /// <param name="game">本机检测到的游戏信息。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    Task<ScanResult> ScanAsync(ScanRequest request, ReaderState state, GameInfo? game, CancellationToken cancellationToken);

    /// <summary>在开始扫描前确认后端可用。</summary>
    /// <exception cref="ScannerConfigurationException">配置缺失或不合法。</exception>
    void EnsureUsable();
}

/// <summary>外部扫描器后端（保留原有能力，不再作为默认路径）。</summary>
public sealed class ExternalScanBackend : IScanBackend
{
    private readonly ScannerAdapter _adapter;

    /// <summary>创建后端。</summary>
    /// <param name="adapter">外部扫描器适配器。</param>
    public ExternalScanBackend(ScannerAdapter adapter)
    {
        _adapter = adapter ?? throw new ArgumentNullException(nameof(adapter));
    }

    /// <inheritdoc />
    public string Name => "external-scanner";

    /// <inheritdoc />
    public Task<ProbeResult> ProbeAsync(ReaderState state, CancellationToken cancellationToken) =>
        _adapter.ProbeAsync(state, cancellationToken);

    /// <inheritdoc />
    public Task<ScanResult> ScanAsync(ScanRequest request, ReaderState state, GameInfo? game, CancellationToken cancellationToken) =>
        _adapter.ScanAsync(request, state, game, cancellationToken);

    /// <inheritdoc />
    public void EnsureUsable() => _adapter.EnsureScannerConfigured();
}

/// <summary>
/// 内置只读引擎后端：调用 <see cref="IFmScanEngine"/>，把协议报文交给既有的信封与落盘管线。
///
/// 它不依赖任何外部可执行文件；引擎自身的版本闸门与读取器的兼容清单是两道独立闸门，都通过才会读取内存。
/// </summary>
public sealed class NativeScanBackend : IScanBackend
{
    private readonly IFmScanEngine _engine;
    private readonly List<string> _diagnostics = new();

    /// <summary>创建后端。</summary>
    /// <param name="engine">只读扫描引擎；默认使用 FMSuperScout 内核。</param>
    public NativeScanBackend(IFmScanEngine? engine = null)
    {
        _engine = engine ?? new FMSuperScoutMemoryEngine();
    }

    /// <inheritdoc />
    public string Name => $"native-fmreader/{_engine.Version}";

    /// <summary>引擎累积的诊断。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <inheritdoc />
    public async Task<ProbeResult> ProbeAsync(ReaderState state, CancellationToken cancellationToken)
    {
        ScannerAdapter.EnsureProbeAllowed(state);
        var probe = await _engine.ProbeAsync(cancellationToken).ConfigureAwait(false);
        _diagnostics.AddRange(probe.Status.Diagnostics);
        return new ProbeResult(
            Passed: probe.Passed,
            ExitCode: probe.Passed ? 0 : 3,
            DurationMs: probe.DurationMs,
            Output: string.Join("\n", probe.Status.Diagnostics),
            FailureReason: probe.Reason);
    }

    /// <inheritdoc />
    public async Task<ScanResult> ScanAsync(
        ScanRequest request,
        ReaderState state,
        GameInfo? game,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ScannerAdapter.EnsureScanAllowed(state);

        var startedAt = DateTimeOffset.UtcNow;
        var attemptId = Guid.NewGuid().ToString("D");
        var scan = await _engine.ScanAsync(cancellationToken).ConfigureAwait(false);
        var finishedAt = DateTimeOffset.UtcNow;

        if (scan.PayloadJson is null)
        {
            return new ScanResult(
                State: ReaderState.ProbeFailed,
                ScanId: attemptId,
                StartedAt: startedAt,
                FinishedAt: finishedAt,
                ExitCode: 3,
                OutputFile: null,
                StdoutFile: null,
                StderrFile: null,
                PlayersCount: 0,
                TransfersCount: 0,
                Warnings: new List<string>(scan.Warnings),
                FailureReason: scan.FailureReason ?? "内置引擎未返回协议报文。");
        }

        string outputDirectory;
        try
        {
            outputDirectory = Path.GetFullPath(request.OutputDirectory);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            throw new ScannerConfigurationException($"输出目录非法（{request.OutputDirectory}）：{ex.Message}");
        }

        Directory.CreateDirectory(outputDirectory);

        ScanPayload payload;
        try
        {
            payload = ScanPayloadParser.Parse(scan.PayloadJson);
        }
        catch (ScanOutputException ex)
        {
            return new ScanResult(
                State: ReaderState.ProbeFailed,
                ScanId: attemptId,
                StartedAt: startedAt,
                FinishedAt: finishedAt,
                ExitCode: 3,
                OutputFile: null,
                StdoutFile: null,
                StderrFile: null,
                PlayersCount: 0,
                TransfersCount: 0,
                Warnings: new List<string>(scan.Warnings),
                FailureReason: $"内置引擎输出未通过协议校验：{ex.Message}");
        }

        var build = ScanEnvelopeBuilder.Build(payload, game, ReaderInfo.Version, attemptId, DateTimeOffset.UtcNow);
        var meta = new ScanMeta(
            SchemaVersion: 1,
            ScanId: build.Envelope.Scan.ScanId,
            AttemptId: attemptId,
            ExitCode: 0,
            DurationMs: (long)(finishedAt - startedAt).TotalMilliseconds,
            StartedAt: startedAt,
            FinishedAt: finishedAt,
            OutputFile: null,
            StdoutFile: null,
            StderrFile: null,
            PlayersCount: build.Envelope.Players.Count,
            TransfersCount: build.Envelope.Transfers.Count,
            Warnings: build.Envelope.Warnings,
            Diagnostics: _diagnostics.Concat(scan.Status.Diagnostics).Distinct(StringComparer.Ordinal).ToList(),
            ReaderVersion: ReaderInfo.Version);

        var written = await new ScanWriter(outputDirectory)
            .WriteAsync(build.Envelope, meta, cancellationToken)
            .ConfigureAwait(false);

        var warnings = new List<string>(build.Envelope.Warnings);
        warnings.AddRange(_diagnostics);
        warnings.AddRange(scan.Warnings);

        return new ScanResult(
            State: ReaderState.ScanCompleted,
            ScanId: build.Envelope.Scan.ScanId,
            StartedAt: startedAt,
            FinishedAt: finishedAt,
            ExitCode: 0,
            OutputFile: written.EnvelopePath,
            StdoutFile: null,
            StderrFile: null,
            PlayersCount: build.Envelope.Players.Count,
            TransfersCount: build.Envelope.Transfers.Count,
            Warnings: warnings.Distinct(StringComparer.Ordinal).ToList(),
            FailureReason: null);
    }

    /// <inheritdoc />
    public void EnsureUsable()
    {
        // 内置引擎不需要外部路径；真正的可用性由 probe 的版本闸门与进程检查决定。
    }
}

/// <summary>选择扫描后端：默认内置引擎，显式配置了外部扫描器或指定 <c>--engine external</c> 时用外部扫描器。</summary>
public static class ScanBackendFactory
{
    /// <summary>内置引擎后端的名字。</summary>
    public const string Native = "native";

    /// <summary>外部扫描器后端的名字。</summary>
    public const string External = "external";

    /// <summary>创建后端。</summary>
    /// <param name="engine">命令行指定的引擎名；为空时自动选择。</param>
    /// <param name="scannerConfig">外部扫描器配置加载结果。</param>
    /// <param name="nativeEngine">内置引擎（测试可注入）。</param>
    /// <param name="externalAdapter">外部适配器（测试可注入）。</param>
    /// <returns>扫描后端与选择说明。</returns>
    public static (IScanBackend Backend, string Rationale) Create(
        string? engine,
        ScannerConfigLoad scannerConfig,
        IFmScanEngine? nativeEngine = null,
        ScannerAdapter? externalAdapter = null)
    {
        var requested = engine?.Trim().ToLowerInvariant();
        var hasExternalPath = !string.IsNullOrWhiteSpace(scannerConfig.Config.ScannerPath);

        if (requested == External)
        {
            return (new ExternalScanBackend(externalAdapter ?? new ScannerAdapter(scannerConfig.Config)),
                "按 --engine external 使用外部扫描器。");
        }

        if (requested == Native)
        {
            return (new NativeScanBackend(nativeEngine), "按 --engine native 使用内置只读引擎。");
        }

        if (hasExternalPath)
        {
            return (new ExternalScanBackend(externalAdapter ?? new ScannerAdapter(scannerConfig.Config)),
                "scanner.json 配置了扫描器路径，优先使用外部扫描器；加 --engine native 可强制内置引擎。");
        }

        return (new NativeScanBackend(nativeEngine),
            "未配置外部扫描器，使用内置只读引擎（不需要单独安装 FMSuperScout）。");
    }
}
