using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一次诊断的完整输出。</summary>
/// <param name="Report">诊断报告。</param>
/// <param name="State">更新后的持久化状态（由调用方保存）。</param>
public sealed record WorldDateDiagnosticsOutcome(
    WorldDateDiagnosticsReport Report,
    DateVerificationState State);

/// <summary>
/// 世界日期诊断编排：采集 → 追踪判定 → 安全门。
///
/// 它不隐藏任何候选：所有结构命中都会出现在 <c>candidates</c> 或 <c>rejected_candidates</c> 中，
/// 并带有类别、排除原因与证据说明。
/// </summary>
public static class WorldDateDiagnostics
{
    /// <summary>诊断限制（不依赖真实游戏时也必须显式说明）。</summary>
    public const string RealGameLimitation = "本轮结果没有包含真实 FM27 的双重启验证证据。";

    /// <summary>存档身份限制。</summary>
    public const string SaveIdentityLimitation = "存档身份识别尚未实现：安全门因此保持 BLOCKED。";

    /// <summary>执行诊断。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="session">进程会话。</param>
    /// <param name="operatorVisibleDate">人工观察到的界面日期。</param>
    /// <param name="saveKey">存档身份；未知为 <c>null</c>。</param>
    /// <param name="previousState">上一次持久化状态。</param>
    /// <param name="maxBytes">扫描预算。</param>
    /// <param name="hints">对象类型提示。</param>
    /// <param name="readerVersionSupported">Reader 构建是否受支持。</param>
    /// <param name="processSessionValid">进程会话是否有效。</param>
    /// <param name="now">当前时间。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <param name="moduleRegions">模块区域；提供时为候选建立模块静态引用链。</param>
    /// <returns>诊断输出。</returns>
    public static WorldDateDiagnosticsOutcome Analyze(
        IMemorySource memory,
        ProcessSessionIdentity session,
        DateOnly? operatorVisibleDate,
        string? saveKey,
        DateVerificationState previousState,
        long maxBytes = WorldDateLocator.DefaultMaxBytes,
        IReadOnlyList<DateObjectHint>? hints = null,
        bool readerVersionSupported = false,
        bool processSessionValid = true,
        DateTimeOffset? now = null,
        CancellationToken cancellationToken = default,
        IReadOnlyList<ModuleRegion>? moduleRegions = null)
    {
        ArgumentNullException.ThrowIfNull(memory);
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(previousState);

        var collection = WorldDateCandidateCollector.Collect(
            memory, maxBytes, hints, budget: null, cancellationToken, moduleRegions);
        var tracked = DateCandidateTracker.Observe(
            session, saveKey, operatorVisibleDate, collection, previousState, now ?? DateTimeOffset.UtcNow);

        var limitations = tracked.Limitations.ToList();
        limitations.Add(SaveIdentityLimitation);
        limitations.Add(RealGameLimitation);
        if (collection.Truncated)
        {
            limitations.Add("扫描预算不足，可能有候选未纳入本轮诊断。");
        }

        if (collection.Observations.Any(item => item.ReferenceChain is not null))
        {
            limitations.Add("引用链只证明该记录可由模块静态数据可达，不能单独证明它就是当前世界日期。");
        }

        var gate = SnapshotSafetyGate.Evaluate(new SnapshotSafetyInput(
            DateAvailable: tracked.SelectedDate is not null,
            CandidateUnambiguous: tracked.SelectedDate is not null && tracked.Status is "session_verified" or "restart_verified" or "heuristic",
            Confidence: tracked.Confidence,
            ProcessSessionValid: processSessionValid && session.ProcessId is not null,
            SaveIdentityValid: false,
            ReaderVersionSupported: readerVersionSupported,
            DateSourceValid: tracked.SelectedSignature is not null));

        var diagnostics = collection.Evidences
            .Concat(tracked.Evidence)
            .ToList();

        var report = new WorldDateDiagnosticsReport(
            Status: tracked.Status,
            Confidence: tracked.Confidence,
            Process: new ProcessDiagnostics(
                session.ProcessId,
                session.ProcessStartTime,
                session.ModuleBase == 0 ? null : CandidateIdentity.Hex(session.ModuleBase),
                session.Build,
                session.PluginVersion,
                session.SessionKey),
            Session: new SessionDiagnostics(session.SessionKey, session.Build, saveKey),
            DateSummary: new SelectedDateSummary(
                tracked.SelectedDate,
                tracked.Candidates.Count,
                tracked.Candidates.Count(item => item.Confidence >= DateConfidenceLevel.SessionVerified),
                tracked.RejectedCandidates.Count),
            Candidates: tracked.Candidates,
            RejectedCandidates: tracked.RejectedCandidates,
            SelectionReason: tracked.SelectionReason,
            VerificationEvidence: previousState.Evidence
                .TakeLast(10)
                .Select(item => $"{item.At} [{item.Kind}] {item.Detail}")
                .Concat(tracked.Evidence)
                .ToList(),
            Limitations: limitations,
            Snapshot: gate,
            NextAction: NextAction(tracked.Status, tracked.SelectedDate, tracked.DateChanged, tracked.DateRolledBack),
            Diagnostics: diagnostics);

        return new WorldDateDiagnosticsOutcome(report, tracked.State);
    }

    /// <summary>构造“不可用”报告（进程未运行、构建不支持、内存不可读等）。</summary>
    /// <param name="status">状态。</param>
    /// <param name="session">进程会话。</param>
    /// <param name="reason">原因。</param>
    /// <param name="diagnostics">诊断行。</param>
    /// <returns>报告。</returns>
    public static WorldDateDiagnosticsReport Unavailable(
        string status,
        ProcessSessionIdentity session,
        string reason,
        IReadOnlyList<string>? diagnostics = null)
    {
        var gate = SnapshotSafetyGate.Evaluate(new SnapshotSafetyInput(
            DateAvailable: false,
            CandidateUnambiguous: false,
            Confidence: DateConfidenceLevel.Unavailable,
            ProcessSessionValid: false,
            SaveIdentityValid: false,
            ReaderVersionSupported: false,
            DateSourceValid: false));

        return new WorldDateDiagnosticsReport(
            Status: status,
            Confidence: DateConfidenceLevel.Unavailable,
            Process: new ProcessDiagnostics(
                session.ProcessId,
                session.ProcessStartTime,
                session.ModuleBase == 0 ? null : CandidateIdentity.Hex(session.ModuleBase),
                session.Build,
                session.PluginVersion,
                session.SessionKey),
            Session: new SessionDiagnostics(session.SessionKey, session.Build, null),
            DateSummary: new SelectedDateSummary(null, 0, 0, 0),
            Candidates: Array.Empty<DateCandidateDiagnostics>(),
            RejectedCandidates: Array.Empty<DateCandidateDiagnostics>(),
            SelectionReason: reason,
            VerificationEvidence: Array.Empty<string>(),
            Limitations: new[] { SaveIdentityLimitation, RealGameLimitation },
            Snapshot: gate,
            NextAction: "未找到可用日期：请确认游戏进程、构建号与插件版本。",
            Diagnostics: diagnostics ?? Array.Empty<string>());
    }

    private static string NextAction(string status, string? selectedDate, bool dateChanged, bool rolledBack) => status switch
    {
        "restart_verified" => "日期已跨进程验证；仍需补齐存档身份验证后，自动快照才可能开放。",
        "session_verified" => dateChanged
            ? "界面日期已变化且验证通过：请重启游戏后再次执行同一验证，积累跨进程证据。"
            : "本次会话验证通过：请在游戏内推进会日期并重启游戏后再次验证。",
        "heuristic" => selectedDate is null
            ? "没有可用日期：请确认游戏进程、构建号与插件版本后重新诊断。"
            : "当前只是启发式日期：请在游戏界面读取世界日期，并用 --verify 重新运行；在此之前不要依赖该日期。",
        "verification_mismatch" => "界面日期与内存候选不一致：请确认游戏界面日期、存档与进程，然后重新采集。",
        "date_rollback" => rolledBack
            ? "检测到界面日期倒退：请确认是否读档回滚，并重新验证。"
            : "检测到日期异常：请重新验证。",
        "ambiguous" => "存在无法区分的候选：需要对象分类证据或人工界面日期确认。",
        "unstable" => "候选复读不一致：请停止游戏内时间推进后重新诊断。",
        _ => "未找到可用日期：请确认游戏进程、构建号与插件版本。",
    };
}
