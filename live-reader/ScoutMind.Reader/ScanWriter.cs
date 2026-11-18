using System.Globalization;
using System.Text;
using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 信封构建结果：信封本体，以及构建过程中新增的说明（例如缺少 <c>scan_id</c> 时的替代说明）。
/// </summary>
/// <param name="Envelope">可直接落盘的信封。</param>
/// <param name="Notes">需要写入 warnings 的补充说明。</param>
public sealed record EnvelopeBuild(ScanEnvelope Envelope, List<string> Notes);

/// <summary>
/// 把扫描器输出装配成 <see cref="ScanEnvelope"/>。装配规则是「有就用、没有就留空并记录说明」，
/// 任何字段都不会被伪造成看起来像真实扫描结果的值。
/// </summary>
public static class ScanEnvelopeBuilder
{
    /// <summary>装配信封。</summary>
    /// <param name="payload">已校验的扫描器输出。</param>
    /// <param name="game">本机检测到的游戏信息，用于补齐扫描器缺失的 version/build。</param>
    /// <param name="readerVersion">读取器版本。</param>
    /// <param name="fallbackScanId">扫描器未提供 scan_id 时使用的读取器 ID。</param>
    /// <param name="now">本次观测时间。</param>
    /// <returns>信封与补充说明。</returns>
    /// <exception cref="ScanOutputException">扫描器给出的 <c>observed_at</c> 不是 ISO-8601。</exception>
    public static EnvelopeBuild Build(
        ScanPayload payload,
        GameInfo? game,
        string readerVersion,
        string fallbackScanId,
        DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(payload);
        var notes = new List<string>();

        var scanId = payload.ScanId;
        if (string.IsNullOrWhiteSpace(scanId))
        {
            scanId = fallbackScanId;
            notes.Add($"扫描器未提供 scan.scan_id，已使用读取器生成的 ID {fallbackScanId}。");
        }

        var observedAt = payload.ObservedAt;
        if (string.IsNullOrWhiteSpace(observedAt))
        {
            observedAt = ScoutMindJson.FormatTimestamp(now);
            notes.Add("扫描器未提供 scan.observed_at，已使用读取器的观测时间。");
        }
        else if (!DateTimeOffset.TryParse(observedAt, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out _))
        {
            throw new ScanOutputException($"scan.observed_at 不是 ISO-8601 时间（{observedAt}），拒绝伪造观测时间。");
        }

        var build = payload.Game.Build;
        if (build is null && game?.BuildId is not null)
        {
            build = game.BuildId;
            notes.Add($"扫描器未提供 game.build，已使用本机检测到的构建号 {game.BuildId}。");
        }

        if (payload.Source is not null
            && !string.Equals(payload.Source, ReaderInfo.Source, StringComparison.Ordinal))
        {
            notes.Add($"扫描器声明的 source 为 {payload.Source}，读取器统一标记为 {ReaderInfo.Source}。");
        }

        var warnings = new List<string>(payload.Warnings);
        warnings.AddRange(notes);

        var envelope = new ScanEnvelope(
            SchemaVersion: ReaderInfo.SchemaVersion,
            Source: ReaderInfo.Source,
            ReaderVersion: readerVersion,
            Game: new ScanGame(
                Version: payload.Game.Version ?? game?.GameVersion,
                Build: build,
                AppId: payload.Game.AppId ?? game?.AppId ?? SteamLocator.Fm27AppId),
            Scan: new ScanMetadata(
                ScanId: scanId,
                ObservedAt: observedAt,
                GameDate: payload.GameDate,
                UserClubUid: payload.UserClubUid),
            Coverage: payload.Coverage,
            Warnings: warnings,
            Clubs: payload.Clubs,
            Players: payload.Players,
            Transfers: payload.Transfers);

        return new EnvelopeBuild(envelope, notes);
    }
}

/// <summary>
/// 扫描产物的元信息边车，记录退出码、耗时与诊断，便于事后排错而不必解析大文件。
/// </summary>
/// <param name="SchemaVersion">边车结构版本，当前为 1。</param>
/// <param name="ScanId">信封中的扫描 ID（后端幂等键）。</param>
/// <param name="AttemptId">本次读取器尝试的 ID，也是产物文件名的来源。</param>
/// <param name="ExitCode">扫描器退出码；未能启动时为 <c>null</c>。</param>
/// <param name="DurationMs">扫描耗时（毫秒）。</param>
/// <param name="StartedAt">开始时间（UTC）。</param>
/// <param name="FinishedAt">结束时间（UTC）。</param>
/// <param name="OutputFile">信封 JSON 路径。</param>
/// <param name="StdoutFile">stdout 捕获文件路径。</param>
/// <param name="StderrFile">stderr 捕获文件路径。</param>
/// <param name="PlayersCount">球员记录数。</param>
/// <param name="TransfersCount">转会记录数。</param>
/// <param name="Warnings">告警集合。</param>
/// <param name="Diagnostics">诊断集合（检测阶段 + 扫描阶段）。</param>
/// <param name="ReaderVersion">读取器版本。</param>
public sealed record ScanMeta(
    int SchemaVersion,
    string ScanId,
    string AttemptId,
    int? ExitCode,
    long DurationMs,
    DateTimeOffset StartedAt,
    DateTimeOffset FinishedAt,
    string? OutputFile,
    string? StdoutFile,
    string? StderrFile,
    int PlayersCount,
    int TransfersCount,
    List<string> Warnings,
    List<string> Diagnostics,
    string ReaderVersion);

/// <summary>
/// 本次写出的文件路径。
/// </summary>
/// <param name="EnvelopePath">信封 JSON 路径。</param>
/// <param name="MetaPath">边车 JSON 路径。</param>
public sealed record ScanWritten(string EnvelopePath, string MetaPath);

/// <summary>
/// 把信封与边车写入输出目录。文件名中的扫描 ID 会被安全化，避免外部进程提供的 ID 影响路径。
/// </summary>
public sealed class ScanWriter
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private readonly string _outputDirectory;

    /// <summary>创建写入器。</summary>
    /// <param name="outputDirectory">输出目录；不存在时在写入前创建。</param>
    public ScanWriter(string outputDirectory)
    {
        if (string.IsNullOrWhiteSpace(outputDirectory))
        {
            throw new ArgumentException("输出目录不能为空。", nameof(outputDirectory));
        }

        _outputDirectory = Path.GetFullPath(outputDirectory);
    }

    /// <summary>写入信封与边车。</summary>
    /// <param name="envelope">信封。</param>
    /// <param name="meta">边车内容；<see cref="ScanMeta.OutputFile"/> 会被覆盖为实际路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>写出的两个文件路径。</returns>
    public async Task<ScanWritten> WriteAsync(ScanEnvelope envelope, ScanMeta meta, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(envelope);
        ArgumentNullException.ThrowIfNull(meta);

        Directory.CreateDirectory(_outputDirectory);
        var stem = SafeFileStem(envelope.Scan.ScanId);
        var envelopePath = Path.Combine(_outputDirectory, $"scan-{stem}.json");
        var metaPath = Path.Combine(_outputDirectory, $"scan-{stem}.meta.json");

        var envelopeJson = JsonSerializer.Serialize(envelope, ScoutMindJson.Options);
        await File.WriteAllTextAsync(envelopePath, envelopeJson, Utf8NoBom, cancellationToken).ConfigureAwait(false);

        var metaJson = JsonSerializer.Serialize(meta with { OutputFile = envelopePath }, ScoutMindJson.Options);
        await File.WriteAllTextAsync(metaPath, metaJson, Utf8NoBom, cancellationToken).ConfigureAwait(false);

        return new ScanWritten(envelopePath, metaPath);
    }

    /// <summary>把外部提供的标识安全化为文件名片段。</summary>
    /// <param name="value">原始标识。</param>
    /// <returns>只含安全字符、长度受限的片段。</returns>
    public static string SafeFileStem(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return "unknown";
        }

        var builder = new StringBuilder(value.Length);
        foreach (var character in value)
        {
            builder.Append(char.IsLetterOrDigit(character) || character is '-' or '_' ? character : '-');
        }

        var stem = builder.ToString().Trim('-');
        if (stem.Length == 0)
        {
            return "unknown";
        }

        return stem.Length <= 64 ? stem : stem[..64];
    }
}
