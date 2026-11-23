using ScoutMind.Contracts;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>
/// Lightweight date probe contract. Implementations must not run a full dump and must not guess
/// offsets; when no verified date source exists they return DateUnavailable.
/// </summary>
public interface IFmDateProbe
{
    Task<FmDateProbeResult> ProbeAsync(CancellationToken cancellationToken);
}

/// <summary>
/// Version-gated date probe.
///
/// The current layout has no verified global game-date field (the upstream dump derives the date
/// from my-team schedule only after scanning the team graph). Therefore this implementation checks
/// process/build/layout and returns DateUnavailable instead of reading a guessed offset.
/// </summary>
public sealed class FmDateProbe : IFmDateProbe
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;
    private readonly LayoutResolver _layouts;

    public FmDateProbe(GameBuildDetector? detector = null, VersionGate? gate = null, LayoutResolver? layouts = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _gate = gate ?? new VersionGate();
        _layouts = layouts ?? new LayoutResolver();
    }

    public Task<FmDateProbeResult> ProbeAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var now = DateTimeOffset.UtcNow;
        var detected = _detector.Detect();
        if (detected.ProcessId is null)
        {
            return Task.FromResult(Result(FmDateProbeState.GameNotRunning, now, detected, null,
                "FM27 进程未运行。"));
        }

        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            return Task.FromResult(Result(FmDateProbeState.UnsupportedBuild, now, detected, gate.Layout,
                gate.Message));
        }

        var layout = _layouts.Resolve(detected.Build, detected.PluginVersion);
        if (layout is null || !LayoutResolver.IsRegistered(detected.Build))
        {
            return Task.FromResult(Result(FmDateProbeState.LayoutNotVerified, now, detected, gate.Layout,
                "当前构建没有可用布局，拒绝读取日期。"));
        }

        // No verified lightweight date offset exists. Return an explicit unavailable state; a full
        // scan/date-derived fallback is the caller's decision and must be labelled.
        return Task.FromResult(Result(
            FmDateProbeState.DateUnavailable,
            now,
            detected,
            layout.Name,
            "当前布局没有经过验证的轻量游戏日期字段；未读取完整存档，拒绝猜测偏移。",
            "date_offset_not_verified"));
    }

    private static FmDateProbeResult Result(
        FmDateProbeState state,
        DateTimeOffset now,
        DetectedGame detected,
        string? layout,
        string message,
        string? errorCode = null)
    {
        var diagnostics = new List<string>(detected.Diagnostics) { message };
        return new FmDateProbeResult(
            state, now, null, detected.Build, detected.PluginVersion, layout, errorCode, diagnostics);
    }
}
