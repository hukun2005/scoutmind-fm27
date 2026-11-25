using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次静态根扫描的环境与结果。</summary>
/// <param name="ProcessDetected">是否检测到 FM27。</param>
/// <param name="Build">构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="ModuleRegions">参与扫描的模块区域。</param>
/// <param name="Roots">候选路径。</param>
/// <param name="Status">`ok` / `game_not_running` / `unsupported_build` / `no_modules`。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record FmStaticDateResult(
    bool ProcessDetected,
    string? Build,
    string? PluginVersion,
    IReadOnlyList<MemoryRegion> ModuleRegions,
    IReadOnlyList<StaticDateRoot> Roots,
    string Status,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 用上游解析出的模块边界做静态根扫描：模块区域来自 <see cref="WinMemorySource.Bounds"/>，
/// 不再依赖“扫描区域里是否恰好包含模块”的猜测。
/// </summary>
public sealed class FmStaticDateScan
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;

    /// <summary>创建扫描器。</summary>
    /// <param name="detector">进程/版本检测。</param>
    /// <param name="gate">版本闸门。</param>
    public FmStaticDateScan(GameBuildDetector? detector = null, VersionGate? gate = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
    }

    /// <summary>执行扫描。</summary>
    /// <param name="expected">人工确认的游戏内日期。</param>
    /// <param name="maxDepth">最大跳数。</param>
    /// <param name="maxBytes">模块内扫描预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    public Task<FmStaticDateResult> ScanAsync(
        DateOnly expected,
        int maxDepth,
        long maxBytes,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var diagnostics = new List<string>();
        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);

        if (detected.ProcessId is null)
        {
            diagnostics.Add("FM27 进程未运行：无法执行静态根扫描。");
            return Task.FromResult(new FmStaticDateResult(
                false, detected.Build, detected.PluginVersion,
                Array.Empty<MemoryRegion>(), Array.Empty<StaticDateRoot>(), "game_not_running", diagnostics));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            diagnostics.Add(gate.Message);
            return Task.FromResult(new FmStaticDateResult(
                true, detected.Build, detected.PluginVersion,
                Array.Empty<MemoryRegion>(), Array.Empty<StaticDateRoot>(), "unsupported_build", diagnostics));
        }

        try
        {
            using var memory = WinMemorySource.Open();
            var regions = BuildModuleRegions(memory);
            if (regions.Count == 0)
            {
                diagnostics.Add("上游扫描器没有解析出模块边界（game_plugin / GameAssembly）。");
                return Task.FromResult(new FmStaticDateResult(
                    true, detected.Build, detected.PluginVersion,
                    Array.Empty<MemoryRegion>(), Array.Empty<StaticDateRoot>(), "no_modules", diagnostics));
            }

            var result = StaticDateScan.Scan(memory, regions, expected, maxDepth, maxBytes, null, cancellationToken);
            diagnostics.AddRange(result.Diagnostics);
            return Task.FromResult(new FmStaticDateResult(
                true, detected.Build, detected.PluginVersion, regions, result.Roots, "ok", diagnostics));
        }
        catch (MemoryUnreadableException ex)
        {
            diagnostics.Add($"无法读取 FM27 内存：{ex.Message}");
            return Task.FromResult(new FmStaticDateResult(
                true, detected.Build, detected.PluginVersion,
                Array.Empty<MemoryRegion>(), Array.Empty<StaticDateRoot>(), "game_not_running", diagnostics));
        }
    }

    /// <summary>把上游模块边界转成扫描区域。</summary>
    /// <param name="memory">内存源。</param>
    /// <returns>模块区域。</returns>
    public static IReadOnlyList<MemoryRegion> BuildModuleRegions(WinMemorySource memory)
    {
        ArgumentNullException.ThrowIfNull(memory);
        var bounds = memory.Bounds;
        var regions = new List<MemoryRegion>(2);
        if (bounds.GpEnd > bounds.GpBase)
        {
            regions.Add(new MemoryRegion(bounds.GpBase, bounds.GpEnd - bounds.GpBase));
        }

        if (bounds.GaEnd > bounds.GaBase)
        {
            regions.Add(new MemoryRegion(bounds.GaBase, bounds.GaEnd - bounds.GaBase));
        }

        return regions;
    }
}
