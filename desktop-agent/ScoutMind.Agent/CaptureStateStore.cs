using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>Persistent auto-capture state; survives agent restarts without pretending a scan completed.</summary>
public sealed record CaptureState(
    string? SaveName,
    string? LastGameDate,
    string? LastScanId,
    string Status,
    int ConsecutiveFailures,
    DateTimeOffset? UpdatedAt);

/// <summary>JSON state file stored beside the scan queue (atomic replace).</summary>
public sealed class CaptureStateStore
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    private readonly string _path;

    public CaptureStateStore(string queueRoot)
    {
        _path = System.IO.Path.Combine(System.IO.Path.GetFullPath(queueRoot), "capture-state.json");
    }

    public string Path => _path;

    public CaptureState Load()
    {
        if (!File.Exists(_path))
        {
            return new CaptureState(null, null, null, "idle", 0, null);
        }

        try
        {
            return JsonSerializer.Deserialize<CaptureState>(File.ReadAllText(_path), Options)
                ?? new CaptureState(null, null, null, "idle", 0, null);
        }
        catch (JsonException)
        {
            return new CaptureState(null, null, null, "idle", 0, null);
        }
    }

    public void Save(CaptureState state)
    {
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(_path)!);
        var temporary = _path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(state with { UpdatedAt = DateTimeOffset.UtcNow }, Options));
        File.Move(temporary, _path, overwrite: true);
    }
}
