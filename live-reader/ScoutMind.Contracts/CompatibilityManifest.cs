namespace ScoutMind.Contracts;

/// <summary>
/// 兼容清单中的单条记录，对应 <c>config/compatibility.json</c> 的一个元素。
/// 三者（AppId、构建号、插件产品版本）必须同时匹配才可能命中。
/// </summary>
/// <param name="AppId">Steam AppId，FM27 为 <c>4530370</c>。</param>
/// <param name="BuildId">Steam 清单中的构建号，例如 <c>26577676</c>。</param>
/// <param name="PluginProductVersion">安装目录 <c>game_plugin.dll</c> 的产品版本，例如 <c>27.0.1+2503222</c>。</param>
/// <param name="Status">条目状态；只有 <see cref="CompatibilityStatus.Verified"/> 允许读取。</param>
/// <param name="Notes">面向用户的中文说明，通常记录该条目的验证来源与限制。</param>
/// <param name="VerifiedAt">该条目在本机完成验证的 UTC 时间；候选条目为 <c>null</c>。</param>
public sealed record CompatibilityEntry(
    string AppId,
    string BuildId,
    string PluginProductVersion,
    CompatibilityStatus Status,
    string? Notes,
    DateTimeOffset? VerifiedAt);

/// <summary>
/// 兼容清单根对象。读取器只信任本文件，绝不内置任何构建号或偏移量常量。
/// </summary>
/// <param name="SchemaVersion">清单结构版本，当前为 1；读取器只接受已知版本。</param>
/// <param name="Entries">兼容条目集合，可以为空（此时所有构建都判为 Unknown）。</param>
public sealed record CompatibilityManifest(
    int SchemaVersion,
    List<CompatibilityEntry> Entries);
