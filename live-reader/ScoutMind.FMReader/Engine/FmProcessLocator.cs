using System.Diagnostics;
using System.Security;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次进程定位的结果。</summary>
/// <param name="ProcessId">fm.exe 进程号。</param>
/// <param name="ProcessPath">可执行文件路径。</param>
/// <param name="InstallDirectory">包含 <c>fm_Data</c> 的安装目录。</param>
/// <param name="Diagnostics">诊断信息。</param>
/// <param name="ProcessStartTime">进程启动时间；读不到时为 <c>null</c>。只用于会话，不作存档身份。</param>
public sealed record FmProcessLocation(
    int? ProcessId,
    string? ProcessPath,
    string? InstallDirectory,
    IReadOnlyList<string> Diagnostics,
    DateTime? ProcessStartTime = null);

/// <summary>进程的只读描述，便于在没有真实游戏的机器上测试定位逻辑。</summary>
/// <param name="ProcessId">进程号。</param>
/// <param name="Name">进程名（不带 .exe）。</param>
/// <param name="MainModulePath">主模块路径；无权读取时为 <c>null</c>。</param>
/// <param name="StartedAt">启动时间。</param>
public sealed record FmProcessDescriptor(int ProcessId, string Name, string? MainModulePath, DateTime StartedAt);

/// <summary>定位 fm.exe。只读进程元数据与文件，不接触游戏内存。</summary>
public interface IFmProcessLocator
{
    /// <summary>定位当前运行的 FM。</summary>
    /// <returns>定位结果；未运行或无权访问时对应字段为 <c>null</c>。</returns>
    FmProcessLocation Locate();
}

/// <summary>
/// 默认的进程定位：找名为 <c>fm</c> 且旁边存在 <c>fm_Data</c> 的进程，多个时取最近启动的那个。
/// 打不开（elevated）的进程单独记录诊断，便于给出"FM 以管理员运行"的准确提示。
/// </summary>
public sealed class FmProcessLocator : IFmProcessLocator
{
    /// <summary>FM27 的 Steam AppId。</summary>
    public const string Fm27AppId = "4530370";

    private readonly Func<IEnumerable<FmProcessDescriptor>> _processSource;

    /// <summary>使用真实进程表。</summary>
    public FmProcessLocator()
        : this(static () => Process.GetProcesses().Select(Describe))
    {
    }

    /// <summary>测试注入进程描述表（避免依赖真实进程）。</summary>
    /// <param name="processSource">进程描述枚举器。</param>
    public FmProcessLocator(Func<IEnumerable<FmProcessDescriptor>> processSource)
    {
        _processSource = processSource ?? throw new ArgumentNullException(nameof(processSource));
    }

    /// <inheritdoc />
    public FmProcessLocation Locate()
    {
        var diagnostics = new List<string>();
        var candidates = new List<(FmProcessDescriptor Process, string InstallDirectory)>();

        foreach (var process in SafeProcesses())
        {
            if (!string.Equals(process.Name, "fm", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (string.IsNullOrWhiteSpace(process.MainModulePath))
            {
                diagnostics.Add($"进程 {process.ProcessId} 名为 fm，但读不到主模块路径（可能权限不足）。");
                continue;
            }

            var installDirectory = Path.GetDirectoryName(process.MainModulePath);
            if (installDirectory is null || !Directory.Exists(Path.Combine(installDirectory, "fm_Data")))
            {
                diagnostics.Add($"进程 {process.ProcessId} 的路径 {process.MainModulePath} 旁边没有 fm_Data，按非 FM27 处理。");
                continue;
            }

            candidates.Add((process, installDirectory));
        }

        if (candidates.Count == 0)
        {
            diagnostics.Add("没有找到正在运行且带 fm_Data 的 fm.exe。");
            return new FmProcessLocation(null, null, null, diagnostics);
        }

        var chosen = candidates.OrderByDescending(item => item.Process.StartedAt).First();
        diagnostics.Add($"选中 fm.exe pid {chosen.Process.ProcessId}，安装目录 {chosen.InstallDirectory}。");
        return new FmProcessLocation(
            chosen.Process.ProcessId,
            chosen.Process.MainModulePath,
            chosen.InstallDirectory,
            diagnostics,
            chosen.Process.StartedAt == DateTime.MinValue ? null : chosen.Process.StartedAt);
    }

    /// <summary>读取插件路径与文件版本（不打开游戏进程）。</summary>
    /// <param name="installDirectory">安装目录。</param>
    /// <returns>插件路径与版本；缺失时字段为 <c>null</c>。</returns>
    public static (string? Path, string? Version) ReadPlugin(string? installDirectory)
    {
        if (string.IsNullOrWhiteSpace(installDirectory))
        {
            return (null, null);
        }

        var path = Path.Combine(installDirectory, "fm_Data", "Plugins", "x86_64", "game_plugin.dll");
        if (!File.Exists(path))
        {
            return (path, null);
        }

        var info = FileVersionInfo.GetVersionInfo(path);
        var text = string.IsNullOrWhiteSpace(info.FileVersion) ? info.ProductVersion : info.FileVersion;
        return (path, string.IsNullOrWhiteSpace(text) ? null : text.Trim());
    }

    /// <summary>读取 AppId：优先 steam_appid.txt，其次按安装目录名判断。</summary>
    /// <param name="installDirectory">安装目录。</param>
    /// <returns>AppId；无法确定时为 <c>null</c>。</returns>
    public static string? ReadAppId(string? installDirectory)
    {
        if (string.IsNullOrWhiteSpace(installDirectory))
        {
            return null;
        }

        try
        {
            var candidate = Path.Combine(installDirectory, "steam_appid.txt");
            if (File.Exists(candidate))
            {
                var text = File.ReadAllText(candidate).Trim();
                if (text.Length > 0)
                {
                    return text;
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or SecurityException)
        {
            // 读不到就按目录名判断。
        }

        return installDirectory.Contains("Football Manager 27", StringComparison.OrdinalIgnoreCase)
            ? Fm27AppId
            : null;
    }

    private static FmProcessDescriptor Describe(Process process)
    {
        string? path = null;
        DateTime startedAt = DateTime.MinValue;
        string name = string.Empty;

        try
        {
            path = process.MainModule?.FileName;
            startedAt = process.StartTime;
        }
        catch (Exception ex) when (ex is InvalidOperationException or NotSupportedException or System.ComponentModel.Win32Exception)
        {
            // 读不到就留空：定位逻辑会把"没有路径"当作不可用并记录诊断。
        }

        try
        {
            name = process.ProcessName;
        }
        catch (InvalidOperationException)
        {
            name = string.Empty;
        }

        return new FmProcessDescriptor(process.Id, name, path, startedAt);
    }

    private IEnumerable<FmProcessDescriptor> SafeProcesses()
    {
        try
        {
            return _processSource().ToList();
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            return Array.Empty<FmProcessDescriptor>();
        }
    }
}
