using System.ComponentModel;
using System.Diagnostics;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 被接受的 FM27 进程。只有通过文件名校验的进程才会生成该对象，避免把同名进程误判为游戏。
/// </summary>
/// <param name="Pid">进程 ID。</param>
/// <param name="ProcessName">进程名（不含扩展名）。</param>
/// <param name="ExecutablePath">主模块完整路径。</param>
/// <param name="ProductName">版本资源中的产品名。</param>
/// <param name="FileVersion">文件版本。</param>
/// <param name="ProductVersion">产品版本。</param>
public sealed record DetectedProcess(
    int Pid,
    string ProcessName,
    string ExecutablePath,
    string? ProductName,
    string? FileVersion,
    string? ProductVersion)
{
    /// <summary>转换为线上契约对象，供 <c>status --json</c> 输出。</summary>
    /// <returns>对应的 <see cref="ProcessInfo"/>。</returns>
    public ProcessInfo ToContract() =>
        new(Pid, ProcessName, ExecutablePath, ProductName, FileVersion, ProductVersion);
}

/// <summary>
/// 枚举本机进程并识别 FM27。识别条件是「主模块文件名必须是 fm.exe」，
/// 并在版本可读时要求 <c>ProductName</c> 含 "Football Manager"；任一条件不满足就跳过并记录诊断。
/// </summary>
public sealed class ProcessDetector
{
    private static readonly string[] CandidateNames = { "fm", "FootballManager" };
    private const string GameExecutableName = "fm.exe";

    private readonly List<string> _diagnostics = new();

    /// <summary>最近一次 <see cref="Detect"/> 产生的诊断信息。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <summary>查找第一个符合 FM27 特征的进程。</summary>
    /// <returns>找到的进程；未运行时返回 <c>null</c>。</returns>
    public DetectedProcess? Detect()
    {
        _diagnostics.Clear();
        foreach (var name in CandidateNames)
        {
            Process[] processes;
            try
            {
                processes = Process.GetProcessesByName(name);
            }
            catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or NotSupportedException)
            {
                _diagnostics.Add($"枚举进程 \"{name}\" 失败：{ex.Message}");
                continue;
            }

            try
            {
                foreach (var process in processes)
                {
                    var detected = TryDescribe(process);
                    if (detected is not null)
                    {
                        return detected;
                    }
                }
            }
            finally
            {
                foreach (var process in processes)
                {
                    process.Dispose();
                }
            }
        }

        return null;
    }

    private DetectedProcess? TryDescribe(Process process)
    {
        int pid;
        try
        {
            pid = process.Id;
        }
        catch (InvalidOperationException ex)
        {
            _diagnostics.Add($"进程已退出，无法读取 ID：{ex.Message}");
            return null;
        }

        string? executablePath = null;
        try
        {
            executablePath = process.MainModule?.FileName;
        }
        catch (Win32Exception ex)
        {
            _diagnostics.Add($"无法读取进程 {pid} 的主模块：{ex.Message}（可能权限不足或进程已退出）。");
        }
        catch (InvalidOperationException ex)
        {
            _diagnostics.Add($"无法读取进程 {pid} 的主模块：{ex.Message}");
        }
        catch (NotSupportedException ex)
        {
            _diagnostics.Add($"无法读取进程 {pid} 的主模块：{ex.Message}");
        }

        if (string.IsNullOrWhiteSpace(executablePath))
        {
            _diagnostics.Add($"进程 {pid}（{SafeProcessName(process)}）的主模块路径不可读，已跳过以避免误判。");
            return null;
        }

        if (!Path.GetFileName(executablePath).Equals(GameExecutableName, StringComparison.OrdinalIgnoreCase))
        {
            _diagnostics.Add($"进程 {pid} 的可执行文件不是 {GameExecutableName}（实际 {executablePath}），已跳过。");
            return null;
        }

        FileVersionInfo? version = null;
        try
        {
            version = FileVersionInfo.GetVersionInfo(executablePath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            _diagnostics.Add($"读取 {executablePath} 的版本资源失败：{ex.Message}");
        }

        var productName = string.IsNullOrWhiteSpace(version?.ProductName) ? null : version.ProductName;
        if (productName is not null && !productName.Contains("Football Manager", StringComparison.OrdinalIgnoreCase))
        {
            _diagnostics.Add($"进程 {pid} 的产品名为 \"{productName}\"，不包含 \"Football Manager\"，已跳过。");
            return null;
        }

        return new DetectedProcess(
            Pid: pid,
            ProcessName: SafeProcessName(process),
            ExecutablePath: executablePath,
            ProductName: productName,
            FileVersion: string.IsNullOrWhiteSpace(version?.FileVersion) ? null : version.FileVersion,
            ProductVersion: string.IsNullOrWhiteSpace(version?.ProductVersion) ? null : version.ProductVersion);
    }

    private string SafeProcessName(Process process)
    {
        try
        {
            return process.ProcessName;
        }
        catch (InvalidOperationException ex)
        {
            _diagnostics.Add($"读取进程名失败：{ex.Message}");
            return "unknown";
        }
    }
}
