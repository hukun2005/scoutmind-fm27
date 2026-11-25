using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>
/// 一次日期候选发现的环境与结果。`VerificationStatus` 只会是 `game_not_running`、
/// `unsupported_build`、`layout_not_verified`、`blocked` 或 `unverified_candidate`；
/// 单次命中永远不会被标成 `verified`。
/// </summary>
/// <param name="ProcessDetected">是否检测到 FM27。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="AppId">Steam AppId。</param>
/// <param name="Layout">命中的布局名。</param>
/// <param name="ExpectedDate">人工提供的游戏内日期。</param>
/// <param name="EncodedValue">FM 日期编码。</param>
/// <param name="Candidates">命中的候选（地址只用于本地多日期比对）。</param>
/// <param name="VerificationStatus">验证状态。</param>
/// <param name="Diagnostics">诊断说明。</param>
public sealed record FmDateDiscoveryResult(
    bool ProcessDetected,
    string? Build,
    string? PluginVersion,
    string? AppId,
    string? Layout,
    string ExpectedDate,
    uint EncodedValue,
    IReadOnlyList<DateCandidate> Candidates,
    string VerificationStatus,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 日期候选发现：在真实 FM27 进程上做一次有预算的只读扫描。
///
/// 它不假设偏移、不读取"看起来像日期"的整数，只寻找与人工提供的游戏内日期逐位相等的编码；
/// 是否真的对应"当前日期"必须由同一地址在多个独立游戏日期上的表现来证明。
/// </summary>
public sealed class FmDateDiscovery
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;
    private readonly LayoutResolver _layouts;

    /// <summary>创建发现器。</summary>
    /// <param name="detector">进程/版本检测。</param>
    /// <param name="gate">版本闸门。</param>
    /// <param name="layouts">布局解析。</param>
    public FmDateDiscovery(
        GameBuildDetector? detector = null,
        VersionGate? gate = null,
        LayoutResolver? layouts = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
        _layouts = layouts ?? new LayoutResolver();
    }

    /// <summary>执行一次候选发现。</summary>
    /// <param name="expected">人工确认的游戏内日期。</param>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>发现结果。</returns>
    public Task<FmDateDiscoveryResult> DiscoverAsync(
        DateOnly expected,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var expectedText = expected.ToString("yyyy-MM-dd");
        var encoded = DateDiscovery.Encode(expected);
        var diagnostics = new List<string>();
        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);

        if (detected.ProcessId is null)
        {
            diagnostics.Add("FM27 进程未运行：无法执行日期候选发现。");
            return Task.FromResult(Blocked(
                detected, null, expectedText, encoded, "game_not_running", diagnostics));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            diagnostics.Add(gate.Message);
            return Task.FromResult(Blocked(
                detected, gate.Layout, expectedText, encoded, "unsupported_build", diagnostics));
        }

        var layout = _layouts.Resolve(detected.Build, detected.PluginVersion);
        if (layout is null || !LayoutResolver.IsRegistered(detected.Build))
        {
            diagnostics.Add("当前构建没有可用布局：拒绝读取内存。");
            return Task.FromResult(Blocked(
                detected, gate.Layout, expectedText, encoded, "layout_not_verified", diagnostics));
        }

        try
        {
            using var memory = WinMemorySource.Open();
            var result = DateDiscovery.Discover(memory, expected, maxBytes, null, cancellationToken);
            diagnostics.AddRange(result.Diagnostics);
            var status = result.Candidates.Count > 0 ? "unverified_candidate" : "blocked";
            if (result.Candidates.Count > 0)
            {
                diagnostics.Add(
                    $"命中 {result.Candidates.Count} 个候选；必须在另一个独立游戏日期上再次比对同一地址，才能升级为 Verified。");
            }

            return Task.FromResult(new FmDateDiscoveryResult(
                ProcessDetected: true,
                Build: detected.Build,
                PluginVersion: detected.PluginVersion,
                AppId: detected.AppId,
                Layout: layout.Name,
                ExpectedDate: expectedText,
                EncodedValue: encoded,
                Candidates: result.Candidates,
                VerificationStatus: status,
                Diagnostics: diagnostics));
        }
        catch (MemoryUnreadableException ex)
        {
            diagnostics.Add($"无法读取 FM27 内存：{ex.Message}");
            return Task.FromResult(Blocked(
                detected, layout.Name, expectedText, encoded, "blocked", diagnostics));
        }
    }

    private static FmDateDiscoveryResult Blocked(
        DetectedGame detected,
        string? layout,
        string expectedDate,
        uint encoded,
        string status,
        IReadOnlyList<string> diagnostics) =>
        new(
            ProcessDetected: detected.ProcessId is not null,
            Build: detected.Build,
            PluginVersion: detected.PluginVersion,
            AppId: detected.AppId,
            Layout: layout,
            ExpectedDate: expectedDate,
            EncodedValue: encoded,
            Candidates: Array.Empty<DateCandidate>(),
            VerificationStatus: status,
            Diagnostics: diagnostics);
}
