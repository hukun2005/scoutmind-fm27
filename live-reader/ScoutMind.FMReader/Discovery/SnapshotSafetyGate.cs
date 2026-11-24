namespace ScoutMind.FMReader.Discovery;

/// <summary>自动快照安全门的输入。所有“是否有效”的布尔值都必须由可核查的事实给出，不能用默认值猜测。</summary>
/// <param name="DateAvailable">是否读到了候选日期。</param>
/// <param name="CandidateUnambiguous">候选是否唯一且未被排除。</param>
/// <param name="Confidence">日期可信度。</param>
/// <param name="ProcessSessionValid">进程会话是否有效。</param>
/// <param name="SaveIdentityValid">存档身份是否有效（当前实现恒为 <c>false</c>）。</param>
/// <param name="ReaderVersionSupported">Reader 版本/构建是否受支持。</param>
/// <param name="DateSourceValid">日期来源是否为已验证的内存候选。</param>
public sealed record SnapshotSafetyInput(
    bool DateAvailable,
    bool CandidateUnambiguous,
    DateConfidenceLevel Confidence,
    bool ProcessSessionValid,
    bool SaveIdentityValid,
    bool ReaderVersionSupported,
    bool DateSourceValid);

/// <summary>
/// 自动快照安全门：只有所有硬性条件同时成立才允许自动快照。
///
/// 默认严格：证据不足、候选有歧义、存档身份未知、未达到 <see cref="DateConfidenceLevel.RestartVerified"/>
/// 的任何一种情况都返回 <c>BLOCKED</c>，并给出逐条原因。
/// </summary>
public static class SnapshotSafetyGate
{
    /// <summary>评估安全门。</summary>
    /// <param name="input">输入条件。</param>
    /// <returns>判定。</returns>
    public static SnapshotGateDecision Evaluate(SnapshotSafetyInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        var reasons = new List<string>();

        if (!input.DateAvailable)
        {
            reasons.Add("没有读取到可用日期。");
        }

        if (!input.CandidateUnambiguous)
        {
            reasons.Add("候选存在歧义或已被排除。");
        }

        if (input.Confidence != DateConfidenceLevel.RestartVerified)
        {
            reasons.Add($"日期可信度只有 {ToText(input.Confidence)}，未达到 restart_verified。");
        }

        if (!input.ProcessSessionValid)
        {
            reasons.Add("进程会话无效或尚未完成验证。");
        }

        if (!input.SaveIdentityValid)
        {
            reasons.Add("存档身份未经验证（即使同一天同一存档也只允许一次快照）。");
        }

        if (!input.ReaderVersionSupported)
        {
            reasons.Add("当前 Reader 构建未通过版本验证。");
        }

        if (!input.DateSourceValid)
        {
            reasons.Add("日期来源不是已验证的内存候选。");
        }

        return reasons.Count == 0
            ? SnapshotGateDecision.Enabled()
            : SnapshotGateDecision.Blocked(reasons);
    }

    /// <summary>把可信度等级转成诊断文本。</summary>
    /// <param name="level">等级。</param>
    /// <returns>文本。</returns>
    public static string ToText(DateConfidenceLevel level) => level switch
    {
        DateConfidenceLevel.Unavailable => "unavailable",
        DateConfidenceLevel.Discovered => "discovered",
        DateConfidenceLevel.Heuristic => "heuristic",
        DateConfidenceLevel.VerificationPending => "verification_pending",
        DateConfidenceLevel.SessionVerified => "session_verified",
        DateConfidenceLevel.RestartVerified => "restart_verified",
        _ => "unknown",
    };

    /// <summary>把候选类别转成诊断文本。</summary>
    /// <param name="kind">类别。</param>
    /// <returns>文本。</returns>
    public static string ToText(DateCandidateKind kind) => kind switch
    {
        DateCandidateKind.CurrentWorldDate => "CURRENT_WORLD_DATE",
        DateCandidateKind.MatchDate => "MATCH_DATE",
        DateCandidateKind.TransferDate => "TRANSFER_DATE",
        DateCandidateKind.NewsDate => "NEWS_DATE",
        DateCandidateKind.CalendarDate => "CALENDAR_DATE",
        DateCandidateKind.HistoryDate => "HISTORY_DATE",
        _ => "UNKNOWN_DATE",
    };

    /// <summary>把排除原因转成诊断文本。</summary>
    /// <param name="reason">原因。</param>
    /// <returns>文本。</returns>
    public static string ToText(DateRejectionReason reason) => reason switch
    {
        DateRejectionReason.None => "NONE",
        DateRejectionReason.InvalidDate => "INVALID_DATE",
        DateRejectionReason.OutOfSupportedRange => "OUT_OF_SUPPORTED_RANGE",
        DateRejectionReason.MatchObject => "MATCH_OBJECT",
        DateRejectionReason.TransferObject => "TRANSFER_OBJECT",
        DateRejectionReason.CalendarObject => "CALENDAR_OBJECT",
        DateRejectionReason.NewsObject => "NEWS_OBJECT",
        DateRejectionReason.FutureEvent => "FUTURE_EVENT",
        DateRejectionReason.UnstableValue => "UNSTABLE_VALUE",
        DateRejectionReason.UnresolvedReference => "UNRESOLVED_REFERENCE",
        DateRejectionReason.DuplicateSignature => "DUPLICATE_SIGNATURE",
        DateRejectionReason.InsufficientEvidence => "INSUFFICIENT_EVIDENCE",
        _ => "UNKNOWN",
    };
}
