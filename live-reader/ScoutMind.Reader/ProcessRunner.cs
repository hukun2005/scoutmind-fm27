using System.ComponentModel;
using System.Diagnostics;
using System.Text;

namespace ScoutMind.Reader;

/// <summary>
/// 一次外部进程调用的请求。标准输出与标准错误直接落盘，避免把扫描结果整体读进内存。
/// </summary>
/// <param name="ExecutablePath">可执行文件绝对路径。</param>
/// <param name="Arguments">逐项参数，不经过 shell。</param>
/// <param name="WorkingDirectory">工作目录。</param>
/// <param name="StdoutPath">标准输出捕获文件路径。</param>
/// <param name="StderrPath">标准错误捕获文件路径。</param>
/// <param name="Timeout">超时；超时后终止整个进程树。</param>
public sealed record ProcessRunRequest(
    string ExecutablePath,
    IReadOnlyList<string> Arguments,
    string WorkingDirectory,
    string StdoutPath,
    string StderrPath,
    TimeSpan Timeout);

/// <summary>
/// 一次外部进程调用的结果。
/// </summary>
/// <param name="ExitCode">退出码；进程未能启动时为 <c>null</c>。</param>
/// <param name="TimedOut">是否因超时被终止。</param>
/// <param name="DurationMs">调用耗时（毫秒）。</param>
/// <param name="StartError">启动失败原因；成功启动时为 <c>null</c>。</param>
/// <param name="Note">非致命问题（例如输出捕获被取消、终止进程失败）。</param>
public sealed record ProcessRunResult(
    int? ExitCode,
    bool TimedOut,
    long DurationMs,
    string? StartError,
    string? Note)
{
    /// <summary>进程正常启动、未超时且退出码为 0。</summary>
    public bool Succeeded => StartError is null && !TimedOut && ExitCode == 0;
}

/// <summary>
/// 外部进程执行器抽象。测试用替身可以断言「是否真的启动了进程」，生产实现见 <see cref="SystemProcessRunner"/>。
/// </summary>
public interface IProcessRunner
{
    /// <summary>执行一次外部进程调用。</summary>
    /// <param name="request">调用请求。</param>
    /// <param name="cancellationToken">取消令牌；取消时终止进程树并抛出 <see cref="OperationCanceledException"/>。</param>
    /// <returns>调用结果。</returns>
    Task<ProcessRunResult> RunAsync(ProcessRunRequest request, CancellationToken cancellationToken);
}

/// <summary>
/// 基于 <see cref="Process"/> 的执行器：不经过 shell、不注入游戏进程、超时后终止整棵进程树。
/// </summary>
public sealed class SystemProcessRunner : IProcessRunner
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    /// <inheritdoc />
    public async Task<ProcessRunResult> RunAsync(ProcessRunRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        var stopwatch = Stopwatch.StartNew();
        var startInfo = new ProcessStartInfo
        {
            FileName = request.ExecutablePath,
            WorkingDirectory = request.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Utf8NoBom,
            StandardErrorEncoding = Utf8NoBom,
        };
        foreach (var argument in request.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };

        try
        {
            if (!process.Start())
            {
                return new ProcessRunResult(null, false, stopwatch.ElapsedMilliseconds, "扫描器进程未能启动。", null);
            }
        }
        catch (Exception ex) when (ex is Win32Exception or InvalidOperationException or PlatformNotSupportedException)
        {
            return new ProcessRunResult(null, false, stopwatch.ElapsedMilliseconds, $"启动扫描器失败：{ex.Message}", null);
        }

        EnsureParentDirectory(request.StdoutPath);
        EnsureParentDirectory(request.StderrPath);

        var stdoutTask = CopyToFileAsync(process.StandardOutput.BaseStream, request.StdoutPath, cancellationToken);
        var stderrTask = CopyToFileAsync(process.StandardError.BaseStream, request.StderrPath, cancellationToken);

        // Cancellation must not leave an orphaned scanner behind: kill the tree, then let the
        // wait complete before rethrowing.
        using var cancellationRegistration = cancellationToken.Register(
            static state => KillTreeQuietly((Process)state!),
            process);

        var exitTask = process.WaitForExitAsync(CancellationToken.None);
        var timeout = request.Timeout <= TimeSpan.Zero ? TimeSpan.FromDays(1) : request.Timeout;
        var timeoutTask = Task.Delay(timeout, CancellationToken.None);
        var completed = await Task.WhenAny(exitTask, timeoutTask).ConfigureAwait(false);

        var timedOut = completed != exitTask;
        string? note = null;
        if (timedOut)
        {
            note = KillTree(process);
            await ObserveExitAsync(process).ConfigureAwait(false);
        }
        else
        {
            await exitTask.ConfigureAwait(false);
        }

        var captureNote = await AwaitCopiesAsync(stdoutTask, stderrTask).ConfigureAwait(false);
        note = CombineNotes(note, captureNote);
        var duration = stopwatch.ElapsedMilliseconds;

        if (cancellationToken.IsCancellationRequested)
        {
            cancellationToken.ThrowIfCancellationRequested();
        }

        return new ProcessRunResult(timedOut ? null : process.ExitCode, timedOut, duration, null, note);
    }

    private static async Task CopyToFileAsync(Stream source, string path, CancellationToken cancellationToken)
    {
        await using var file = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.Read, 81920, useAsync: true);
        await source.CopyToAsync(file, cancellationToken).ConfigureAwait(false);
    }

    private static async Task<string?> AwaitCopiesAsync(params Task[] captureTasks)
    {
        try
        {
            await Task.WhenAll(captureTasks).ConfigureAwait(false);
            return null;
        }
        catch (OperationCanceledException)
        {
            return "输出捕获被取消，捕获文件可能不完整。";
        }
        catch (IOException ex)
        {
            return $"捕获扫描器输出失败：{ex.Message}";
        }
        catch (UnauthorizedAccessException ex)
        {
            return $"写入捕获文件失败：{ex.Message}";
        }
    }

    private static async Task ObserveExitAsync(Process process)
    {
        try
        {
            await process.WaitForExitAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            // The tree kill was issued; a scanner that ignores it still gets no further reads.
        }
    }

    private static void KillTreeQuietly(Process process)
    {
        // Cancellation path: the kill note is re-derived by the caller's timed-out branch.
        _ = KillTree(process);
    }

    private static string? KillTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }

            return null;
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception or NotSupportedException)
        {
            return $"终止扫描器进程树失败：{ex.Message}";
        }
    }

    private static void EnsureParentDirectory(string path)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
    }

    private static string? CombineNotes(string? first, string? second)
    {
        if (string.IsNullOrEmpty(first))
        {
            return string.IsNullOrEmpty(second) ? null : second;
        }

        return string.IsNullOrEmpty(second) ? first : $"{first} {second}";
    }
}
