using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次启发式日期解析的环境与结果。</summary>
/// <param name="ProcessDetected">是否检测到 FM27。</param>
/// <param name="Build">构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="Resolution">解析结果。</param>
/// <param name="Status">`ok` / `game_not_running` / `unsupported_build`。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record FmWorldDateOutcome(
    bool ProcessDetected,
    string? Build,
    string? PluginVersion,
    WorldDateResolution? Resolution,
    string Status,
    IReadOnlyList<string> Diagnostics);

/// <summary>在真实进程上执行启发式世界日期解析。</summary>
public sealed class FmWorldDate
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;

    /// <summary>创建解析器。</summary>
    /// <param name="detector">进程/版本检测。</param>
    /// <param name="gate">版本闸门。</param>
    public FmWorldDate(GameBuildDetector? detector = null, VersionGate? gate = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
    }

    /// <summary>解析当前游戏日期。</summary>
    /// <param name="maxBytes">签名扫描预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>解析结果。</returns>
    public Task<FmWorldDateOutcome> ResolveAsync(long maxBytes, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var diagnostics = new List<string>();
        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);

        if (detected.ProcessId is null)
        {
            diagnostics.Add("FM27 进程未运行：无法解析世界日期。");
            return Task.FromResult(new FmWorldDateOutcome(
                false, detected.Build, detected.PluginVersion, null, "game_not_running", diagnostics));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            diagnostics.Add(gate.Message);
            return Task.FromResult(new FmWorldDateOutcome(
                true, detected.Build, detected.PluginVersion, null, "unsupported_build", diagnostics));
        }

        try
        {
            using var memory = WinMemorySource.Open();
            var resolution = WorldDateResolver.Resolve(memory, maxBytes, cancellationToken);
            diagnostics.AddRange(resolution.Diagnostics);
            return Task.FromResult(new FmWorldDateOutcome(
                true, detected.Build, detected.PluginVersion, resolution, "ok", diagnostics));
        }
        catch (MemoryUnreadableException ex)
        {
            diagnostics.Add($"无法读取 FM27 内存：{ex.Message}");
            return Task.FromResult(new FmWorldDateOutcome(
                true, detected.Build, detected.PluginVersion, null, "game_not_running", diagnostics));
        }
    }
}

