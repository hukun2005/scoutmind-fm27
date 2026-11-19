using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>诊断报告的整体状态计算与组装。</summary>
public static class ReportBuilder
{
    /// <summary>
    /// 计算整体状态。规则（从严）：
    /// 有字段被 Rejected 或探测 Failed → <c>Rejected</c>；
    /// 否则若所有必填字段 Verified 且所有适用探测 Passed → <c>Verified</c>；
    /// 否则若有任何结构证据 → <c>Candidate</c>；否则 <c>Unknown</c>。
    /// </summary>
    /// <param name="layout">布局。</param>
    /// <param name="probes">探测结果。</param>
    /// <returns>整体状态。</returns>
    public static OverallStatus Compute(ILayout layout, IReadOnlyList<ProbeOutcome> probes)
    {
        ArgumentNullException.ThrowIfNull(layout);
        ArgumentNullException.ThrowIfNull(probes);

        if (layout.Fields.Values.Any(field => field.Status == FieldStatus.Rejected)
            || probes.Any(probe => probe.Status == ProbeStatus.Failed))
        {
            return OverallStatus.Rejected;
        }

        var requiredVerified = layout.RequiredFields.All(field =>
            layout.Verification(field).Status == FieldStatus.Verified);
        var applicable = probes.Where(probe => probe.Status != ProbeStatus.NotApplicable).ToList();
        var probesPassed = applicable.Count > 0 && applicable.All(probe => probe.Status == ProbeStatus.Passed);

        if (requiredVerified && probesPassed)
        {
            return OverallStatus.Verified;
        }

        if (layout.Status is FieldStatus.Candidate or FieldStatus.Verified
            || probes.Any(probe => probe.Status is ProbeStatus.Passed or ProbeStatus.Inconclusive))
        {
            return OverallStatus.Candidate;
        }

        return OverallStatus.Unknown;
    }

    /// <summary>拼装报告。</summary>
    /// <param name="engineVersion">引擎版本。</param>
    /// <param name="build">构建号。</param>
    /// <param name="pluginVersion">插件版本。</param>
    /// <param name="appId">AppId。</param>
    /// <param name="layout">布局；未登记时为 <c>null</c>。</param>
    /// <param name="probes">探测结果。</param>
    /// <param name="diagnostics">诊断。</param>
    /// <param name="limitations">局限说明。</param>
    /// <returns>报告。</returns>
    public static DiagnosticReport Build(
        string engineVersion,
        string? build,
        string? pluginVersion,
        string? appId,
        ILayout? layout,
        IReadOnlyList<ProbeOutcome> probes,
        IReadOnlyList<string> diagnostics,
        IReadOnlyList<string> limitations)
    {
        var overall = layout is null
            ? OverallStatus.Unknown
            : Compute(layout, probes);

        var scanAllowed = layout is not null
            && overall == OverallStatus.Verified
            && layout.RequiredFields.All(field => layout.Verification(field).Status == FieldStatus.Verified);

        var summary = overall switch
        {
            OverallStatus.Verified => "布局已在真实存档上核对：允许正式扫描。",
            OverallStatus.Candidate => "结构探测通过但缺少真实值锚定：仍然禁止正式扫描。",
            OverallStatus.Rejected => "探测失败或字段被拒绝：布局不匹配，禁止扫描。",
            _ => layout is null
                ? "构建未登记或游戏未运行：无法判断布局，禁止扫描。"
                : "证据不足：禁止扫描。",
        };

        return new DiagnosticReport(
            GeneratedAt: DateTimeOffset.UtcNow.ToString("O"),
            EngineVersion: engineVersion,
            GameBuild: build,
            PluginVersion: pluginVersion,
            AppId: appId,
            LayoutName: layout?.Name,
            LayoutStatus: layout?.Status ?? FieldStatus.Unknown,
            Probes: probes,
            Fields: layout is null
                ? Array.Empty<FieldVerification>()
                : layout.Fields.Values.OrderBy(field => field.Field, StringComparer.Ordinal).ToList(),
            Overall: overall,
            ScanAllowed: scanAllowed,
            Summary: summary,
            Diagnostics: diagnostics,
            Limitations: limitations);
    }
}
