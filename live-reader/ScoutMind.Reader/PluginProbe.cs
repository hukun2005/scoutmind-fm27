using System.Diagnostics;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 读取安装目录中 <c>game_plugin.dll</c> 的版本资源。只读文件头，绝不加载该 DLL，
/// 因此不存在执行第三方代码的风险。
/// </summary>
public sealed class PluginProbe
{
    /// <summary>插件文件名，位于游戏安装目录根部。</summary>
    public const string PluginFileName = "game_plugin.dll";

    /// <summary>
    /// 插件的候选相对路径，按顺序探测。第一项是协议规定的安装目录根部，
    /// 其余是 FM27 实际发布布局中出现过的位置（只读定位，不会加载 DLL）。
    /// </summary>
    private static readonly string[] CandidateRelativePaths =
    {
        PluginFileName,
        Path.Combine("fm_Data", "Plugins", "x86_64", PluginFileName),
        Path.Combine("fm_Data", "Plugins", PluginFileName),
        Path.Combine("Plugins", "x86_64", PluginFileName),
    };

    private readonly List<string> _diagnostics = new();

    /// <summary>最近一次 <see cref="Probe"/> 产生的诊断信息。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <summary>读取插件版本信息。</summary>
    /// <param name="installDirectory">游戏安装目录；为空时直接返回 <c>null</c>。</param>
    /// <returns>读取成功时返回插件信息；文件缺失或不可读时返回 <c>null</c>。</returns>
    public PluginInfo? Probe(string? installDirectory)
    {
        _diagnostics.Clear();
        if (string.IsNullOrWhiteSpace(installDirectory))
        {
            _diagnostics.Add("安装目录未知，无法读取 game_plugin.dll 版本。");
            return null;
        }

        var path = LocatePlugin(installDirectory);
        if (path is null)
        {
            var tried = string.Join("、", CandidateRelativePaths);
            _diagnostics.Add($"在 {installDirectory} 下未找到 {PluginFileName}（已尝试：{tried}）。");
            return null;
        }

        if (!path.Equals(Path.Combine(installDirectory, PluginFileName), StringComparison.OrdinalIgnoreCase))
        {
            _diagnostics.Add($"已按 FM27 实际布局定位插件：{path}");
        }

        try
        {
            var info = FileVersionInfo.GetVersionInfo(path);
            var productVersion = string.IsNullOrWhiteSpace(info.ProductVersion) ? null : info.ProductVersion;
            var fileVersion = string.IsNullOrWhiteSpace(info.FileVersion) ? null : info.FileVersion;
            if (productVersion is null)
            {
                _diagnostics.Add($"{PluginFileName} 未提供产品版本，无法做版本闸门校验：{path}");
            }

            return new PluginInfo(path, productVersion, fileVersion);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            _diagnostics.Add($"读取 {path} 的版本资源失败：{ex.Message}");
            return null;
        }
    }

    private static string? LocatePlugin(string installDirectory)
    {
        foreach (var relativePath in CandidateRelativePaths)
        {
            var candidate = Path.Combine(installDirectory, relativePath);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }
}
