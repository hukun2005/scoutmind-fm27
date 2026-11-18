using System.Text.Json.Serialization;

namespace ScoutMind.Contracts;

/// <summary>
/// 读取器生命周期状态。按协议以枚举名原样序列化（例如 <c>"NotFound"</c>），
/// 后端、前端与代理据此判断是否允许读取游戏数据。
/// </summary>
/// <remarks>
/// 允许的迁移边由 <c>ScoutMind.Reader.StateMachine</c> 维护；任何失败状态（
/// <see cref="Unsupported"/>、<see cref="Unknown"/>、<see cref="ProbeFailed"/>）都表示
/// 读取器必须拒绝读取游戏内存。
/// </remarks>
[JsonConverter(typeof(JsonStringEnumConverter<ReaderState>))]
public enum ReaderState
{
    /// <summary>未找到 FM27：既没有 Steam 安装清单，也没有运行中的 FM27 进程。</summary>
    NotFound,

    /// <summary>已找到 FM27 安装或运行中的进程，但尚未确认构建版本。</summary>
    Detected,

    /// <summary>已从 appmanifest 与 game_plugin.dll 读取到构建号与插件版本。</summary>
    VersionIdentified,

    /// <summary>构建号与插件版本命中兼容清单中的 <c>verified</c> 条目，允许执行 probe。</summary>
    Compatible,

    /// <summary>本机 probe 已通过，允许执行扫描。</summary>
    ProbePassed,

    /// <summary>扫描已完成，原始数据已落盘。</summary>
    ScanCompleted,

    /// <summary>构建或版本不受支持：必须拒绝读取，且不得回退到旧版本的偏移量。</summary>
    Unsupported,

    /// <summary>版本无法确定（例如清单中只有 candidate 条目）：必须拒绝读取。</summary>
    Unknown,

    /// <summary>probe 或扫描失败：必须拒绝读取。</summary>
    ProbeFailed,
}
