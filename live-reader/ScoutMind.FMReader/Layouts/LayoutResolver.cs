namespace ScoutMind.FMReader.Layouts;

/// <summary>
/// 构建号 → 布局。解析顺序：显式注册表（本文件）→ 插件主次版本兜底 → 未知（返回 <c>null</c>）。
///
/// 关键规则：**构建号优先于版本号**。同一 FM 版本的不同 Steam 构建可能改变布局，因此只有登记过的构建
/// 才能拿到布局；未登记的构建一律 <c>null</c>，由调用方拒绝扫描。
/// </summary>
public sealed class LayoutResolver
{
    private static readonly Dictionary<string, Func<ILayout>> KnownBuilds = new(StringComparer.Ordinal)
    {
        // FM27 27.0：上游钉过的布局。ScoutMind 尚未在本机 27.0 上核对，因此状态是 Verified（上游证据）。
        ["26577676"] = static () => new FM27_0_Layout(),
        // 本机 Steam 构建：27.1，候选布局。
        ["26620374"] = static () => new FM27_1_Layout(),
    };

    private readonly Dictionary<string, ILayout> _cache = new(StringComparer.Ordinal);

    /// <summary>按构建号解析布局。</summary>
    /// <param name="build">Steam 构建号；未知时为 <c>null</c>。</param>
    /// <param name="pluginVersion">插件版本，仅用于诊断与兜底。</param>
    /// <returns>布局；无法确定时为 <c>null</c>。</returns>
    public ILayout? Resolve(string? build, string? pluginVersion = null)
    {
        if (string.IsNullOrWhiteSpace(build))
        {
            return null;
        }

        if (_cache.TryGetValue(build, out var cached))
        {
            return cached;
        }

        if (!KnownBuilds.TryGetValue(build, out var factory))
        {
            return null;
        }

        var layout = factory();
        _cache[build] = layout;
        return layout;
    }

    /// <summary>列出已知构建（诊断用）。</summary>
    /// <returns>构建号与该构建的布局名。</returns>
    public static IReadOnlyDictionary<string, string> KnownBuildMap() =>
        KnownBuilds.ToDictionary(item => item.Key, item => item.Value().Name, StringComparer.Ordinal);

    /// <summary>该构建是否已登记（不代表已通过验证）。</summary>
    /// <param name="build">构建号。</param>
    /// <returns>已登记时为 <c>true</c>。</returns>
    public static bool IsRegistered(string? build) =>
        !string.IsNullOrWhiteSpace(build) && KnownBuilds.ContainsKey(build);
}
