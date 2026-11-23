using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>Exclusive agent lock; the OS releases the handle if the process crashes.</summary>
public sealed class CaptureLock : IDisposable
{
    private readonly FileStream _stream;

    private CaptureLock(FileStream stream) => _stream = stream;

    public static CaptureLock? TryAcquire(string queueRoot, out string message)
    {
        var path = System.IO.Path.Combine(System.IO.Path.GetFullPath(queueRoot), "agent.lock");
        try
        {
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
            var stream = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            using var writer = new StreamWriter(stream, leaveOpen: true);
            writer.Write($"{Environment.ProcessId} {DateTimeOffset.UtcNow:O}");
            writer.Flush();
            message = "已获取自动采集锁。";
            return new CaptureLock(stream);
        }
        catch (IOException)
        {
            message = "另一个 Agent 正在运行（agent.lock 被占用）。";
            return null;
        }
    }

    public void Dispose() => _stream.Dispose();
}

/// <summary>Pause/resume control file shared by the running auto agent and CLI commands.</summary>
public static class CaptureControl
{
    private sealed record State(string Status);

    private static string PathFor(string queueRoot) =>
        System.IO.Path.Combine(System.IO.Path.GetFullPath(queueRoot), "capture-control.json");

    public static bool IsPaused(string queueRoot)
    {
        var path = PathFor(queueRoot);
        if (!File.Exists(path)) return false;
        try
        {
            return JsonSerializer.Deserialize<State>(File.ReadAllText(path))?.Status == "paused";
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public static void Set(string queueRoot, string status)
    {
        var path = PathFor(queueRoot);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(new State(status)));
    }

    public static string Status(string queueRoot) => IsPaused(queueRoot) ? "paused" : "running";
}
