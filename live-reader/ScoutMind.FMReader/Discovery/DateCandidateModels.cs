namespace ScoutMind.FMReader.Discovery;

/// <summary>
/// 日期候选的语义分类。只有在存在可解释证据（对象类型提示、与人工确认日期的关系）时才给出具体类别；
/// 证据不足一律 <see cref="UnknownDate"/>，绝不只按日期值大小猜测。
/// </summary>
public enum DateCandidateKind
{
    /// <summary>当前世界日期（只有被人工界面日期确认过的候选才允许）。</summary>
    CurrentWorldDate,

    /// <summary>比赛相关日期。</summary>
    MatchDate,

    /// <summary>转会相关日期。</summary>
    TransferDate,

    /// <summary>新闻/媒体日期。</summary>
    NewsDate,

    /// <summary>日历/赛程日期。</summary>
    CalendarDate,

    /// <summary>历史记录日期。</summary>
    HistoryDate,

    /// <summary>无法判定类型。</summary>
    UnknownDate,
}

/// <summary>候选被排除的原因。每个被排除的候选都必须写明原因，禁止静默丢弃。</summary>
public enum DateRejectionReason
{
    /// <summary>未排除。</summary>
    None,

    /// <summary>原始值无法解码为合法 FM 日期。</summary>
    InvalidDate,

    /// <summary>解码日期或参考日期间隔超出支持范围。</summary>
    OutOfSupportedRange,

    /// <summary>属于比赛对象。</summary>
    MatchObject,

    /// <summary>属于转会对象。</summary>
    TransferObject,

    /// <summary>属于日历/赛程对象。</summary>
    CalendarObject,

    /// <summary>属于新闻对象。</summary>
    NewsObject,

    /// <summary>日期晚于已确认的当前日期（未来事件）。</summary>
    FutureEvent,

    /// <summary>复读值不一致。</summary>
    UnstableValue,

    /// <summary>引用关系无法解析。</summary>
    UnresolvedReference,

    /// <summary>与其它候选逻辑签名重复，无法唯一确定。</summary>
    DuplicateSignature,

    /// <summary>证据不足（结构合理但不能证明是当前日期）。</summary>
    InsufficientEvidence,
}

/// <summary>日期可信度等级。只能逐级提升，任何硬性条件失败都会停留在较低等级。</summary>
public enum DateConfidenceLevel
{
    /// <summary>没有可用日期。</summary>
    Unavailable,

    /// <summary>发现候选，但没有足够证据做任何选择。</summary>
    Discovered,

    /// <summary>候选合理（结构 + 最新 + 稳定），但仍属启发式。</summary>
    Heuristic,

    /// <summary>等待真实界面日期验证。</summary>
    VerificationPending,

    /// <summary>在本游戏进程/会话内完成界面日期验证。</summary>
    SessionVerified,

    /// <summary>跨游戏进程重启后仍重新定位并验证通过。</summary>
    RestartVerified,
}

/// <summary>候选对象类型提示：由对象分类器给出，用于把日期候选归到比赛/转会/新闻等对象。</summary>
/// <param name="ObjectAddress">对象起始地址。</param>
/// <param name="Window">对象窗口大小。</param>
/// <param name="Kind">对象对应的日期类别。</param>
/// <param name="Description">证据说明。</param>
public sealed record DateObjectHint(
    ulong ObjectAddress,
    int Window,
    DateCandidateKind Kind,
    string Description);

/// <summary>
/// 一次世界日期诊断中的进程身份。`SessionKey` 只由 PID + 进程启动时间 + 构建号构成，
/// 用于区分“同一个进程里的多次读取”和“游戏重启后的新进程”。
/// </summary>
/// <param name="SessionKey">进程会话键；未知时为确定性的 <c>unknown</c>。</param>
/// <param name="ProcessId">进程 ID。</param>
/// <param name="ProcessStartTime">进程启动时间（ISO 8601，UTC）。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="ModuleBase">game_plugin.dll 基址（0 表示未解析）。</param>
public sealed record ProcessSessionIdentity(
    string SessionKey,
    int? ProcessId,
    string? ProcessStartTime,
    string? Build,
    string? PluginVersion,
    ulong ModuleBase);

/// <summary>诊断报告里的进程信息。</summary>
/// <param name="Pid">进程 ID。</param>
/// <param name="ProcessStartTime">进程启动时间。</param>
/// <param name="ModuleBase">模块基址（十六进制字符串）。</param>
/// <param name="Build">游戏构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="SessionKey">进程会话键。</param>
public sealed record ProcessDiagnostics(
    int? Pid,
    string? ProcessStartTime,
    string? ModuleBase,
    string? Build,
    string? PluginVersion,
    string? SessionKey);

/// <summary>诊断报告里的会话信息。存档身份未实现时 <see cref="SaveKey"/> 为 <c>null</c>。</summary>
/// <param name="SessionId">会话 ID（等于进程会话键）。</param>
/// <param name="GameVersion">游戏版本（构建号）。</param>
/// <param name="SaveKey">存档身份；未知为 <c>null</c>。</param>
public sealed record SessionDiagnostics(string? SessionId, string? GameVersion, string? SaveKey);

/// <summary>一个候选的完整诊断，字段与任务书 5.2 对齐。</summary>
public sealed record DateCandidateDiagnostics(
    int Index,
    ulong Address,
    ulong BaseAddress,
    ulong RegionStart,
    ulong RegionOffset,
    string Module,
    string DataType,
    string RawBytes,
    uint RawValue,
    string? Date,
    uint RawReference,
    string? Reference,
    int ReferenceGapDays,
    string Signature,
    string Source,
    string StructureFingerprint,
    string LogicalSignature,
    ulong RelativeAddress,
    string? RelatedObject,
    string StructureEvidence,
    DateCandidateKind Kind,
    DateRejectionReason Rejection,
    DateConfidenceLevel Confidence,
    string? FirstSeen,
    string? LastSeen,
    int ReadCount,
    int ConsecutiveConsistentReads,
    string? SessionKey,
    IReadOnlyList<string> ObservedDates,
    string? RejectionDetail);

/// <summary>选中的日期与统计。</summary>
/// <param name="SelectedDate">选中的日期；未选中为 <c>null</c>。</param>
/// <param name="CandidateCount">参与判定的候选数。</param>
/// <param name="VerifiedCandidateCount">达到会话验证的候选数。</param>
/// <param name="RejectedCount">被明确排除的候选数。</param>
public sealed record SelectedDateSummary(
    string? SelectedDate,
    int CandidateCount,
    int VerifiedCandidateCount,
    int RejectedCount);

/// <summary>自动快照安全门判定。</summary>
/// <param name="Allowed">是否允许自动快照。</param>
/// <param name="Status"><c>ENABLED</c> 或 <c>BLOCKED</c>。</param>
/// <param name="Reasons">未通过的原因（通过时为空）。</param>
public sealed record SnapshotGateDecision(
    bool Allowed,
    string Status,
    IReadOnlyList<string> Reasons)
{
    /// <summary>永远拒绝（默认状态）。</summary>
    /// <param name="reasons">原因。</param>
    /// <returns>BLOCKED 判定。</returns>
    public static SnapshotGateDecision Blocked(IReadOnlyList<string> reasons) => new(false, "BLOCKED", reasons);

    /// <summary>允许自动快照。</summary>
    public static SnapshotGateDecision Enabled() => new(true, "ENABLED", Array.Empty<string>());
}

/// <summary>完整的世界日期诊断报告。</summary>
public sealed record WorldDateDiagnosticsReport(
    string Status,
    DateConfidenceLevel Confidence,
    ProcessDiagnostics Process,
    SessionDiagnostics Session,
    SelectedDateSummary DateSummary,
    IReadOnlyList<DateCandidateDiagnostics> Candidates,
    IReadOnlyList<DateCandidateDiagnostics> RejectedCandidates,
    string? SelectionReason,
    IReadOnlyList<string> VerificationEvidence,
    IReadOnlyList<string> Limitations,
    SnapshotGateDecision Snapshot,
    string NextAction,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 采集阶段得到的一条候选观测。它只描述“这一瞬间内存里有什么”，不携带任何跨读取状态；
/// 跨读取的计数、时间与验证结论由 <see cref="DateCandidateTracker"/> 维护。
/// </summary>
public sealed record DateCandidateObservation(
    ulong Address,
    ulong BaseAddress,
    ulong RegionStart,
    string Module,
    uint RawValue,
    uint RawReference,
    string Signature,
    string Source,
    string StructureFingerprint,
    string LogicalSignature,
    ulong RelativeAddress,
    string? RelatedObject,
    string StructureEvidence,
    DateCandidateKind KindHint,
    int ConsecutiveConsistentReads,
    string RawBytes);
