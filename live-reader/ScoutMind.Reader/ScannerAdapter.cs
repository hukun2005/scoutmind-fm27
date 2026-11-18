using System.Globalization;
using System.Text;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 外部扫描器配置缺失或不合法。属于使用/配置错误，命令行以退出码 64 结束。
/// </summary>
public sealed class ScannerConfigurationException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="message">中文错误说明。</param>
    public ScannerConfigurationException(string message)
        : base(message)
    {
    }
}

/// <summary>
/// 当前状态不允许执行该动作。读取器在状态未到 <see cref="ReaderState.Compatible"/>（probe）
/// 或 <see cref="ReaderState.ProbePassed"/>（scan）时必须拒绝启动外部进程。
/// </summary>
public sealed class ScanRefusedException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="message">中文错误说明。</param>
    public ScanRefusedException(string message)
        : base(message)
    {
    }
}

/// <summary>
/// 外部扫描器适配器：校验配置与状态，用 <see cref="System.Diagnostics.Process"/> 启动外部可执行文件，
/// 捕获 stdout/stderr 到文件，超时终止整棵进程树，并校验扫描输出是否符合协议。
/// 它从不注入、不读写游戏进程。
/// </summary>
public sealed class ScannerAdapter
{
    /// <summary>probe 输出保留到 <see cref="ProbeResult.Output"/> 的最大字节数。</summary>
    public const int MaxProbeOutputBytes = 8192;

    private readonly ScannerConfig _config;
    private readonly IProcessRunner _runner;
    private readonly List<string> _diagnostics = new();

    /// <summary>创建适配器。</summary>
    /// <param name="config">扫描器配置。</param>
    /// <param name="processRunner">进程执行器，测试可注入替身；默认使用 <see cref="SystemProcessRunner"/>。</param>
    public ScannerAdapter(ScannerConfig config, IProcessRunner? processRunner = null)
    {
        ArgumentNullException.ThrowIfNull(config);
        _config = config;
        _runner = processRunner ?? new SystemProcessRunner();

        var template = config.ScanArgumentsTemplate ?? string.Empty;
        if (!template.Contains("{output}", StringComparison.Ordinal))
        {
            _diagnostics.Add("扫描参数模板未包含 {output}；扫描器必须把扫描协议 JSON 写到 stdout。");
        }
    }

    /// <summary>适配器产生的诊断信息。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <summary>确认状态为 <see cref="ReaderState.Compatible"/>。</summary>
    /// <param name="state">当前状态。</param>
    /// <exception cref="ScanRefusedException">状态不允许执行 probe。</exception>
    public static void EnsureProbeAllowed(ReaderState state)
    {
        if (state != ReaderState.Compatible)
        {
            throw new ScanRefusedException(
                $"当前状态为 {state}，probe 只能在 {ReaderState.Compatible} 阶段执行。");
        }
    }

    /// <summary>确认状态为 <see cref="ReaderState.ProbePassed"/>。</summary>
    /// <param name="state">当前状态。</param>
    /// <exception cref="ScanRefusedException">状态不允许执行扫描。</exception>
    public static void EnsureScanAllowed(ReaderState state)
    {
        if (state != ReaderState.ProbePassed)
        {
            throw new ScanRefusedException(
                $"当前状态为 {state}，扫描只能在 {ReaderState.ProbePassed} 阶段执行。");
        }
    }

    /// <summary>解析并校验扫描器路径。</summary>
    /// <param name="overridePath">请求中的路径覆盖；为 <c>null</c> 时使用配置值。</param>
    /// <returns>扫描器可执行文件的绝对路径。</returns>
    /// <exception cref="ScannerConfigurationException">未配置、路径非法或文件不存在。</exception>
    public string EnsureScannerConfigured(string? overridePath = null)
    {
        var configured = string.IsNullOrWhiteSpace(overridePath) ? _config.ScannerPath : overridePath;
        if (string.IsNullOrWhiteSpace(configured))
        {
            throw new ScannerConfigurationException(
                "未配置外部扫描器路径（scannerPath）。请把 config/scanner.sample.json 复制为 scanner.json 并填写扫描器路径。");
        }

        string fullPath;
        try
        {
            fullPath = Path.GetFullPath(configured.Trim());
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            throw new ScannerConfigurationException($"扫描器路径非法（{configured}）：{ex.Message}");
        }

        if (!File.Exists(fullPath))
        {
            throw new ScannerConfigurationException($"外部扫描器不存在：{fullPath}");
        }

        return fullPath;
    }

    /// <summary>执行 probe：启动扫描器自检并检查退出码与输出。</summary>
    /// <param name="state">当前状态，必须是 <see cref="ReaderState.Compatible"/>。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>probe 结果；失败时 <see cref="ProbeResult.FailureReason"/> 说明原因。</returns>
    /// <exception cref="ScanRefusedException">状态不允许执行 probe。</exception>
    /// <exception cref="ScannerConfigurationException">扫描器未配置或不存在。</exception>
    public async Task<ProbeResult> ProbeAsync(ReaderState state, CancellationToken cancellationToken)
    {
        EnsureProbeAllowed(state);
        var scannerPath = EnsureScannerConfigured();
        var timeout = ResolveTimeout(0);
        var tempDirectory = Path.Combine(Path.GetTempPath(), "scoutmind", $"probe-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempDirectory);

        try
        {
            var stdoutPath = Path.Combine(tempDirectory, "probe.stdout.txt");
            var stderrPath = Path.Combine(tempDirectory, "probe.stderr.txt");
            var request = new ProcessRunRequest(
                scannerPath,
                _config.ProbeArguments ?? new List<string>(),
                Path.GetDirectoryName(scannerPath) ?? tempDirectory,
                stdoutPath,
                stderrPath,
                timeout);

            var run = await _runner.RunAsync(request, cancellationToken).ConfigureAwait(false);
            if (run.Note is not null)
            {
                _diagnostics.Add(run.Note);
            }

            if (run.StartError is not null)
            {
                return new ProbeResult(false, run.ExitCode, run.DurationMs, null, run.StartError);
            }

            var stdoutExcerpt = ReadExcerpt(stdoutPath);
            var stderrExcerpt = ReadExcerpt(stderrPath);
            var output = string.IsNullOrWhiteSpace(stdoutExcerpt) ? stderrExcerpt : stdoutExcerpt;

            if (run.TimedOut)
            {
                return new ProbeResult(
                    false,
                    run.ExitCode,
                    run.DurationMs,
                    output,
                    $"扫描器在 {timeout.TotalSeconds.ToString("0", CultureInfo.InvariantCulture)} 秒内未完成 probe，已终止进程树。");
            }

            if (run.ExitCode is not null && run.ExitCode != 0)
            {
                return new ProbeResult(
                    false,
                    run.ExitCode,
                    run.DurationMs,
                    output,
                    $"扫描器 probe 退出码 {run.ExitCode.Value.ToString(CultureInfo.InvariantCulture)}。{SummarizeStderr(stderrExcerpt)}");
            }

            return new ProbeResult(true, run.ExitCode, run.DurationMs, output, null);
        }
        finally
        {
            TryDeleteDirectory(tempDirectory);
        }
    }

    /// <summary>执行一次扫描并落盘。</summary>
    /// <param name="request">扫描请求（输出目录、超时、扫描器路径覆盖）。</param>
    /// <param name="state">当前状态，必须是 <see cref="ReaderState.ProbePassed"/>。</param>
    /// <param name="game">本机检测到的游戏信息，用于补齐信封中的 version/build。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果；失败时状态为 <see cref="ReaderState.ProbeFailed"/>。</returns>
    /// <exception cref="ScanRefusedException">状态不允许执行扫描。</exception>
    /// <exception cref="ScannerConfigurationException">扫描器或参数模板未配置。</exception>
    public async Task<ScanResult> ScanAsync(
        ScanRequest request,
        ReaderState state,
        GameInfo? game,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        EnsureScanAllowed(state);
        var scannerPath = EnsureScannerConfigured(request.ScannerPath);

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

        var startedAt = DateTimeOffset.UtcNow;
        var attemptId = Guid.NewGuid().ToString("D");
        var timeout = ResolveTimeout(request.TimeoutSeconds);
        var warnings = new List<string>();
        var stdoutPath = Path.Combine(outputDirectory, $"scan-{attemptId}.stdout.txt");
        var stderrPath = Path.Combine(outputDirectory, $"scan-{attemptId}.stderr.txt");
        var arguments = BuildScanArguments(outputDirectory, attemptId);

        var run = await _runner.RunAsync(
            new ProcessRunRequest(
                scannerPath,
                arguments,
                Path.GetDirectoryName(scannerPath) ?? outputDirectory,
                stdoutPath,
                stderrPath,
                timeout),
            cancellationToken).ConfigureAwait(false);

        if (run.Note is not null)
        {
            warnings.Add(run.Note);
        }

        ScanResult Fail(string reason) => new(
            State: ReaderState.ProbeFailed,
            ScanId: attemptId,
            StartedAt: startedAt,
            FinishedAt: DateTimeOffset.UtcNow,
            ExitCode: run.ExitCode,
            OutputFile: null,
            StdoutFile: stdoutPath,
            StderrFile: stderrPath,
            PlayersCount: 0,
            TransfersCount: 0,
            Warnings: new List<string>(warnings),
            FailureReason: reason);

        if (run.StartError is not null)
        {
            return Fail(run.StartError);
        }

        if (run.TimedOut)
        {
            return Fail(
                $"扫描器在 {timeout.TotalSeconds.ToString("0", CultureInfo.InvariantCulture)} 秒内未完成，已终止进程树。");
        }

        if (run.ExitCode is not null && run.ExitCode != 0)
        {
            return Fail(
                $"扫描器退出码 {run.ExitCode.Value.ToString(CultureInfo.InvariantCulture)}。{SummarizeStderr(ReadExcerpt(stderrPath))}");
        }

        string stdoutText;
        try
        {
            stdoutText = await File.ReadAllTextAsync(stdoutPath, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Fail($"读取扫描器输出失败：{ex.Message}");
        }

        ScanPayload payload;
        try
        {
            payload = ScanPayloadParser.Parse(stdoutText);
        }
        catch (ScanOutputException ex)
        {
            return Fail($"扫描器输出未通过协议校验：{ex.Message}");
        }

        EnvelopeBuild build;
        try
        {
            build = ScanEnvelopeBuilder.Build(payload, game, ReaderInfo.Version, attemptId, DateTimeOffset.UtcNow);
        }
        catch (ScanOutputException ex)
        {
            return Fail(ex.Message);
        }

        var finishedAt = DateTimeOffset.UtcNow;
        var meta = new ScanMeta(
            SchemaVersion: 1,
            ScanId: build.Envelope.Scan.ScanId,
            AttemptId: attemptId,
            ExitCode: run.ExitCode,
            DurationMs: run.DurationMs,
            StartedAt: startedAt,
            FinishedAt: finishedAt,
            OutputFile: null,
            StdoutFile: stdoutPath,
            StderrFile: stderrPath,
            PlayersCount: build.Envelope.Players.Count,
            TransfersCount: build.Envelope.Transfers.Count,
            Warnings: build.Envelope.Warnings,
            Diagnostics: new List<string>(_diagnostics),
            ReaderVersion: ReaderInfo.Version);

        ScanWritten written;
        try
        {
            written = await new ScanWriter(outputDirectory)
                .WriteAsync(build.Envelope, meta, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Fail($"写入扫描产物失败：{ex.Message}");
        }

        var allWarnings = new List<string>(build.Envelope.Warnings);
        allWarnings.AddRange(_diagnostics);

        return new ScanResult(
            State: ReaderState.ScanCompleted,
            ScanId: build.Envelope.Scan.ScanId,
            StartedAt: startedAt,
            FinishedAt: finishedAt,
            ExitCode: run.ExitCode,
            OutputFile: written.EnvelopePath,
            StdoutFile: stdoutPath,
            StderrFile: stderrPath,
            PlayersCount: build.Envelope.Players.Count,
            TransfersCount: build.Envelope.Transfers.Count,
            Warnings: allWarnings,
            FailureReason: null);
    }

    private List<string> BuildScanArguments(string outputDirectory, string attemptId)
    {
        var template = _config.ScanArgumentsTemplate;
        if (string.IsNullOrWhiteSpace(template))
        {
            throw new ScannerConfigurationException("扫描参数模板为空（scanArgumentsTemplate）。");
        }

        List<string> tokens;
        try
        {
            tokens = CommandLineSplitter.Split(template);
        }
        catch (FormatException ex)
        {
            throw new ScannerConfigurationException($"扫描参数模板非法：{ex.Message}");
        }

        var saveName = _config.SaveName ?? string.Empty;
        var arguments = new List<string>(tokens.Count);
        foreach (var token in tokens)
        {
            arguments.Add(token
                .Replace("{output}", outputDirectory, StringComparison.Ordinal)
                .Replace("{scanId}", attemptId, StringComparison.Ordinal)
                .Replace("{saveName}", saveName, StringComparison.Ordinal));
        }

        if (arguments.Count == 0)
        {
            throw new ScannerConfigurationException("扫描参数模板切分后为空。");
        }

        return arguments;
    }

    private TimeSpan ResolveTimeout(int requestSeconds)
    {
        var seconds = requestSeconds > 0 ? requestSeconds : _config.TimeoutSeconds;
        if (seconds <= 0)
        {
            seconds = 120;
        }

        return TimeSpan.FromSeconds(seconds);
    }

    private string? ReadExcerpt(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return null;
            }

            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            var buffer = new byte[MaxProbeOutputBytes];
            var read = stream.Read(buffer, 0, buffer.Length);
            return read == 0 ? null : Encoding.UTF8.GetString(buffer, 0, read);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _diagnostics.Add($"读取捕获文件失败（{path}）：{ex.Message}");
            return null;
        }
    }

    private static string SummarizeStderr(string? stderrExcerpt)
    {
        if (string.IsNullOrWhiteSpace(stderrExcerpt))
        {
            return "stderr 为空。";
        }

        var trimmed = stderrExcerpt.Trim();
        return $"stderr 摘要：{(trimmed.Length <= 800 ? trimmed : trimmed[..800])}";
    }

    private void TryDeleteDirectory(string directory)
    {
        try
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _diagnostics.Add($"清理临时目录失败（{directory}）：{ex.Message}");
        }
    }
}
