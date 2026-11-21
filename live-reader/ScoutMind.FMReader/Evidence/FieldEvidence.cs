using System.Globalization;
using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Evidence;

/// <summary>可信度状态（SM-042/SM-052）：只有达到字段级门槛才允许 Verified。</summary>
public enum FieldValidationStatus
{
    Pending,
    Candidate,
    Verified,
    Rejected,
}

/// <summary>字段级证据；confidence 只在有校准数据时填写，不把启发式分数当概率。</summary>
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
    double? Confidence,
    string ValidationNotes,
    string ComparisonKind = "exact",
    int UniqueObjectCount = 0,
    int UniqueObservationCount = 0);

/// <summary>一次观测；ObjectId 用于区分独立对象，ObservedAt 用于区分独立观测时间。</summary>
public sealed record FieldObservation(
    string FieldId,
    string? RawValue,
    string? ExpectedGameValue,
    string ObservedAt,
    string? ObjectId = null);

/// <summary>字段级验证门槛与比较规则（SM-052）。</summary>
/// <param name="NumericTolerance">数值字段允许的绝对误差；默认 0。</param>
/// <param name="MinimumSamples">至少多少个有效配对样本。</param>
/// <param name="MinimumUniqueObjects">至少多少个独立对象。</param>
/// <param name="MinimumUniqueObservations">至少多少个独立观测时间。</param>
/// <param name="CalibratedConfidence">只有在有校准研究时填写；否则保持 null。</param>
public sealed record FieldEvidenceOptions(
    double NumericTolerance = 0.0,
    int MinimumSamples = 1,
    int MinimumUniqueObjects = 1,
    int MinimumUniqueObservations = 1,
    double? CalibratedConfidence = null);

/// <summary>把布局、字段规格、注册表与样本合并成结构化证据。</summary>
public static class FieldEvidenceCatalog
{
    /// <summary>生成 50 个字段的证据记录；缺少样本时绝不升级为 Verified。</summary>
    public static IReadOnlyList<FieldEvidence> Build(
        ILayout layout,
        CompatibilityRegistry? registry = null,
        IReadOnlyList<FieldObservation>? observations = null,
        string? registeredBuild = null,
        FieldEvidenceOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(layout);
        registry ??= new CompatibilityRegistry();
        options ??= new FieldEvidenceOptions();
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
            var comparison = ComparisonFor(name, spec?.DataType);
            var mismatch = valid.Count(item => !Matches(comparison, item.RawValue!, item.ExpectedGameValue!, options.NumericTolerance));
            var sampleCount = valid.Count;
            var uniqueObjects = valid.Select(item => item.ObjectId ?? item.ObservedAt).Distinct(StringComparer.Ordinal).Count();
            var uniqueObservations = valid.Select(item => item.ObservedAt).Distinct(StringComparer.Ordinal).Count();
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
                status = isRegistryVerified || isUpstream ? FieldValidationStatus.Candidate : FieldValidationStatus.Pending;
                notes = "没有原始值 + 界面期望值的配对样本，不能升级为 Verified";
            }
            else if (sampleCount < options.MinimumSamples)
            {
                status = FieldValidationStatus.Candidate;
                notes = $"有效样本 {sampleCount} 少于门槛 {options.MinimumSamples}，保持 Candidate";
            }
            else if (isRegistryVerified
                     && uniqueObjects >= options.MinimumUniqueObjects
                     && uniqueObservations >= options.MinimumUniqueObservations)
            {
                status = FieldValidationStatus.Verified;
                notes = $"{sampleCount} 个样本一致，{uniqueObjects} 个独立对象、{uniqueObservations} 个观测时间达到门槛";
            }
            else if (isRegistryVerified)
            {
                status = FieldValidationStatus.Candidate;
                notes = "样本一致但独立对象/观测时间不足，保持 Candidate";
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
            var confidence = status == FieldValidationStatus.Verified ? options.CalibratedConfidence : null;

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
                ValidationNotes: notes + "；confidence 未校准（null），不是概率",
                ComparisonKind: comparison,
                UniqueObjectCount: uniqueObjects,
                UniqueObservationCount: uniqueObservations));
        }

        return rows;
    }

    private static string ComparisonFor(string name, string? dataType)
    {
        var type = dataType ?? "";
        if (type.Contains("date", StringComparison.OrdinalIgnoreCase))
        {
            return "date";
        }
        if (numericTypes.Any(token => type.Contains(token, StringComparison.OrdinalIgnoreCase)))
        {
            return "numeric";
        }
        return "exact";
    }

    private static readonly string[] numericTypes = { "u8", "u16", "u32", "int", "float", "double", "number" };

    private static bool Matches(string comparison, string raw, string expected, double tolerance)
    {
        switch (comparison)
        {
            case "date":
                return DateTime.TryParse(raw, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal, out var rawDate)
                       && DateTime.TryParse(expected, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal, out var expectedDate)
                       && rawDate.Date == expectedDate.Date;
            case "numeric":
                return double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var rawNumber)
                       && double.TryParse(expected, NumberStyles.Float, CultureInfo.InvariantCulture, out var expectedNumber)
                       && Math.Abs(rawNumber - expectedNumber) <= tolerance;
            default:
                return string.Equals(raw.Trim(), expected.Trim(), StringComparison.Ordinal);
        }
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
