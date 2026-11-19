using System.Text.Json.Serialization;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>单项检查结果。</summary>
public enum CheckStatus
{
    /// <summary>通过。</summary>
    Passed,

    /// <summary>不通过。</summary>
    Failed,

    /// <summary>数据不足或结构无法判断（例如指针为空但上游允许为空）。</summary>
    Inconclusive,
}

/// <summary>一项具体检查。</summary>
/// <param name="Name">检查项，例如 <c>ca_range</c>。</param>
/// <param name="Status">结果。</param>
/// <param name="Detail">证据：实际值、阈值、样本量。</param>
public sealed record FieldCheck(string Name, CheckStatus Status, string Detail);

/// <summary>一个探测的整体结果。</summary>
public enum ProbeStatus
{
    /// <summary>全部检查通过。</summary>
    Passed,

    /// <summary>有检查失败。</summary>
    Failed,

    /// <summary>结构自洽但没有真实值锚定，或样本不足。</summary>
    Inconclusive,

    /// <summary>当前布局没有该能力（例如租借字段）。</summary>
    NotApplicable,
}

/// <summary>一个对象的探测结果。</summary>
/// <param name="Name">探测名，例如 <c>player</c>。</param>
/// <param name="Status">状态。</param>
/// <param name="Samples">参与检查的样本数。</param>
/// <param name="Checks">逐项检查。</param>
/// <param name="Note">说明。</param>
public sealed record ProbeOutcome(
    string Name,
    ProbeStatus Status,
    int Samples,
    IReadOnlyList<FieldCheck> Checks,
    string? Note = null)
{
    /// <summary>失败检查数。</summary>
    public int FailedChecks => Checks.Count(item => item.Status == CheckStatus.Failed);

    /// <summary>通过检查数。</summary>
    public int PassedChecks => Checks.Count(item => item.Status == CheckStatus.Passed);
}

/// <summary>诊断报告的整体状态。</summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum OverallStatus
{
    /// <summary>全部字段与探测都通过真实核对，允许扫描。</summary>
    Verified,

    /// <summary>结构探测通过但缺少真实值锚定，仍不允许扫描。</summary>
    Candidate,

    /// <summary>探测失败或存在被拒绝的字段，禁止扫描。</summary>
    Rejected,

    /// <summary>信息不足（游戏未运行、布局未登记、样本为空）。</summary>
    Unknown,
}

/// <summary>一次诊断的完整结果，可直接序列化成 JSON 报告。</summary>
/// <param name="GeneratedAt">生成时间（ISO-8601）。</param>
/// <param name="EngineVersion">引擎版本。</param>
/// <param name="GameBuild">Steam 构建号。</param>
/// <param name="PluginVersion">game_plugin.dll 版本。</param>
/// <param name="AppId">Steam AppId。</param>
/// <param name="LayoutName">布局名。</param>
/// <param name="LayoutStatus">布局整体状态。</param>
/// <param name="Probes">各对象探测结果。</param>
/// <param name="Fields">字段状态（来自布局与注册表）。</param>
/// <param name="Overall">整体状态。</param>
/// <param name="ScanAllowed">是否允许正式扫描。</param>
/// <param name="Summary">一句话结论。</param>
/// <param name="Diagnostics">诊断信息。</param>
/// <param name="Limitations">本次诊断的局限。</param>
public sealed record DiagnosticReport(
    string GeneratedAt,
    string EngineVersion,
    string? GameBuild,
    string? PluginVersion,
    string? AppId,
    string? LayoutName,
    FieldStatus LayoutStatus,
    IReadOnlyList<ProbeOutcome> Probes,
    IReadOnlyList<FieldVerification> Fields,
    OverallStatus Overall,
    bool ScanAllowed,
    string Summary,
    IReadOnlyList<string> Diagnostics,
    IReadOnlyList<string> Limitations)
{
    /// <summary>字段规格（含证据种类），与 <see cref="Fields"/> 互补：前者是"字段设计"，后者是"布局键状态"。</summary>
    public IReadOnlyList<FieldSpec> Specifications { get; init; } = Array.Empty<FieldSpec>();

    /// <summary>各证据种类的字段数。</summary>
    /// <returns>证据种类 → 数量。</returns>
    public IReadOnlyDictionary<EvidenceKind, int> EvidenceCounts() =>
        Specifications.GroupBy(item => item.Kind).ToDictionary(group => group.Key, group => group.Count());
}
