using System.Text.Json;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Versioning;

/// <summary>注册表中的一个构建条目。</summary>
/// <param name="Build">Steam 构建号。</param>
/// <param name="Layout">布局名。</param>
/// <param name="Status">构建的验证状态。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="VerifiedFields">已核对通过的字段。</param>
/// <param name="Evidence">验证证据。</param>
/// <param name="Note">说明。</param>
public sealed record BuildRegistration(
    string Build,
    string Layout,
    BuildStatus Status,
    string PluginVersion,
    IReadOnlyList<string> VerifiedFields,
    IReadOnlyList<string> Evidence,
    string Note);

/// <summary>
/// 兼容性注册表：构建 → 布局 + 已验证字段 + 证据。
///
/// 它是"能不能扫描"的唯一判决来源之一（另一个是运行期诊断报告）。注册表里没有的构建一律拒绝；
/// 注册了但状态不是 <see cref="BuildStatus.Verified"/> 的也拒绝。
/// </summary>
public sealed class CompatibilityRegistry
{
    private readonly Dictionary<string, BuildRegistration> _entries;

    /// <summary>使用嵌入的注册表。</summary>
    public CompatibilityRegistry()
        : this(LoadEmbedded())
    {
    }

    /// <summary>使用给定条目（测试注入）。</summary>
    /// <param name="entries">条目。</param>
    public CompatibilityRegistry(IEnumerable<BuildRegistration> entries)
    {
        _entries = entries.ToDictionary(item => item.Build, StringComparer.Ordinal);
    }

    /// <summary>全部条目。</summary>
    public IReadOnlyDictionary<string, BuildRegistration> Entries => _entries;

    /// <summary>查询条目。</summary>
    /// <param name="build">构建号。</param>
    /// <returns>条目；未注册时为 <c>null</c>。</returns>
    public BuildRegistration? For(string? build) =>
        build is not null && _entries.TryGetValue(build, out var entry) ? entry : null;

    /// <summary>把注册表里的字段状态应用到布局上（不改动 27.0 的字段值，只改状态记录）。</summary>
    /// <param name="build">构建号。</param>
    /// <param name="layout">布局。</param>
    public void Apply(string? build, ILayout layout)
    {
        ArgumentNullException.ThrowIfNull(layout);
        var entry = For(build);
        if (entry is null)
        {
            return;
        }

        foreach (var field in layout.Offsets.Keys)
        {
            if (entry.VerifiedFields.Contains(field, StringComparer.Ordinal))
            {
                if (layout is LayoutBase mutable)
                {
                    mutable.Mark(field, FieldStatus.Verified, EvidenceKind.GameUiAgreement, string.Join("; ", entry.Evidence), entry.Note);
                }
            }
        }
    }

    /// <summary>该构建是否允许扫描（只看注册表）。</summary>
    /// <param name="build">构建号。</param>
    /// <returns>允许时为 <c>true</c>。</returns>
    public bool AllowsScan(string? build) => For(build)?.Status == BuildStatus.Verified;

    /// <summary>读取嵌入的注册表。</summary>
    /// <returns>条目。</returns>
    public static IReadOnlyList<BuildRegistration> LoadEmbedded()
    {
        var assembly = typeof(CompatibilityRegistry).Assembly;
        var name = assembly.GetManifestResourceNames()
            .FirstOrDefault(item => item.EndsWith("compatibility-registry.json", StringComparison.Ordinal));
        if (name is null)
        {
            return Array.Empty<BuildRegistration>();
        }

        using var stream = assembly.GetManifestResourceStream(name);
        return stream is null ? Array.Empty<BuildRegistration>() : Parse(stream);
    }

    /// <summary>解析注册表 JSON（测试复用）。</summary>
    /// <param name="stream">JSON 流。</param>
    /// <returns>条目。</returns>
    public static IReadOnlyList<BuildRegistration> Parse(Stream stream)
    {
        using var document = JsonDocument.Parse(stream);
        if (!document.RootElement.TryGetProperty("builds", out var builds) || builds.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<BuildRegistration>();
        }

        var result = new List<BuildRegistration>();
        foreach (var item in builds.EnumerateArray())
        {
            var status = ReadString(item, "status") switch
            {
                "verified" => BuildStatus.Verified,
                "unsupported" => BuildStatus.Unsupported,
                _ => BuildStatus.Candidate,
            };
            result.Add(new BuildRegistration(
                Build: ReadString(item, "build") ?? string.Empty,
                Layout: ReadString(item, "layout") ?? string.Empty,
                Status: status,
                PluginVersion: ReadString(item, "plugin_version") ?? string.Empty,
                VerifiedFields: ReadArray(item, "verified_fields"),
                Evidence: ReadArray(item, "evidence"),
                Note: ReadString(item, "note") ?? string.Empty));
        }

        return result;
    }

    private static string? ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static IReadOnlyList<string> ReadArray(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<string>();
        }

        return value.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.String)
            .Select(item => item.GetString()!)
            .ToList();
    }
}
