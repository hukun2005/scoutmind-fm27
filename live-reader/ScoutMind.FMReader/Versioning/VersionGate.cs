using System.Reflection;
using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.FMReader.Versioning;

/// <summary>某个 FM 构建在 ScoutMind 里的验证状态。</summary>
public enum BuildStatus
{
    /// <summary>已在真实存档上逐项核对，允许扫描。</summary>
    Verified,

    /// <summary>结构上可能可用，但 ScoutMind 尚未核对，必须拒绝扫描（不猜）。</summary>
    Candidate,

    /// <summary>已知不兼容。</summary>
    Unsupported,
}

/// <summary>兼容清单中的一条记录。</summary>
/// <param name="Layout">内存布局名，例如 <c>FM27</c>。</param>
/// <param name="AppId">Steam AppId。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginVersion">game_plugin.dll 文件版本，例如 <c>27.1.0+2505117</c>。</param>
/// <param name="Status">验证状态。</param>
/// <param name="Note">说明，写入状态与扫描告警。</param>
/// <param name="Evidence">验证记录（文档路径或结论）。</param>
public sealed record BuildEntry(
    string Layout,
    string AppId,
    string Build,
    string PluginVersion,
    BuildStatus Status,
    string Note,
    IReadOnlyList<string> Evidence);

/// <summary>版本闸门的判定结果。</summary>
/// <param name="AllowScan">是否允许读取内存。</param>
/// <param name="Status">命中的状态；未命中为 <see cref="BuildStatus.Candidate"/>。</param>
/// <param name="Layout">命中的布局名；未命中为 <c>null</c>。</param>
/// <param name="Matched">命中的清单条目；未命中为 <c>null</c>。</param>
/// <param name="Message">给用户看的中文说明。</param>
public sealed record VersionGateResult(
    bool AllowScan,
    BuildStatus Status,
    string? Layout,
    BuildEntry? Matched,
    string Message)
{
    /// <summary>拒绝扫描的便捷构造。</summary>
    /// <param name="status">判定状态。</param>
    /// <param name="message">说明。</param>
    /// <param name="matched">命中的条目。</param>
    /// <returns>拒绝结果。</returns>
    public static VersionGateResult Refuse(BuildStatus status, string message, BuildEntry? matched = null) =>
        new(false, status, matched?.Layout, matched, message);
}

/// <summary>
/// 读取器兼容清单 + 内存布局闸门。
///
/// 规则（与产品规格一致）：只有 <see cref="BuildStatus.Verified"/> 允许读取；<c>candidate</c> 即使上游声称支持
/// 也一律拒绝，因为"上游按 27.0 钉的偏移"不等于"本机 27.1 可用"。未知构建同样拒绝。
/// </summary>
public sealed class VersionGate
{
    private readonly IReadOnlyList<BuildEntry> _entries;

    /// <summary>使用嵌入的兼容清单。</summary>
    public VersionGate()
        : this(LoadEmbedded())
    {
    }

    /// <summary>使用给定清单（测试可注入）。</summary>
    /// <param name="entries">清单条目。</param>
    public VersionGate(IReadOnlyList<BuildEntry> entries)
    {
        _entries = entries ?? throw new ArgumentNullException(nameof(entries));
    }

    /// <summary>当前清单。</summary>
    public IReadOnlyList<BuildEntry> Entries => _entries;

    /// <summary>判定一个构建是否允许扫描。</summary>
    /// <param name="appId">Steam AppId；未知时为 <c>null</c>。</param>
    /// <param name="build">构建号；未知时为 <c>null</c>。</param>
    /// <param name="pluginVersion">插件版本；未知时为 <c>null</c>。</param>
    /// <returns>判定结果。</returns>
    public VersionGateResult Evaluate(string? appId, string? build, string? pluginVersion)
    {
        if (string.IsNullOrWhiteSpace(build))
        {
            return VersionGateResult.Refuse(
                BuildStatus.Candidate,
                "没有读到游戏构建号，无法判断内存布局；拒绝扫描。请确认 FM27 已启动并加载存档。");
        }

        var byBuild = _entries.FirstOrDefault(entry => string.Equals(entry.Build, build, StringComparison.Ordinal));
        if (byBuild is null)
        {
            return VersionGateResult.Refuse(
                BuildStatus.Candidate,
                $"构建 {build} 不在 ScoutMind 的已验证清单里；拒绝扫描。新构建必须逐类核对偏移后才能加入清单。");
        }

        if (byBuild.Status == BuildStatus.Unsupported)
        {
            return VersionGateResult.Refuse(BuildStatus.Unsupported, byBuild.Note, byBuild);
        }

        if (byBuild.Status == BuildStatus.Candidate)
        {
            var detail = string.IsNullOrWhiteSpace(byBuild.Note) ? "尚未在真实存档上核对" : byBuild.Note;
            return VersionGateResult.Refuse(BuildStatus.Candidate, $"构建 {build} 未验证：{detail}", byBuild);
        }

        // 已验证条目：插件主次版本必须一致。FileVersion 常写成 "27.1"，清单可能写 "27.1.0+2505117"，
        // 因此比较主次版本；build 号仍是主键。
        if (!string.IsNullOrWhiteSpace(pluginVersion)
            && !string.IsNullOrWhiteSpace(byBuild.PluginVersion)
            && !SameMajorMinor(byBuild.PluginVersion, pluginVersion))
        {
            return VersionGateResult.Refuse(
                BuildStatus.Candidate,
                $"构建 {build} 已验证，但插件版本是 {pluginVersion}（清单记录 {byBuild.PluginVersion}）；拒绝扫描。",
                byBuild);
        }

        return new VersionGateResult(
            true,
            BuildStatus.Verified,
            byBuild.Layout,
            byBuild,
            $"构建 {build} · 插件 {pluginVersion ?? "未知"} · 布局 {byBuild.Layout}（已核对）");
    }

    /// <summary>比较两个插件版本的主次号，例如 <c>27.1.0+2505117</c> 与 <c>27.1</c> 视为一致。</summary>
    /// <param name="left">版本一。</param>
    /// <param name="right">版本二。</param>
    /// <returns>主次号相同时为 <c>true</c>。</returns>
    public static bool SameMajorMinor(string left, string right)
    {
        static (int Major, int Minor)? Parse(string value)
        {
            var text = value.Trim().Split('+', 2)[0];
            var parts = text.Split('.');
            if (parts.Length < 2
                || !int.TryParse(parts[0], out var major)
                || !int.TryParse(parts[1], out var minor))
            {
                return null;
            }

            return (major, minor);
        }

        var a = Parse(left);
        var b = Parse(right);
        return a is null || b is null ? string.Equals(left, right, StringComparison.OrdinalIgnoreCase) : a == b;
    }

    /// <summary>读取嵌入资源里的清单；缺失或损坏时返回空清单（所有构建都会被拒绝）。</summary>
    /// <returns>清单条目。</returns>
    public static IReadOnlyList<BuildEntry> LoadEmbedded()
    {
        var assembly = typeof(VersionGate).Assembly;
        var name = assembly.GetManifestResourceNames()
            .FirstOrDefault(item => item.EndsWith("verified-versions.json", StringComparison.Ordinal));
        if (name is null)
        {
            return Array.Empty<BuildEntry>();
        }

        using var stream = assembly.GetManifestResourceStream(name);
        if (stream is null)
        {
            return Array.Empty<BuildEntry>();
        }

        using var document = JsonDocument.Parse(stream);
        return Parse(document.RootElement);
    }

    /// <summary>解析清单 JSON（与嵌入资源同构，测试直接复用）。</summary>
    /// <param name="root">JSON 根元素。</param>
    /// <returns>清单条目。</returns>
    public static IReadOnlyList<BuildEntry> Parse(JsonElement root)
    {
        if (!root.TryGetProperty("layouts", out var layouts) || layouts.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<BuildEntry>();
        }

        var entries = new List<BuildEntry>();
        foreach (var item in layouts.EnumerateArray())
        {
            var status = ReadString(item, "status") switch
            {
                "verified" => BuildStatus.Verified,
                "unsupported" => BuildStatus.Unsupported,
                _ => BuildStatus.Candidate,
            };
            entries.Add(new BuildEntry(
                Layout: ReadString(item, "layout") ?? "unknown",
                AppId: ReadString(item, "app_id") ?? string.Empty,
                Build: ReadString(item, "build") ?? string.Empty,
                PluginVersion: ReadString(item, "plugin_version") ?? string.Empty,
                Status: status,
                Note: ReadString(item, "note") ?? string.Empty,
                Evidence: ReadStringArray(item, "evidence")));
        }

        return entries;
    }

    private static string? ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static IReadOnlyList<string> ReadStringArray(JsonElement element, string name)
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
