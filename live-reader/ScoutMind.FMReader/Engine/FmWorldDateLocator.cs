using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次世界日期定位的环境与结果。</summary>
/// <param name="ProcessDetected">是否检测到 FM27。</param>
/// <param name="Build">构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="Matches">命中。</param>
/// <param name="Status">`ok` / `game_not_running` / `unsupported_build`。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record FmWorldDateResult(
    bool ProcessDetected,
    string? Build,
    string? PluginVersion,
    IReadOnlyList<WorldDateMatch> Matches,
    string Status,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 按结构签名在真实进程里定位世界日期：不依赖绝对地址与指针链，
/// 适合在游戏重启后重新找到同一条记录。命中仍需与游戏内日期比对才算证据。
/// </summary>
public sealed class FmWorldDateLocator
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;

    /// <summary>创建定位器。</summary>
    /// <param name="detector">进程/版本检测。</param>
    /// <param name="gate">版本闸门。</param>
    public FmWorldDateLocator(GameBuildDetector? detector = null, VersionGate? gate = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
    }

    /// <summary>执行定位。</summary>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>定位结果。</returns>
    public Task<FmWorldDateResult> LocateAsync(long maxBytes, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var diagnostics = new List<string>();
        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);

        if (detected.ProcessId is null)
        {
            diagnostics.Add("FM27 进程未运行：无法定位世界日期。");
            return Task.FromResult(new FmWorldDateResult(
                false, detected.Build, detected.PluginVersion,
                Array.Empty<WorldDateMatch>(), "game_not_running", diagnostics));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            diagnostics.Add(gate.Message);
            return Task.FromResult(new FmWorldDateResult(
                true, detected.Build, detected.PluginVersion,
                Array.Empty<WorldDateMatch>(), "unsupported_build", diagnostics));
        }

        try
        {
            using var memory = WinMemorySource.Open();
            var result = WorldDateLocator.Scan(memory, maxBytes, null, cancellationToken);
            diagnostics.AddRange(result.Diagnostics);
            return Task.FromResult(new FmWorldDateResult(
                true, detected.Build, detected.PluginVersion, result.Matches, "ok", diagnostics));
        }
        catch (MemoryUnreadableException ex)
        {
            diagnostics.Add($"无法读取 FM27 内存：{ex.Message}");
            return Task.FromResult(new FmWorldDateResult(
                true, detected.Build, detected.PluginVersion,
                Array.Empty<WorldDateMatch>(), "game_not_running", diagnostics));
        }
    }
}
