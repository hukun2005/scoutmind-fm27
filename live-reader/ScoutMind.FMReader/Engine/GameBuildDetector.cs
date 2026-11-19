using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次游戏版本检测的结果。</summary>
/// <param name="ProcessId">fm.exe 进程号；未运行为 <c>null</c>。</param>
/// <param name="ProcessPath">可执行文件路径。</param>
/// <param name="InstallDirectory">安装目录。</param>
/// <param name="AppId">Steam AppId。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginPath">game_plugin.dll 路径。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="Diagnostics">诊断信息。</param>
public sealed record DetectedGame(
    int? ProcessId,
    string? ProcessPath,
    string? InstallDirectory,
    string? AppId,
    string? Build,
    string? PluginPath,
    string? PluginVersion,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 游戏与构建识别：进程 → 安装目录（进程不在时回落到 Steam 库）→ 插件版本 → Steam 构建号。
/// 只读文件与进程元数据，不接触游戏内存。
/// </summary>
public sealed class GameBuildDetector
{
    private readonly IFmProcessLocator _locator;
    private readonly Func<GameIdentity, string?> _buildResolver;

    /// <summary>创建检测器。</summary>
    /// <param name="locator">进程定位器。</param>
    /// <param name="buildResolver">构建号解析（默认读 Steam appmanifest）。</param>
    public GameBuildDetector(IFmProcessLocator? locator = null, Func<GameIdentity, string?>? buildResolver = null)
    {
        _locator = locator ?? new FmProcessLocator();
        _buildResolver = buildResolver ?? SteamBuildResolver.Resolve;
    }

    /// <summary>执行检测。</summary>
    /// <returns>检测结果。</returns>
    public DetectedGame Detect()
    {
        var location = _locator.Locate();
        var diagnostics = new List<string>(location.Diagnostics);

        var installDirectory = location.InstallDirectory;
        if (installDirectory is null)
        {
            installDirectory = SteamBuildResolver.FindInstallDirectory();
            if (installDirectory is not null)
            {
                diagnostics.Add($"进程未运行，但按 Steam 库定位到安装目录：{installDirectory}。");
            }
        }

        var (pluginPath, pluginVersion) = FmProcessLocator.ReadPlugin(installDirectory);
        var appId = FmProcessLocator.ReadAppId(installDirectory);
        var identity = new GameIdentity(Version: null, Build: null, AppId: appId);
        var build = _buildResolver(identity);
        if (build is null)
        {
            diagnostics.Add("没有读到 Steam 构建号（appmanifest 缺失或被跳过）。");
        }

        return new DetectedGame(
            ProcessId: location.ProcessId,
            ProcessPath: location.ProcessPath,
            InstallDirectory: installDirectory,
            AppId: appId,
            Build: build,
            PluginPath: pluginPath,
            PluginVersion: pluginVersion,
            Diagnostics: diagnostics);
    }
}

/// <summary>Steam 安装路径与构建号解析（也用于"游戏没启动"时定位安装目录）。</summary>
public static partial class SteamPaths
{
    /// <summary>按 Steam 库目录查找 FM27 安装目录。</summary>
    /// <returns>安装目录或 <c>null</c>。</returns>
    public static string? FindFm27Install() => SteamBuildResolver.FindInstallDirectory();

    /// <summary>列出 Steam 库根目录（诊断用）。</summary>
    /// <returns>库根目录。</returns>
    public static IReadOnlyList<string> Libraries() => SteamBuildResolver.SteamLibraryRootsPublic();
}
