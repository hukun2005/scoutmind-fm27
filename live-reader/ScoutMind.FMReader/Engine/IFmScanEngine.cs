using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>引擎能力状态（不接触游戏内存即可得到）。</summary>
/// <param name="ProcessId">fm.exe 进程号；未运行时为 <c>null</c>。</param>
/// <param name="ProcessPath">fm.exe 路径；未知时为 <c>null</c>。</param>
/// <param name="InstallDirectory">安装目录；未知时为 <c>null</c>。</param>
/// <param name="AppId">Steam AppId。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginPath">game_plugin.dll 路径。</param>
/// <param name="PluginVersion">插件文件版本，例如 <c>27.1.0+2505117</c>。</param>
/// <param name="AccessDenied">进程存在但无法打开（通常 FM 以管理员运行）。</param>
/// <param name="Diagnostics">诊断信息。</param>
/// <param name="Gate">版本闸门判定。</param>
/// <param name="EngineVersion">引擎版本。</param>
public sealed record FmEngineStatus(
    int? ProcessId,
    string? ProcessPath,
    string? InstallDirectory,
    string? AppId,
    string? Build,
    string? PluginPath,
    string? PluginVersion,
    bool AccessDenied,
    IReadOnlyList<string> Diagnostics,
    VersionGateResult? Gate,
    string EngineVersion);

/// <summary>probe 结果：能否安全读取。</summary>
/// <param name="Passed">是否通过（诊断报告的整体状态为 Verified）。</param>
/// <param name="Reason">失败原因；通过时为 <c>null</c>。</param>
/// <param name="Status">当时的完整状态。</param>
/// <param name="DurationMs">耗时。</param>
/// <param name="Report">诊断报告；无法探测时为 <c>null</c>。</param>
public sealed record FmProbeResult(
    bool Passed,
    string? Reason,
    FmEngineStatus Status,
    long DurationMs,
    Probes.DiagnosticReport? Report = null);

/// <summary>扫描结果。</summary>
/// <param name="PayloadJson">符合 ScoutMind 扫描协议的 JSON 文本；失败时为 <c>null</c>。</param>
/// <param name="Players">球员数。</param>
/// <param name="Clubs">俱乐部数。</param>
/// <param name="Transfers">转会数（上游导出不含转会，通常为 0）。</param>
/// <param name="Coverage">覆盖域。</param>
/// <param name="Warnings">告警（原样上报）。</param>
/// <param name="Status">当时的状态。</param>
/// <param name="FailureReason">失败原因；成功时为 <c>null</c>。</param>
/// <param name="RawDumpPath">上游 dump 文件的临时路径，便于诊断；成功后可删除。</param>
public sealed record FmScanResult(
    string? PayloadJson,
    int Players,
    int Clubs,
    int Transfers,
    IReadOnlyDictionary<string, bool> Coverage,
    IReadOnlyList<string> Warnings,
    FmEngineStatus Status,
    string? FailureReason,
    string? RawDumpPath);

/// <summary>
/// FM 只读扫描引擎。实现者负责：进程识别、版本闸门、内存读取（只读）、上游结构到 ScoutMind
/// 协议的转换。调用方只看到协议 JSON，永远拿不到上游原始数据结构。
/// </summary>
public interface IFmScanEngine
{
    /// <summary>引擎版本，写入告警与诊断。</summary>
    string Version { get; }

    /// <summary>读取进程、安装目录、插件版本并做版本闸门判定；不接触游戏内存。</summary>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>能力状态。</returns>
    Task<FmEngineStatus> GetStatusAsync(CancellationToken cancellationToken);

    /// <summary>
    /// 自检：确认构建允许读取、进程可打开、关键对象可解析。通过后调用方才能扫描。
    /// </summary>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>probe 结果。</returns>
    Task<FmProbeResult> ProbeAsync(CancellationToken cancellationToken);

    /// <summary>执行一次结构化诊断（球员/俱乐部/球队/合同/租借/转会/完整性），返回报告。</summary>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>诊断报告。</returns>
    Task<Probes.DiagnosticReport> DiagnoseAsync(CancellationToken cancellationToken);

    /// <summary>执行一次只读扫描并返回 ScoutMind 协议报文。</summary>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    Task<FmScanResult> ScanAsync(CancellationToken cancellationToken);
}
