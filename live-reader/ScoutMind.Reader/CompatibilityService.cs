using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 兼容清单无法加载或结构不受支持。出现该异常时读取器必须拒绝读取，而不是继续猜测。
/// </summary>
public sealed class CompatibilityManifestException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="message">中文错误说明。</param>
    public CompatibilityManifestException(string message)
        : base(message)
    {
    }

    /// <summary>创建异常并保留内部原因。</summary>
    /// <param name="message">中文错误说明。</param>
    /// <param name="innerException">导致失败的原始异常。</param>
    public CompatibilityManifestException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>
/// 版本闸门的输入：本机实际观测到的三个值。任一缺失都不能判定为兼容。
/// </summary>
/// <param name="AppId">Steam AppId。</param>
/// <param name="BuildId">appmanifest 中的构建号。</param>
/// <param name="PluginProductVersion">game_plugin.dll 的产品版本。</param>
public sealed record CompatibilityInput(
    string? AppId,
    string? BuildId,
    string? PluginProductVersion);

/// <summary>
/// 严格版本闸门：只有当 AppId、构建号与插件产品版本同时命中清单中的 <c>verified</c> 条目时才允许读取。
/// 未知构建一律判为不受支持，绝不回退到旧版本的偏移量或兼容规则。
/// </summary>
public sealed class CompatibilityService
{
    /// <summary>本读取器支持的兼容清单结构版本。</summary>
    public const int SupportedSchemaVersion = 1;

    private readonly CompatibilityManifest _manifest;

    /// <summary>使用已加载的清单创建服务。</summary>
    /// <param name="manifest">兼容清单。</param>
    public CompatibilityService(CompatibilityManifest manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        _manifest = manifest;
    }

    /// <summary>已加载的兼容清单。</summary>
    public CompatibilityManifest Manifest => _manifest;

    /// <summary>从磁盘加载并校验兼容清单。</summary>
    /// <param name="manifestPath">清单文件路径。</param>
    /// <returns>校验通过的清单。</returns>
    /// <exception cref="CompatibilityManifestException">文件缺失、无法读取、JSON 非法或版本不受支持。</exception>
    public static CompatibilityManifest LoadManifest(string manifestPath)
    {
        if (string.IsNullOrWhiteSpace(manifestPath))
        {
            throw new CompatibilityManifestException("兼容清单路径为空。");
        }

        if (!File.Exists(manifestPath))
        {
            throw new CompatibilityManifestException($"兼容清单不存在：{manifestPath}");
        }

        string json;
        try
        {
            json = File.ReadAllText(manifestPath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            throw new CompatibilityManifestException($"读取兼容清单失败（{manifestPath}）：{ex.Message}", ex);
        }

        CompatibilityManifest? manifest;
        try
        {
            manifest = System.Text.Json.JsonSerializer.Deserialize<CompatibilityManifest>(json, ScoutMindJson.Options);
        }
        catch (System.Text.Json.JsonException ex)
        {
            throw new CompatibilityManifestException($"兼容清单不是合法 JSON（{manifestPath}）：{ex.Message}", ex);
        }

        if (manifest is null)
        {
            throw new CompatibilityManifestException($"兼容清单为空（{manifestPath}）。");
        }

        if (manifest.SchemaVersion != SupportedSchemaVersion)
        {
            throw new CompatibilityManifestException(
                $"兼容清单 schemaVersion={manifest.SchemaVersion} 不受支持（当前仅支持 {SupportedSchemaVersion}）。");
        }

        if (manifest.Entries is null)
        {
            throw new CompatibilityManifestException($"兼容清单缺少 entries 数组（{manifestPath}）。");
        }

        return manifest;
    }

    /// <summary>按 AppId、构建号与插件产品版本做严格匹配并给出判定。</summary>
    /// <param name="input">本机观测值。</param>
    /// <returns>判定结果；只有 <c>verified</c> 命中才会返回 <see cref="CompatibilityStatus.Verified"/>。</returns>
    public CompatibilityResult Evaluate(CompatibilityInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        var checkedAt = DateTimeOffset.UtcNow;
        var appId = Normalize(input.AppId);
        var buildId = Normalize(input.BuildId);
        var pluginVersion = Normalize(input.PluginProductVersion);

        CompatibilityResult Unsupported(string reason) =>
            new(CompatibilityStatus.Rejected, null, reason, checkedAt, input.AppId, input.BuildId, input.PluginProductVersion);

        CompatibilityResult Unknown(string reason) =>
            new(CompatibilityStatus.Candidate, null, reason, checkedAt, input.AppId, input.BuildId, input.PluginProductVersion);

        if (appId is null)
        {
            return Unknown("未提供 Steam AppId，无法判定兼容性。");
        }

        var byApp = _manifest.Entries
            .Where(entry => string.Equals(entry.AppId?.Trim(), appId, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (byApp.Count == 0)
        {
            return Unsupported($"兼容清单中没有 AppId={appId} 的条目，拒绝读取。");
        }

        if (buildId is null)
        {
            return Unknown("未能识别 FM27 构建号（appmanifest 缺少 buildid），按策略拒绝读取。");
        }

        var byBuild = byApp
            .Where(entry => string.Equals(entry.BuildId?.Trim(), buildId, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (byBuild.Count == 0)
        {
            var known = string.Join("、", byApp.Select(entry => entry.BuildId).Distinct(StringComparer.OrdinalIgnoreCase));
            return Unsupported(
                $"未收录的 FM27 构建 {buildId}（清单已知：{known}）。拒绝读取，且不会回退到旧版本偏移量。");
        }

        if (pluginVersion is null)
        {
            return Unknown($"已识别构建 {buildId}，但无法读取 game_plugin.dll 产品版本，拒绝读取。");
        }

        var exact = byBuild.FirstOrDefault(
            entry => string.Equals(entry.PluginProductVersion?.Trim(), pluginVersion, StringComparison.Ordinal));
        if (exact is null)
        {
            var expected = string.Join("、", byBuild.Select(entry => entry.PluginProductVersion).Distinct(StringComparer.Ordinal));
            return Unsupported(
                $"构建 {buildId} 的插件版本与清单不符：实际 {pluginVersion}，清单为 {expected}。拒绝读取。");
        }

        var rule = $"appId={appId};buildId={buildId};pluginProductVersion={pluginVersion}";
        switch (exact.Status)
        {
            case CompatibilityStatus.Verified:
                return new CompatibilityResult(
                    CompatibilityStatus.Verified,
                    rule,
                    $"构建 {buildId} 与插件版本 {pluginVersion} 命中已验证条目，允许执行 probe。",
                    checkedAt,
                    input.AppId,
                    input.BuildId,
                    input.PluginProductVersion);

            case CompatibilityStatus.Candidate:
                return new CompatibilityResult(
                    CompatibilityStatus.Candidate,
                    rule,
                    "候选兼容项，需本机 probe 验证",
                    checkedAt,
                    input.AppId,
                    input.BuildId,
                    input.PluginProductVersion);

            default:
                return new CompatibilityResult(
                    CompatibilityStatus.Rejected,
                    rule,
                    $"构建 {buildId} 在兼容清单中被标记为 rejected：{exact.Notes ?? "无说明"}。拒绝读取。",
                    checkedAt,
                    input.AppId,
                    input.BuildId,
                    input.PluginProductVersion);
        }
    }

    private static string? Normalize(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}
