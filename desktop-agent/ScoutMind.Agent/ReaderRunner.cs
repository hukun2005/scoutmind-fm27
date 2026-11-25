using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace ScoutMind.Agent;

/// <summary>
/// 一次读取器调用的结果。
/// </summary>
/// <param name="ExitCode">读取器退出码；未能启动或超时时为 <c>-1</c>。</param>
/// <param name="Stdout">标准输出全文。</param>
/// <param name="Stderr">标准错误全文。</param>
/// <param name="TimedOut">是否因超时被终止。</param>
/// <param name="StartError">启动失败原因；成功启动时为 <c>null</c>。</param>
public sealed record ReaderInvocation(
    int ExitCode,
    string Stdout,
    string Stderr,
    bool TimedOut,
    string? StartError);

/// <summary>
/// 以子进程方式运行读取器 CLI。代理不直接读游戏内存，也不解析扫描器输出，
/// 只消费读取器写出的 JSON。
/// </summary>
public sealed class ReaderRunner
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private readonly string _readerPath;
    private readonly TimeSpan _timeout;

    /// <summary>
    /// 是否允许自动快照。只有 <c>auto</c> 路径会置为 <c>true</c>，并通过环境变量
    /// <c>SCOUTMIND_AUTOMATIC_SNAPSHOT=1</c> 传给读取器；读取器仍只对 <c>verified</c> 身份放行。
    /// </summary>
    public bool AutomaticSnapshot { get; set; }

    /// <summary>创建运行器。</summary>
    /// <param name="readerPath">读取器可执行文件或 .dll 的绝对路径。</param>
    /// <param name="timeout">单次调用的超时。</param>
    public ReaderRunner(string readerPath, TimeSpan timeout)
    {
        if (string.IsNullOrWhiteSpace(readerPath))
        {
            throw new ArgumentException("读取器路径不能为空。", nameof(readerPath));
        }

        _readerPath = Path.GetFullPath(readerPath);
        _timeout = timeout <= TimeSpan.Zero ? TimeSpan.FromMinutes(5) : timeout;
    }

    /// <summary>执行读取器命令。</summary>
    /// <param name="arguments">传给读取器的参数。</param>
    /// <param name="cancellationToken">取消令牌（Ctrl+C）。</param>
    /// <returns>调用结果；代理据此透传退出码与消息。</returns>
    public async Task<ReaderInvocation> RunAsync(IReadOnlyList<string> arguments, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(arguments);

        var (fileName, prefixArguments) = BuildInvocation(_readerPath);
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Utf8NoBom,
            StandardErrorEncoding = Utf8NoBom,
        };

        foreach (var argument in prefixArguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        if (AutomaticSnapshot)
        {
            startInfo.Environment["SCOUTMIND_AUTOMATIC_SNAPSHOT"] = "1";
        }

        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                return new ReaderInvocation(-1, string.Empty, string.Empty, false, "读取器进程未能启动。");
            }
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or PlatformNotSupportedException)
        {
            return new ReaderInvocation(-1, string.Empty, string.Empty, false, $"启动读取器失败：{ex.Message}");
        }

        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        using var registration = cancellationToken.Register(static state => TryKill((Process)state!), process);

        var exitTask = process.WaitForExitAsync(CancellationToken.None);
        var completed = await Task.WhenAny(exitTask, Task.Delay(_timeout, CancellationToken.None)).ConfigureAwait(false);
        var timedOut = completed != exitTask;
        if (timedOut)
        {
            TryKill(process);
        }

        try
        {
            await process.WaitForExitAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            // The reader ignored the tree kill; the caller still gets a failure instead of hanging.
        }

        var stdout = await stdoutTask.ConfigureAwait(false);
        var stderr = await stderrTask.ConfigureAwait(false);

        if (cancellationToken.IsCancellationRequested)
        {
            cancellationToken.ThrowIfCancellationRequested();
        }

        return new ReaderInvocation(timedOut ? -1 : process.ExitCode, stdout, stderr, timedOut, null);
    }

    private static (string FileName, List<string> PrefixArguments) BuildInvocation(string readerPath)
    {
        // A .dll is launched through the dotnet host, which keeps `dotnet run` development usable
        // without a published apphost next to the agent.
        if (readerPath.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
        {
            return ("dotnet", new List<string> { readerPath });
        }

        return (readerPath, new List<string>());
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception or NotSupportedException)
        {
            // The process already exited or cannot be signalled; the caller still reports a timeout.
        }
    }
}
