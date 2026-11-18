using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 一次检测的编排：定位安装 → 识别进程 → 读取插件版本 → 版本闸门判定，全程驱动
/// <see cref="StateMachine"/> 并收集诊断。检测过程只读文件与进程元数据，不接触游戏内存。
/// </summary>
public sealed class ReaderPipeline
{
    private readonly SteamLocator _steamLocator;
    private readonly ProcessDetector _processDetector;
    private readonly PluginProbe _pluginProbe;
    private readonly CompatibilityService? _compatibility;
    private readonly string? _compatibilityError;

    /// <summary>创建编排器。</summary>
    /// <param name="compatibility">兼容性服务；兼容清单不可用时为 <c>null</c>，此时状态一律为 Unknown。</param>
    /// <param name="compatibilityError">兼容清单不可用的原因，写入状态说明。</param>
    /// <param name="steamLocator">Steam 定位器，测试可注入替身。</param>
    /// <param name="processDetector">进程序列器，测试可注入替身。</param>
    /// <param name="pluginProbe">插件探测，测试可注入替身。</param>
    public ReaderPipeline(
        CompatibilityService? compatibility,
        string? compatibilityError = null,
        SteamLocator? steamLocator = null,
        ProcessDetector? processDetector = null,
        PluginProbe? pluginProbe = null)
    {
        _compatibility = compatibility;
        _compatibilityError = compatibilityError;
        _steamLocator = steamLocator ?? new SteamLocator();
        _processDetector = processDetector ?? new ProcessDetector();
        _pluginProbe = pluginProbe ?? new PluginProbe();
    }

    /// <summary>
    /// 把兼容性判定映射为读取器状态。只有 <c>verified</c> 才能进入可读取的 Compatible，
    /// <c>candidate</c> 一律停在 Unknown。
    /// </summary>
    /// <param name="status">兼容性状态。</param>
    /// <returns>对应的读取器状态。</returns>
    public static ReaderState MapCompatibilityStatus(CompatibilityStatus status) => status switch
    {
        CompatibilityStatus.Verified => ReaderState.Compatible,
        CompatibilityStatus.Rejected => ReaderState.Unsupported,
        _ => ReaderState.Unknown,
    };

    /// <summary>执行一次检测并返回状态快照。</summary>
    /// <returns>状态快照；失败状态（Unknown / Unsupported）表示必须拒绝读取。</returns>
    public ReaderStatus Detect()
    {
        var diagnostics = new List<string>();
        var machine = new StateMachine();
        var detectedAt = DateTimeOffset.UtcNow;
        ProcessInfo? processInfo = null;
        GameInfo? gameInfo = null;
        PluginInfo? pluginInfo = null;

        ReaderStatus Build(ReaderState state, string message, CompatibilityResult? compatibility = null)
        {
            var allDiagnostics = new List<string>(diagnostics);
            allDiagnostics.AddRange(machine.Diagnostics);
            return new ReaderStatus(
                State: state,
                Message: message,
                DetectedAt: detectedAt,
                Process: processInfo,
                Game: gameInfo,
                Plugin: pluginInfo,
                Compatibility: compatibility,
                Diagnostics: allDiagnostics,
                ReaderVersion: ReaderInfo.Version);
        }

        var install = _steamLocator.Locate();
        diagnostics.AddRange(_steamLocator.Diagnostics);

        var process = _processDetector.Detect();
        diagnostics.AddRange(_processDetector.Diagnostics);
        processInfo = process?.ToContract();

        if (install is null && processInfo is null)
        {
            return Build(ReaderState.NotFound, "未找到 FM27：既没有 Steam 安装清单，也没有运行中的 FM27 进程。");
        }

        if (processInfo is null)
        {
            diagnostics.Add("FM27 进程未运行；执行 probe 与 scan 前需要先启动游戏。");
        }

        if (install is null)
        {
            // A running process without a readable install manifest still proves FM27 exists,
            // but the build cannot be gated, so the only safe state is Unknown.
            machine.TransitionTo(ReaderState.Detected);
            machine.TransitionTo(ReaderState.Unknown);
            return Build(
                ReaderState.Unknown,
                "已找到 FM27 进程，但无法解析 Steam 安装清单（appmanifest_4530370.acf），因此无法确定构建号，拒绝读取。");
        }

        pluginInfo = _pluginProbe.Probe(install.InstallDirectory);
        diagnostics.AddRange(_pluginProbe.Diagnostics);
        gameInfo = new GameInfo(
            AppId: install.AppId,
            BuildId: install.BuildId,
            InstallDir: install.InstallDirectory,
            SteamLibrary: install.SteamLibrary,
            GameVersion: DeriveGameVersion(pluginInfo?.ProductVersion));

        machine.TransitionTo(ReaderState.Detected);

        if (install.BuildId is null)
        {
            diagnostics.Add("appmanifest 缺少 buildid。");
            machine.TransitionTo(ReaderState.Unknown);
            return Build(ReaderState.Unknown, "已找到 FM27 安装，但安装清单缺少 buildid，无法确定构建版本，拒绝读取。");
        }

        var pluginVersion = pluginInfo?.ProductVersion;
        if (pluginVersion is null)
        {
            machine.TransitionTo(ReaderState.Unknown);
            return Build(ReaderState.Unknown, "已找到 FM27 安装，但无法读取 game_plugin.dll 的产品版本，拒绝读取。");
        }

        machine.TransitionTo(ReaderState.VersionIdentified);

        if (_compatibility is null)
        {
            machine.TransitionTo(ReaderState.Unknown);
            return Build(
                ReaderState.Unknown,
                $"兼容清单不可用，拒绝读取：{_compatibilityError ?? "未加载兼容清单"}");
        }

        var compatibility = _compatibility.Evaluate(
            new CompatibilityInput(install.AppId, install.BuildId, pluginVersion));

        var next = MapCompatibilityStatus(compatibility.Status);

        machine.TransitionTo(next);
        return Build(next, compatibility.Reason, compatibility);
    }

    private static string? DeriveGameVersion(string? pluginProductVersion)
    {
        if (string.IsNullOrWhiteSpace(pluginProductVersion))
        {
            return null;
        }

        var plusIndex = pluginProductVersion.IndexOf('+', StringComparison.Ordinal);
        var version = plusIndex > 0 ? pluginProductVersion[..plusIndex] : pluginProductVersion;
        return string.IsNullOrWhiteSpace(version) ? null : version.Trim();
    }
}
