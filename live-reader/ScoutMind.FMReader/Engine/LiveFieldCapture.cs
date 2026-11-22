using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Engine;

/// <summary>Live raw field sample from the running game (no expected UI value yet).</summary>
public sealed record LiveCaptureSample(
    string FieldId,
    string ObjectType,
    string PlayerUid,
    string? PlayerName,
    string RawValue,
    string? DecodedValue);

/// <summary>Result of a live capture; Expected values must be supplied by the operator.</summary>
public sealed record LiveCaptureResult(
    string GameBuild,
    string PluginVersion,
    string LayoutVersion,
    string ObservedAt,
    IReadOnlyList<LiveCaptureSample> Samples,
    IReadOnlyList<string> Diagnostics);
