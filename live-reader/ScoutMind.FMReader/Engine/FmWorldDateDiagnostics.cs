using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>
/// 世界日期诊断的真实进程入口：识别进程/构建 → 打开只读内存 → 采集与追踪 → 持久化验证状态 → 安全门。
///
/// 只读：不写入内存、不注入、不修改游戏。
/// </summary>
public sealed class FmWorldDateDiagnostics
{
    private readonly GameBuildDetector _detector;
    private readonly Func<WinMemorySource> _openMemory;

    /// <summary>创建诊断器。</summary>
    /// <param name="detector">构建检测器。</param>
    /// <param name="openMemory">内存源工厂（测试可替换）。</param>
    public FmWorldDateDiagnostics(
        GameBuildDetector? detector = null,
        Func<WinMemorySource>? openMemory = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _openMemory = openMemory ?? WinMemorySource.Open;
    }

    /// <summary>执行诊断。</summary>
    /// <param name="operatorVisibleDate">人工观察到的界面日期。</param>
    /// <param name="statePath">验证状态文件路径；为空使用默认路径。</param>
    /// <param name="maxBytes">扫描预算。</param>
    /// <param name="hints">对象类型提示。</param>
    /// <param name="now">当前时间。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>诊断报告。</returns>
    public WorldDateDiagnosticsReport Analyze(
        DateOnly? operatorVisibleDate = null,
        string? statePath = null,
        long maxBytes = WorldDateLocator.DefaultMaxBytes,
        IReadOnlyList<DateObjectHint>? hints = null,
        DateTimeOffset? now = null,
        CancellationToken cancellationToken = default)
    {
        var detected = _detector.Detect();
        if (detected.ProcessId is null)
        {
            return WorldDateDiagnostics.Unavailable(
                "game_not_running",
                BuildSession(detected, 0),
                "未检测到正在运行的 fm.exe：不会猜测日期。",
                detected.Diagnostics);
        }

        var gate = new VersionGate().Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            return WorldDateDiagnostics.Unavailable(
                "unsupported_build",
                BuildSession(detected, 0),
                gate.Message,
                detected.Diagnostics);
        }

        WinMemorySource? memory = null;
        try
        {
            memory = _openMemory();
            var bounds = memory.Bounds;
            if (bounds.GpEnd <= bounds.GpBase)
            {
                return WorldDateDiagnostics.Unavailable(
                    "no_modules",
                    BuildSession(detected, 0),
                    "没有解析到 game_plugin 模块边界。",
                    detected.Diagnostics);
            }

            var session = BuildSession(detected, bounds.GpBase);
            var store = new DateVerificationStore(statePath);
            var outcome = WorldDateDiagnostics.Analyze(
                memory,
                session,
                operatorVisibleDate,
                saveKey: null,
                store.Load(),
                maxBytes,
                hints,
                readerVersionSupported: gate.AllowScan,
                processSessionValid: true,
                now,
                cancellationToken,
                BuildModuleRegions(bounds));

            store.Save(outcome.State);
            return outcome.Report;
        }
        catch (MemoryUnreadableException ex)
        {
            return WorldDateDiagnostics.Unavailable(
                "unreadable",
                BuildSession(detected, 0),
                $"无法读取游戏内存：{ex.Message}",
                detected.Diagnostics);
        }
        finally
        {
            memory?.Dispose();
        }
    }

    /// <summary>把上游模块边界转成引用链扫描区域。</summary>
    private static IReadOnlyList<ModuleRegion> BuildModuleRegions(ModuleBounds bounds)
    {
        var regions = new List<ModuleRegion>(2);
        if (bounds.GpEnd > bounds.GpBase)
        {
            regions.Add(new ModuleRegion("gp", bounds.GpBase, bounds.GpBase, bounds.GpEnd - bounds.GpBase));
        }

        if (bounds.GaEnd > bounds.GaBase)
        {
            regions.Add(new ModuleRegion("ga", bounds.GaBase, bounds.GaBase, bounds.GaEnd - bounds.GaBase));
        }

        return regions;
    }

    private static ProcessSessionIdentity BuildSession(DetectedGame detected, ulong moduleBase)
    {
        var start = ReadStartTime(detected.ProcessId);
        var key = detected.ProcessId is null
            ? "unknown"
            : $"{detected.ProcessId}:{start ?? "unknown"}:{detected.Build ?? "unknown"}";
        return new ProcessSessionIdentity(
            key,
            detected.ProcessId,
            start,
            detected.Build,
            detected.PluginVersion,
            moduleBase);
    }

    private static string? ReadStartTime(int? processId)
    {
        if (processId is null)
        {
            return null;
        }

        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(processId.Value);
            return process.StartTime.ToUniversalTime().ToString("O");
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            return null;
        }
    }
}
