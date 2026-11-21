using System.Globalization;
using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Evidence;

/// <summary>可信度状态（SM-055）：异常不再一票否决，Rejected 需要系统性证据。</summary>
public enum FieldValidationStatus
{
    Pending,
    Candidate,
    Verified,
    Rejected,
}

/// <summary>一条异常证据，保留原始值、期望值、对象与观测时间。</summary>
public sealed record FieldAnomaly(
    string RawValue,
    string ExpectedGameValue,
    string ObservedAt,
    string ObjectId,
    bool Simulated);

/// <summary>字段级证据；confidence 只有校准值才填写，不把启发式分数当概率。</summary>
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
    int UniqueObservationCount = 0,
    int MatchCount = 0,
    int MissingSampleCount = 0,
    double ObservedMatchRate = 0,
    bool NeedsReview = false,
    string EvidenceClass = "none",
    IReadOnlyList<FieldAnomaly>? Anomalies = null);

/// <summary>一次观测；ObjectId 区分独立对象，ObservedAt 区分独立观测时间。</summary>
public sealed record FieldObservation(
    string FieldId,
    string? RawValue,
    string? ExpectedGameValue,
    string ObservedAt,
    string? ObjectId = null,
    bool Simulated = false);

/// <summary>字段级验证门槛覆盖值；0 表示使用 FieldSpec 自己的策略。</summary>
public sealed record FieldEvidenceOptions(
    double NumericTolerance = 0.0,
    int MinimumSamples = 0,
    int MinimumUniqueObjects = 0,
    int MinimumUniqueObservations = 0,
    double? CalibratedConfidence = null,
    double? AllowedMismatchRate = null);

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
            var strategy = spec?.Validation ?? DefaultStrategy(spec);
            var fieldSamples = samples.GetValueOrDefault(name) ?? new List<FieldObservation>();
            var valid = fieldSamples
                .Where(item => item.RawValue is not null && item.ExpectedGameValue is not null)
                .ToList();
            var missing = fieldSamples.Count - valid.Count;
            var comparison = strategy.ComparisonStrategy;
            var tolerance = options.NumericTolerance > 0 ? options.NumericTolerance : strategy.NumericTolerance;
            var anomalies = valid
                .Where(item => !Matches(comparison, item.RawValue!, item.ExpectedGameValue!, tolerance))
                .Select(item => new FieldAnomaly(
                    item.RawValue!, item.ExpectedGameValue!, item.ObservedAt,
                    item.ObjectId ?? item.ObservedAt, item.Simulated))
                .ToList();
            var sampleCount = valid.Count;
            var mismatch = anomalies.Count;
            var match = sampleCount - mismatch;
            var matchRate = sampleCount == 0 ? 0 : (double)match / sampleCount;
            var uniqueObjects = valid.Select(item => item.ObjectId ?? item.ObservedAt).Distinct(StringComparer.Ordinal).Count();
            var uniqueObservations = valid.Select(item => item.ObservedAt).Distinct(StringComparer.Ordinal).Count();
            var last = valid.LastOrDefault();
            var objectType = ObjectTypeOf(name, spec?.RelativeTo);
            var isRegistryVerified = verified.Contains(name);
            var isUpstream = upstream.Contains(name);
            var allowedRate = options.AllowedMismatchRate ?? strategy.AllowedMismatchRate;
            var minSamples = options.MinimumSamples > 0 ? options.MinimumSamples : strategy.MinimumSamples;
            var minObjects = options.MinimumUniqueObjects > 0 ? options.MinimumUniqueObjects : strategy.MinimumUniqueObjects;
            var minObservations = options.MinimumUniqueObservations > 0
                ? options.MinimumUniqueObservations
                : strategy.MinimumUniqueObservations;

            var systematic = anomalies
                .GroupBy(item => $"{item.RawValue}->{item.ExpectedGameValue}", StringComparer.Ordinal)
                .Any(group => group.Select(item => item.ObservedAt).Distinct(StringComparer.Ordinal).Count() >= 3);
            var rate = sampleCount == 0 ? 0 : (double)mismatch / sampleCount;

            FieldValidationStatus status;
            string notes;
            var needsReview = false;
            if (mismatch > 0 && (rate > allowedRate || systematic))
            {
                status = FieldValidationStatus.Rejected;
                notes = systematic
                    ? $"同一异常在至少 3 个独立观测重复出现，判定为系统性错误（{mismatch}/{sampleCount}）"
                    : $"异常比例 {rate:P1} 超过字段阈值 {allowedRate:P1}（{mismatch}/{sampleCount}）";
            }
            else if (sampleCount == 0)
            {
                status = isRegistryVerified || isUpstream ? FieldValidationStatus.Candidate : FieldValidationStatus.Pending;
                notes = missing > 0
                    ? $"{missing} 条观测缺少原始值或界面值，不计入样本"
                    : "没有原始值 + 界面期望值的配对样本，不能升级为 Verified";
            }
            else if (mismatch > 0)
            {
                status = FieldValidationStatus.Candidate;
                needsReview = true;
                notes = $"单次/少量异常（{mismatch}/{sampleCount}，允许 {allowedRate:P1}），保留异常证据，转人工复核";
            }
            else if (sampleCount < minSamples)
            {
                status = FieldValidationStatus.Candidate;
                notes = $"有效样本 {sampleCount} 少于门槛 {minSamples}，保持 Candidate";
            }
            else if (isRegistryVerified
                     && uniqueObjects >= minObjects
                     && uniqueObservations >= minObservations)
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

            var source = sampleCount > 0 || missing > 0
                ? "real-memory + game-ui sample"
                : isRegistryVerified
                    ? "verified_fields（历史界面核对，本轮没有重新采样）"
                    : isUpstream
                        ? "upstream_agreement_fields"
                        : "布局声明，无字段级证据";
            var evidenceClass = valid.Count == 0
                ? (missing > 0 ? "missing-only" : "none")
                : valid.All(item => item.Simulated) ? "simulated" : "real";
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
                UniqueObservationCount: uniqueObservations,
                MatchCount: match,
                MissingSampleCount: missing,
                ObservedMatchRate: matchRate,
                NeedsReview: needsReview,
                EvidenceClass: evidenceClass,
                Anomalies: anomalies));
        }

        return rows;
    }

    private static FieldValidationStrategy DefaultStrategy(FieldSpec? spec)
    {
        if (spec is not null)
        {
            return FieldValidationStrategies.For(spec);
        }

        return new("String", "player", "exact", 0, 2, 2, 1, 0.02, "empty", "空值不计数", "界面文本配对");
    }

    private static bool Matches(string comparison, string raw, string expected, double tolerance)
    {
        switch (comparison)
        {
            case "date":
                return TryDate(raw, out var rawDate)
                       && TryDate(expected, out var expectedDate)
                       && rawDate == expectedDate;
            case "numeric":
                return double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var rawNumber)
                       && double.TryParse(expected, NumberStyles.Float, CultureInfo.InvariantCulture, out var expectedNumber)
                       && Math.Abs(rawNumber - expectedNumber) <= tolerance;
            default:
                return string.Equals(raw.Trim(), expected.Trim(), StringComparison.Ordinal);
        }
    }

    private static bool TryDate(string value, out DateTime date)
    {
        if (DateTime.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal, out var parsed))
        {
            date = parsed.Date;
            return true;
        }

        date = default;
        return false;
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
