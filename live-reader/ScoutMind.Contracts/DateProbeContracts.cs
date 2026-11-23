namespace ScoutMind.Contracts;

/// <summary>Result state for the lightweight game-date probe.</summary>
public enum FmDateProbeState
{
    GameNotRunning,
    UnsupportedBuild,
    LayoutNotVerified,
    DateUnavailable,
    DateDetected,
    ProbeFailed,
}

/// <summary>Lightweight date probe result; never fabricates a date.</summary>
public sealed record FmDateProbeResult(
    FmDateProbeState State,
    DateTimeOffset ProbedAt,
    string? GameDate,
    string? Build,
    string? PluginVersion,
    string? LayoutVersion,
    string? ErrorCode,
    IReadOnlyList<string> Diagnostics);
