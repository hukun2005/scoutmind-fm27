using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Evidence;

/// <summary>可信度状态（SM-042）：只有真实界面/样本证据齐全才允许 Verified。</summary>
public enum FieldValidationStatus
{
    Pending,
    Candidate,
    Verified,
    Rejected,
}

/// <summary>一条字段级证据。</summary>
/// <param name="FieldId">稳定字段标识（布局键）。</param>
/// <param name="FieldName">可读字段名。</param>
/// <param name="ObjectType">所属对象：player / contract / club / team / block / person。</param>
/// <param name="MemoryOffset">内存偏移（十六进制）。</param>
/// <param name="DataType">数据类型。</param>
/// <param name="RawValue">最近一次原始值；没有样本时为 null。</param>
/// <param name="ExpectedGameValue">游戏界面期望值；没有核对时为 null。</param>
/// <param name="ObservedAt">观测时间。</param>
/// <param name="SampleCount">有效样本数（只计非缺失观测）。</param>
/// <param name="MismatchCount">与期望不一致的数量。</param>
/// <param name="ValidationStatus">可信度状态。</param>
/// <param name="EvidenceSource">证据来源。</param>
/// <param name="Confidence">0..1 置信度。</param>
/// <param name="ValidationNotes">说明与缺口。</param>
public sealed record FieldEvidence(
    string FieldId,
    string FieldName,
    string ObjectType,
    string MemoryOffset,
    string DataType,
    string? RawValue,
    string? ExpectedGameValue,
    string? ObservedAt,
    int SampleCount,
    int MismatchCount,
    FieldValidationStatus ValidationStatus,
    string EvidenceSource,
    double Confidence,
    string ValidationNotes);

/// <summary>一次观测：只有 raw 与 expected 同时存在且可比时才算有效样本。</summary>
/// <param name="FieldId">布局键。</param>
/// <param name="RawValue">内存读取值。</param>
/// <param name="ExpectedGameValue">界面核对值。</param>
/// <param name="ObservedAt">观测时间。</param>
public sealed record FieldObservation(
    string FieldId,
    string? RawValue,
    string? ExpectedGameValue,
    string ObservedAt);

/// <summary>把布局、字段规格、注册表与样本合并成结构化证据。</summary>
public static class FieldEvidenceCatalog
{
    /// <summary>生成 50 个字段的证据记录；缺少样本时绝不升级为 Verified。</summary>
    /// <param name="layout">布局。</param>
    /// <param name="registry">兼容性注册表。</param>
    /// <param name="observations">可选样本（真实读取 + 界面核对）。</param>
    /// <param name="registeredBuild">注册表构建号；缺省按布局推断。</param>
    public static IReadOnlyList<FieldEvidence> Build(
        ILayout layout,
        CompatibilityRegistry? registry = null,
        IReadOnlyList<FieldObservation>? observations = null,
        string? registeredBuild = null)
    {
        ArgumentNullException.ThrowIfNull(layout);
        registry ??= new CompatibilityRegistry();
        var build = registeredBuild ?? FieldMetadataCatalog.DefaultBuild(layout);
        var registration = build is null ? null : registry.For(build);
        var verified = new HashSet<string>(registration?.VerifiedFields ?? Array.Empty<string>(), StringComparer.Ordinal);
        var upstream = new HashSet<string>(registration?.UpstreamFields ?? Array.Empty<string>(), StringComparer.Ordinal);
        var specs = new Dictionary<string, FieldSpec>(StringComparer.Ordinal);
        foreach (var spec in FieldSpecs.Build(layout))
        {
            if (spec.LayoutKey is { Length: > 0 } key)
            {
                specs.TryAdd(key, spec);
            }
        }

        var samples = (observations ?? Array.Empty<FieldObservation>())
            .GroupBy(item => item.FieldId, StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.ToList(), StringComparer.Ordinal);

        var rows = new List<FieldEvidence>();
        foreach (var (name, offset) in layout.Offsets.OrderBy(item => item.Value).ThenBy(item => item.Key))
        {
            var spec = specs.GetValueOrDefault(name);
            var fieldSamples = samples.GetValueOrDefault(name) ?? new List<FieldObservation>();
            var valid = fieldSamples
                .Where(item => item.RawValue is not null && item.ExpectedGameValue is not null)
                .ToList();
            var mismatch = valid.Count(item => !string.Equals(item.RawValue, item.ExpectedGameValue, StringComparison.Ordinal));
            var sampleCount = valid.Count;
            var last = valid.LastOrDefault();
            var objectType = ObjectTypeOf(name, spec?.RelativeTo);
            var isRegistryVerified = verified.Contains(name);
            var isUpstream = upstream.Contains(name);

            FieldValidationStatus status;
            string notes;
            if (mismatch > 0)
            {
                status = FieldValidationStatus.Rejected;
                notes = $"{mismatch}/{sampleCount} 个样本与界面不一致，字段被拒绝";
            }
            else if (sampleCount == 0)
            {
                // 没有真实样本时最高只能是 Candidate；注册表 verified 也不能凭空升级。
                status = isRegistryVerified || isUpstream ? FieldValidationStatus.Candidate : FieldValidationStatus.Pending;
                notes = "没有原始值 + 界面期望值的配对样本，不能升级为 Verified";
            }
            else if (isRegistryVerified && sampleCount >= 1)
            {
                status = FieldValidationStatus.Verified;
                notes = $"{sampleCount} 个样本全部与界面一致";
            }
            else if (isUpstream)
            {
                status = FieldValidationStatus.Candidate;
                notes = "有样本一致，但字段只在导出层核对过，缺少独立界面证据";
            }
            else
            {
                status = FieldValidationStatus.Candidate;
                notes = "有样本一致，但字段没有注册表证据，保持 Candidate";
            }

            var source = sampleCount > 0
                ? "real-memory + game-ui sample"
                : isRegistryVerified
                    ? "verified_fields（历史界面核对，本轮没有重新采样）"
                    : isUpstream
                        ? "upstream_agreement_fields"
                        : "布局声明，无字段级证据";
            var confidence = status switch
            {
                FieldValidationStatus.Verified => Math.Min(1.0, 0.6 + 0.1 * sampleCount),
                FieldValidationStatus.Candidate when sampleCount > 0 => 0.5,
                FieldValidationStatus.Candidate => 0.3,
                FieldValidationStatus.Rejected => 0.0,
                _ => 0.15,
            };

            rows.Add(new FieldEvidence(
                FieldId: name,
                FieldName: name,
                ObjectType: objectType,
                MemoryOffset: $"0x{offset:X}",
                DataType: spec?.DataType ?? "未知",
                RawValue: last?.RawValue,
                ExpectedGameValue: last?.ExpectedGameValue,
                ObservedAt: last?.ObservedAt,
                SampleCount: sampleCount,
                MismatchCount: mismatch,
                ValidationStatus: status,
                EvidenceSource: source,
                Confidence: confidence,
                ValidationNotes: notes));
        }

        return rows;
    }

    private static string ObjectTypeOf(string name, string? relativeTo)
    {
        if (!string.IsNullOrEmpty(relativeTo))
        {
            return relativeTo switch
            {
                "person" => "person",
                "block" => "player",
                "contract" => "contract",
                "club" => "club",
                "team" => "team",
                "db" => "database",
                _ => relativeTo!,
            };
        }

        if (name.StartsWith("CON_", StringComparison.Ordinal)) return "contract";
        if (name.StartsWith("PERO_", StringComparison.Ordinal)) return "person";
        if (name.StartsWith("CLUB_", StringComparison.Ordinal)) return "club";
        if (name.StartsWith("TEAM_", StringComparison.Ordinal)) return "team";
        return "player";
    }
}
