using System.Text.Json;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Versioning;

/// <summary>配置文件之间的一条冲突。</summary>
/// <param name="Code">稳定的冲突代码。</param>
/// <param name="Message">中文说明。</param>
public sealed record ConfigIssue(string Code, string Message);

/// <summary>
/// 统一校验三份兼容性配置：
///
/// * <c>Versioning/verified-versions.json</c>（引擎闸门：哪些构建允许读内存）
/// * <c>Versioning/compatibility-registry.json</c>（字段级证据：哪些字段 Verified/Candidate）
/// * <c>LayoutResolver</c>（构建号 → 具体布局）
///
/// 三者必须一致：同一个构建不能在两份文件里给不同的布局/插件版本，布局 ID 必须能被解析器解析，
/// AppId 必须是 FM27。任何冲突都让扫描被拒绝——配置错误比布局错误更常见，也更危险。
/// </summary>
public sealed class CompatibilityConfig
{
    /// <summary>FM27 的 Steam AppId。</summary>
    public const string Fm27AppId = "4530370";

    private readonly LayoutResolver _resolver;
    private readonly IReadOnlyList<BuildEntry> _gateEntries;
    private readonly IReadOnlyList<BuildRegistration> _registrations;

    /// <summary>用默认的嵌入配置构建。</summary>
    public CompatibilityConfig()
        : this(
            VersionGate.LoadEmbedded(),
            CompatibilityRegistry.LoadEmbedded(),
            new LayoutResolver())
    {
    }

    /// <summary>用给定条目构建（测试注入）。</summary>
    /// <param name="gateEntries">闸门条目。</param>
    /// <param name="registrations">注册表条目。</param>
    /// <param name="resolver">布局解析器。</param>
    public CompatibilityConfig(
        IReadOnlyList<BuildEntry> gateEntries,
        IReadOnlyList<BuildRegistration> registrations,
        LayoutResolver? resolver = null)
    {
        _gateEntries = gateEntries;
        _registrations = registrations;
        _resolver = resolver ?? new LayoutResolver();
    }

    /// <summary>闸门条目。</summary>
    public IReadOnlyList<BuildEntry> GateEntries => _gateEntries;

    /// <summary>注册表条目。</summary>
    public IReadOnlyList<BuildRegistration> Registrations => _registrations;

    /// <summary>执行校验。空列表表示三份配置一致。</summary>
    /// <returns>冲突列表。</returns>
    public IReadOnlyList<ConfigIssue> Validate()
    {
        var issues = new List<ConfigIssue>();

        foreach (var group in _gateEntries.GroupBy(entry => entry.Build, StringComparer.Ordinal).Where(group => group.Count() > 1))
        {
            issues.Add(new ConfigIssue("duplicate_gate_build", $"verified-versions.json 里构建 {group.Key} 出现了 {group.Count()} 次。"));
        }

        foreach (var group in _registrations.GroupBy(entry => entry.Build, StringComparer.Ordinal).Where(group => group.Count() > 1))
        {
            issues.Add(new ConfigIssue("duplicate_registry_build", $"compatibility-registry.json 里构建 {group.Key} 出现了 {group.Count()} 次。"));
        }

        foreach (var entry in _gateEntries)
        {
            if (!string.Equals(entry.AppId, Fm27AppId, StringComparison.Ordinal))
            {
                issues.Add(new ConfigIssue("wrong_app_id", $"构建 {entry.Build} 的 app_id 是 {entry.AppId}，不是 FM27 的 {Fm27AppId}。"));
            }

            var resolved = _resolver.Resolve(entry.Build, entry.PluginVersion);
            if (resolved is null)
            {
                issues.Add(new ConfigIssue("unregistered_layout", $"构建 {entry.Build} 在 LayoutResolver 里没有布局。"));
                continue;
            }

            if (!string.IsNullOrWhiteSpace(entry.Layout) && !string.Equals(entry.Layout, resolved.Name, StringComparison.Ordinal))
            {
                issues.Add(new ConfigIssue("layout_id_mismatch",
                    $"构建 {entry.Build} 在 verified-versions.json 里写的是 {entry.Layout}，解析器给出的是 {resolved.Name}。"));
            }

            var registration = _registrations.FirstOrDefault(item => string.Equals(item.Build, entry.Build, StringComparison.Ordinal));
            if (registration is null)
            {
                issues.Add(new ConfigIssue("missing_registration", $"构建 {entry.Build} 在闸门里存在，但 compatibility-registry.json 没有登记。"));
                continue;
            }

            if (!string.Equals(registration.Layout, resolved.Name, StringComparison.Ordinal))
            {
                issues.Add(new ConfigIssue("layout_id_mismatch",
                    $"构建 {entry.Build} 在注册表里写的是 {registration.Layout}，解析器给出的是 {resolved.Name}。"));
            }

            if (!string.IsNullOrWhiteSpace(entry.PluginVersion)
                && !string.IsNullOrWhiteSpace(registration.PluginVersion)
                && !VersionGate.SameMajorMinor(entry.PluginVersion, registration.PluginVersion))
            {
                issues.Add(new ConfigIssue("plugin_version_mismatch",
                    $"构建 {entry.Build} 的插件版本在两份文件里不一致：{entry.PluginVersion} vs {registration.PluginVersion}。"));
            }

            // 已声明 verified 的构建，必须有已核对字段，否则等于"空验证"。
            if (entry.Status == BuildStatus.Verified && registration.VerifiedFields.Count == 0)
            {
                issues.Add(new ConfigIssue("verified_without_fields",
                    $"构建 {entry.Build} 标为 verified，但注册表里没有任何 verified_fields。"));
            }
        }

        foreach (var registration in _registrations)
        {
            if (_gateEntries.All(item => !string.Equals(item.Build, registration.Build, StringComparison.Ordinal)))
            {
                issues.Add(new ConfigIssue("registration_without_gate",
                    $"注册表里的构建 {registration.Build} 没有出现在 verified-versions.json（永远不会被放行）。"));
            }

            var layout = _resolver.Resolve(registration.Build, registration.PluginVersion);
            if (layout is null)
            {
                issues.Add(new ConfigIssue("unregistered_layout", $"注册表构建 {registration.Build} 在 LayoutResolver 里没有布局。"));
            }
            else if (!string.Equals(layout.Name, registration.Layout, StringComparison.Ordinal))
            {
                issues.Add(new ConfigIssue("layout_id_mismatch",
                    $"注册表构建 {registration.Build} 的布局 {registration.Layout} 与解析器 {layout.Name} 不一致。"));
            }
        }

        return issues;
    }

    /// <summary>从 JSON 文本解析闸门条目（测试用）。</summary>
    /// <param name="json">JSON 文本。</param>
    /// <returns>条目。</returns>
    public static IReadOnlyList<BuildEntry> ParseGate(string json) => VersionGate.ParseJson(json);

    /// <summary>从 JSON 文本解析注册表条目（测试用）。</summary>
    /// <param name="json">JSON 文本。</param>
    /// <returns>条目。</returns>
    public static IReadOnlyList<BuildRegistration> ParseRegistry(string json)
    {
        using var stream = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(json));
        return CompatibilityRegistry.Parse(stream);
    }

    /// <summary>把冲突列表写成人能读的几行。</summary>
    /// <param name="issues">冲突。</param>
    /// <returns>文本。</returns>
    public static string Describe(IReadOnlyList<ConfigIssue> issues) =>
        issues.Count == 0 ? "配置一致" : string.Join("；", issues.Select(issue => $"[{issue.Code}] {issue.Message}"));

    /// <summary>读取 JSON 的便捷方法（诊断工具用）。</summary>
    /// <param name="path">文件路径。</param>
    /// <returns>根节点。</returns>
    public static JsonDocument ReadDocument(string path) => JsonDocument.Parse(File.ReadAllText(path));
}
