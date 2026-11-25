using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次指针扫描的环境与结果。</summary>
/// <param name="ProcessDetected">是否检测到 FM27。</param>
/// <param name="Build">构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="TargetStart">目标区间起点。</param>
/// <param name="TargetEnd">目标区间终点。</param>
/// <param name="Hits">命中的指针。</param>
/// <param name="Status">状态：`ok` / `game_not_running` / `unsupported_build`。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record FmPointerScanResult(
    bool ProcessDetected,
    string? Build,
    string? PluginVersion,
    ulong TargetStart,
    ulong TargetEnd,
    IReadOnlyList<PointerHit> Hits,
    string Status,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 在真实 FM27 进程上做一次只读指针扫描，用于寻找引用目标结构的指针，
/// 进而定位模块静态数据里的根，得到跨重启可复用的“模块偏移 + 偏移链”。
/// </summary>
public sealed class FmPointerScan
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;

    /// <summary>创建扫描器。</summary>
    /// <param name="detector">进程/版本检测。</param>
    /// <param name="gate">版本闸门。</param>
    public FmPointerScan(GameBuildDetector? detector = null, VersionGate? gate = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
    }

    /// <summary>执行指针扫描。</summary>
    /// <param name="targetStart">目标区间起点。</param>
    /// <param name="window">目标区间长度。</param>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    public Task<FmPointerScanResult> ScanAsync(
        ulong targetStart,
        int window,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var diagnostics = new List<string>();
        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);
        var targetEnd = targetStart + (ulong)Math.Max(8, window);

        if (detected.ProcessId is null)
        {
            diagnostics.Add("FM27 进程未运行：无法执行指针扫描。");
            return Task.FromResult(new FmPointerScanResult(
                false, detected.Build, detected.PluginVersion, targetStart, targetEnd,
                Array.Empty<PointerHit>(), "game_not_running", diagnostics));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            diagnostics.Add(gate.Message);
            return Task.FromResult(new FmPointerScanResult(
                true, detected.Build, detected.PluginVersion, targetStart, targetEnd,
                Array.Empty<PointerHit>(), "unsupported_build", diagnostics));
        }

        try
        {
            using var memory = WinMemorySource.Open();
            var result = PointerScan.Scan(memory, targetStart, targetEnd, maxBytes, null, cancellationToken);
            diagnostics.AddRange(result.Diagnostics);
            return Task.FromResult(new FmPointerScanResult(
                true, detected.Build, detected.PluginVersion, targetStart, targetEnd,
                result.Hits, "ok", diagnostics));
        }
        catch (MemoryUnreadableException ex)
        {
            diagnostics.Add($"无法读取 FM27 内存：{ex.Message}");
            return Task.FromResult(new FmPointerScanResult(
                true, detected.Build, detected.PluginVersion, targetStart, targetEnd,
                Array.Empty<PointerHit>(), "game_not_running", diagnostics));
        }
    }
}
