using System.Text.Json.Serialization;

namespace ScoutMind.Contracts;

/// <summary>
/// 一次状态快照，是 <c>ScoutMind.LiveReader status --json</c> 的输出。
/// 所有字段都来自本机真实测量（注册表、appmanifest、进程、文件版本信息），没有推断值。
/// </summary>
/// <param name="State">当前状态机的状态。</param>
/// <param name="Message">面向用户的中文状态说明，失败时说明拒绝读取的原因。</param>
/// <param name="DetectedAt">生成该快照的 UTC 时间，序列化为 <c>yyyy-MM-ddTHH:mm:ssZ</c>。</param>
/// <param name="Process">运行中的 FM27 进程信息；游戏未运行时为 <c>null</c>。</param>
/// <param name="Game">从 Steam 安装清单解析出的游戏信息；未找到安装时为 <c>null</c>。</param>
/// <param name="Plugin">安装目录中 <c>game_plugin.dll</c> 的版本信息；文件缺失时为 <c>null</c>。</param>
/// <param name="Compatibility">兼容性判定结果；尚未判定时为 <c>null</c>。</param>
/// <param name="Diagnostics">检测过程中产生的诊断信息（访问拒绝、文件缺失等），用于排错。</param>
/// <param name="ReaderVersion">读取器版本号，与 <c>readerVersion</c> 常量一致。</param>
public sealed record ReaderStatus(
    ReaderState State,
    string Message,
    DateTimeOffset DetectedAt,
    ProcessInfo? Process,
    GameInfo? Game,
    PluginInfo? Plugin,
    CompatibilityResult? Compatibility,
    List<string> Diagnostics,
    string ReaderVersion);

/// <summary>
/// 运行中的 FM27 进程信息。只有可执行文件名以 <c>fm.exe</c> 结尾、且（可读时）
/// <c>ProductName</c> 含 "Football Manager" 的进程才会被接受，避免误判同名进程。
/// </summary>
/// <param name="Pid">操作系统进程 ID。</param>
/// <param name="ProcessName">进程名（不含扩展名）。</param>
/// <param name="ExecutablePath">主模块的完整路径；无法读取时为 <c>null</c>。</param>
/// <param name="ProductName">可执行文件版本资源中的产品名。</param>
/// <param name="FileVersion">可执行文件的文件版本字符串。</param>
/// <param name="ProductVersion">可执行文件的产品版本字符串。</param>
public sealed record ProcessInfo(
    int Pid,
    string ProcessName,
    string? ExecutablePath,
    string? ProductName,
    string? FileVersion,
    string? ProductVersion);

/// <summary>
/// 从 Steam 安装清单（<c>appmanifest_4530370.acf</c>）解析出的游戏信息。
/// <c>buildId</c> 是版本闸门的唯一依据；缺失时读取器必须停在 Unknown。
/// </summary>
/// <param name="AppId">Steam AppId，FM27 为 <c>4530370</c>。</param>
/// <param name="BuildId">清单中的 <c>buildid</c>，例如 <c>26577676</c>；缺失时为 <c>null</c>。</param>
/// <param name="InstallDir">游戏安装目录的绝对路径。</param>
/// <param name="SteamLibrary">该安装所在的 Steam 库根目录。</param>
/// <param name="GameVersion">游戏版本号（通常取插件产品版本的前缀，例如 <c>27.0.1</c>）。</param>
public sealed record GameInfo(
    string AppId,
    string? BuildId,
    string? InstallDir,
    string? SteamLibrary,
    string? GameVersion);

/// <summary>
/// 安装目录中 <c>game_plugin.dll</c> 的版本信息。仅读取文件的版本资源，绝不加载该 DLL。
/// </summary>
/// <param name="Path">DLL 的绝对路径。</param>
/// <param name="ProductVersion">产品版本，例如 <c>27.0.1+2503222</c>；这是兼容清单匹配的关键值。</param>
/// <param name="FileVersion">文件版本字符串。</param>
public sealed record PluginInfo(
    string Path,
    string? ProductVersion,
    string? FileVersion);

/// <summary>
/// 兼容清单条目的状态。序列化为小写字符串（<c>candidate</c> / <c>verified</c> / <c>rejected</c>）。
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter<CompatibilityStatus>))]
public enum CompatibilityStatus
{
    /// <summary>候选条目：只能推导出 Unknown，必须由本机 probe 验证后才可提升。</summary>
    [JsonStringEnumMemberName("candidate")]
    Candidate,

    /// <summary>已验证条目：允许进入 Compatible。</summary>
    [JsonStringEnumMemberName("verified")]
    Verified,

    /// <summary>已拒绝条目：命中即 Unsupported。</summary>
    [JsonStringEnumMemberName("rejected")]
    Rejected,
}

/// <summary>
/// 一次兼容性判定的结果。命中 <c>verified</c> 才算兼容；<c>candidate</c> 只给出 Unknown。
/// </summary>
/// <param name="Status">判定状态：兼容、未知或不受支持。</param>
/// <param name="MatchedRule">命中的匹配规则描述；未命中时为 <c>null</c>。</param>
/// <param name="Reason">面向用户的中文原因说明。</param>
/// <param name="CheckedAt">判定发生的 UTC 时间。</param>
/// <param name="ObservedAppId">本次实际观测到的 AppId，用于诊断与排错。</param>
/// <param name="ObservedBuildId">本次实际观测到的构建号。</param>
/// <param name="ObservedPluginProductVersion">本次实际观测到的插件产品版本。</param>
public sealed record CompatibilityResult(
    CompatibilityStatus Status,
    string? MatchedRule,
    string Reason,
    DateTimeOffset CheckedAt,
    string? ObservedAppId,
    string? ObservedBuildId,
    string? ObservedPluginProductVersion);
