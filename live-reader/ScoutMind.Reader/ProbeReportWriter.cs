using System.Text.Json;
using ScoutMind.Contracts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.Reader;

/// <summary>
/// 把一次 probe 的结构化诊断写成 JSON 文件（`probe --report &lt;path&gt;`）。
///
/// 这里只做投影，不新增任何判断：UID 分类、哨兵样本与扫描就绪度全部来自引擎在真实内存上跑出的
/// <see cref="DiagnosticReport"/>；外部扫描器后端没有该报告时如实写 `available=false`。
/// </summary>
public static class ProbeReportWriter
{
    /// <summary>报告结构版本；字段变化时递增。</summary>
    public const string Schema = "scoutmind.probe.diagnostics.v1";

    /// <summary>把报告序列化为 JSON 文本。</summary>
    /// <param name="readerVersion">读取器版本。</param>
    /// <param name="probe">probe 结果。</param>
    /// <param name="report">引擎诊断报告；外部后端为 <c>null</c>。</param>
    /// <param name="now">生成时间。</param>
    /// <returns>JSON 文本。</returns>
    public static string Serialize(
        string readerVersion,
        ProbeResult probe,
        DiagnosticReport? report,
        DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(probe);
        var ids = report?.Probes.Select(item => item.ObjectIds).FirstOrDefault(item => item is not null);
        var document = new
        {
            schema = Schema,
            reader_version = readerVersion,
            generated_at = ScoutMindJson.FormatTimestamp(now),
            probe = new
            {
                passed = probe.Passed,
                exit_code = probe.ExitCode,
                duration_ms = probe.DurationMs,
                failure_reason = probe.FailureReason,
            },
            available = report is not null,
            scan_readiness = report?.ScanAllowed ?? probe.Passed,
            uid_diagnostics = report?.UidDiagnostics,
            sentinel_samples = ids?.SentinelSamples,
            sample_count = ids?.Samples.Count ?? 0,
            report,
        };
        return JsonSerializer.Serialize(document, ScoutMindJson.Options);
    }

    /// <summary>写出报告文件。</summary>
    /// <param name="path">目标路径；父目录会自动创建。</param>
    /// <param name="readerVersion">读取器版本。</param>
    /// <param name="probe">probe 结果。</param>
    /// <param name="report">引擎诊断报告。</param>
    /// <param name="now">生成时间。</param>
    /// <returns>写入的绝对路径。</returns>
    public static string Write(
        string path,
        string readerVersion,
        ProbeResult probe,
        DiagnosticReport? report,
        DateTimeOffset now)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var fullPath = Path.GetFullPath(path);
        var directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(fullPath, Serialize(readerVersion, probe, report, now));
        return fullPath;
    }
}
