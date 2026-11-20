using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>单个字段的可追溯元数据（SM-012）。</summary>
/// <param name="Name">布局字段名（例如 <c>PLAO_CA</c>）。</param>
/// <param name="Offset">偏移（十六进制字符串）。</param>
/// <param name="Type">数据类型（来自 FieldSpecs 的声明）。</param>
/// <param name="Status">可信度：Verified / Candidate / Pending。</param>
/// <param name="Evidence">证据来源说明。</param>
/// <param name="Versions">适用版本范围。</param>
/// <param name="VerificationMethod">验证方式（来自 FieldSpec）。</param>
public sealed record FieldMetadata(
    string Name,
    string Offset,
    string Type,
    string Status,
    string Evidence,
    string Versions,
    string VerificationMethod);

/// <summary>把布局、字段规格与兼容性注册表合并成"每个字段一行"的清单。</summary>
public static class FieldMetadataCatalog
{
    /// <summary>生成字段清单。</summary>
    /// <param name="layout">要导出的布局。</param>
    /// <param name="registry">字段证据来源；缺省读嵌入的注册表。</param>
    /// <param name="registeredBuild">注册表里的 Build；缺省取布局对应的已知构建。</param>
    /// <returns>按偏移排序的字段元数据。</returns>
    public static IReadOnlyList<FieldMetadata> Build(
        ILayout layout,
        CompatibilityRegistry? registry = null,
        string? registeredBuild = null)
    {
        ArgumentNullException.ThrowIfNull(layout);
        registry ??= new CompatibilityRegistry();
        var build = registeredBuild ?? DefaultBuild(layout);
        var registration = build is null ? null : registry.For(build);

        // FieldSpec 以布局键关联；同一个偏移键可能对应多个语义字段，这里保留第一条声明的类型。
        var specs = new Dictionary<string, FieldSpec>(StringComparer.Ordinal);
        foreach (var spec in FieldSpecs.Build(layout))
        {
            if (spec.LayoutKey is { Length: > 0 } key)
            {
                specs.TryAdd(key, spec);
            }
        }

        var verified = new HashSet<string>(registration?.VerifiedFields ?? Array.Empty<string>(), StringComparer.Ordinal);
        var candidate = new HashSet<string>(registration?.UpstreamFields ?? Array.Empty<string>(), StringComparer.Ordinal);

        var rows = new List<FieldMetadata>();
        foreach (var (name, offset) in layout.Offsets.OrderBy(item => item.Value).ThenBy(item => item.Key))
        {
            var spec = specs.GetValueOrDefault(name);
            var status = verified.Contains(name)
                ? "Verified"
                : candidate.Contains(name)
                    ? "Candidate"
                    : "Pending";

            var evidence = verified.Contains(name)
                ? "verified_fields（真实界面/扫描核对）"
                : candidate.Contains(name)
                    ? "upstream_agreement_fields（与上游一致，未单独核对）"
                    : "布局声明，无字段级证据";

            rows.Add(new FieldMetadata(
                Name: name,
                Offset: $"0x{offset:X}",
                Type: spec?.DataType ?? "未知",
                Status: status,
                Evidence: evidence,
                Versions: $"{layout.Name}（FM {layout.Major}.{layout.Minor}）",
                VerificationMethod: spec?.Method ?? "未声明"));
        }

        return rows;
    }

    /// <summary>布局对应的默认构建号（用于查注册表）。</summary>
    /// <param name="layout">布局。</param>
    /// <returns>构建号；未知返回 <c>null</c>。</returns>
    public static string? DefaultBuild(ILayout layout) =>
        layout.Name switch
        {
            "FM27_1" => "26620374",
            "FM27_0" => "26577676",
            _ => null,
        };
}
