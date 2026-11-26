namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// Verified 生命周期状态（V3.2.9.2）。
///
/// 名称与 V3.2.8.1 的 <see cref="PersonVerificationState"/> 保持等价语义；
/// 这里描述的是"持久化后的 Verified 记录"，而不是一次 Evaluate 的即时结论。
/// </summary>
public enum VerificationState
{
    /// <summary>尚未验证。</summary>
    Unverified,

    /// <summary>验证进行中。</summary>
    Verifying,

    /// <summary>已验证，且绑定当前 Save Identity / generation / 证据。</summary>
    Verified,

    /// <summary>证据或作用域已变化，必须重新读取并确认。</summary>
    RevalidationRequired,

    /// <summary>关键身份字段冲突。</summary>
    Conflict,

    /// <summary>无法唯一确定存档/球员。</summary>
    Ambiguous,

    /// <summary>已失效（切档、会话变化、撤销等），历史保留。</summary>
    Invalidated,

    /// <summary>验证失败。</summary>
    Failed,
}

/// <summary>一次验证提交的结果。</summary>
public enum VerificationCommitOutcome
{
    /// <summary>已写入新的 Verified 记录。</summary>
    Applied,

    /// <summary>同一作用域、同一证据重复提交：幂等，不新增历史。</summary>
    Duplicate,

    /// <summary>generation 已过期，旧任务结果被丢弃。</summary>
    StaleGeneration,

    /// <summary>证据不完整，不允许 Verified。</summary>
    InsufficientEvidence,
}

/// <summary>Verified 必须固化的证据摘要。</summary>
/// <param name="SaveIdentityFingerprint">存档身份指纹。</param>
/// <param name="SaveSessionKey">采集会话键。</param>
/// <param name="GameBuild">游戏构建号。</param>
/// <param name="LayoutVersion">布局版本。</param>
/// <param name="PersonUid">存档内 UID。</param>
/// <param name="DisplayName">展示姓名。</param>
/// <param name="DateOfBirth">出生日期。</param>
/// <param name="AttributeRecordIdentity">属性记录摘要。</param>
/// <param name="ValidatorVersion">验证器版本。</param>
/// <param name="EvidenceDigest">关键证据摘要。</param>
public sealed record VerificationEvidence(
    string SaveIdentityFingerprint,
    string SaveSessionKey,
    string GameBuild,
    string LayoutVersion,
    uint PersonUid,
    string DisplayName,
    DateOnly? DateOfBirth,
    string AttributeRecordIdentity,
    string ValidatorVersion,
    string EvidenceDigest)
{
    /// <summary>是否具备全部必需证据；缺任意一项都不允许 Verified。</summary>
    public bool IsComplete =>
        !string.IsNullOrWhiteSpace(SaveIdentityFingerprint)
        && !string.IsNullOrWhiteSpace(SaveSessionKey)
        && !string.IsNullOrWhiteSpace(GameBuild)
        && !string.IsNullOrWhiteSpace(LayoutVersion)
        && PersonUid != 0
        && !string.IsNullOrWhiteSpace(DisplayName)
        && (DateOfBirth is not null)
        && !string.IsNullOrWhiteSpace(AttributeRecordIdentity)
        && !string.IsNullOrWhiteSpace(ValidatorVersion)
        && !string.IsNullOrWhiteSpace(EvidenceDigest);
}

/// <summary>开始验证时拿到的 generation 令牌。</summary>
/// <param name="Generation">开始时的身份代次。</param>
/// <param name="StartedAt">开始时间。</param>
public sealed record VerificationAttempt(int Generation, DateTimeOffset StartedAt);

/// <summary>一条不可覆盖的 Verified 生命周期记录（只追加）。</summary>
/// <param name="Sequence">追加序号。</param>
/// <param name="SaveIdentityFingerprint">存档身份指纹。</param>
/// <param name="PersonUid">存档内 UID。</param>
/// <param name="State">记录状态。</param>
/// <param name="Generation">写入时的身份代次。</param>
/// <param name="VerifiedAt">验证时间。</param>
/// <param name="ValidatorVersion">验证器版本。</param>
/// <param name="EvidenceDigest">证据摘要。</param>
/// <param name="Reason">失效/变更原因；正常 Verified 为 <c>null</c>。</param>
/// <param name="RecordedAt">记录写入时间。</param>
public sealed record VerifiedLifecycleRecord(
    long Sequence,
    string SaveIdentityFingerprint,
    uint PersonUid,
    VerificationState State,
    int Generation,
    DateTimeOffset VerifiedAt,
    string ValidatorVersion,
    string EvidenceDigest,
    string? Reason,
    DateTimeOffset RecordedAt);

/// <summary>提交结果。</summary>
/// <param name="Outcome">结果。</param>
/// <param name="Record">本次产生的记录；幂等时为既有记录。</param>
/// <param name="Note">解释。</param>
public sealed record VerificationCommitResult(
    VerificationCommitOutcome Outcome,
    VerifiedLifecycleRecord? Record,
    string Note);

/// <summary>
/// Verified 生命周期台账（V3.2.9.2）。
///
/// 规则：
/// * 每条 Verified 绑定 Save Identity + generation + 验证器版本 + 证据摘要；
/// * 切档/会话变化通过 <see cref="AdvanceGeneration"/> 推进代次并使旧记录失效；
/// * 旧任务携带的令牌代次不匹配时一律丢弃，绝不覆盖新状态；
/// * 已撤销的 Verified 不会被旧任务恢复；
/// * 历史只追加，不覆盖、不删除。
/// </summary>
public sealed class VerifiedLifecycleLedger
{
    private readonly Func<DateTimeOffset> _now;
    private readonly List<VerifiedLifecycleRecord> _history = new();
    private readonly Dictionary<(string Fingerprint, uint Uid), VerifiedLifecycleRecord> _active = new();
    private readonly object _gate = new();
    private long _sequence;

    /// <summary>创建台账。</summary>
    /// <param name="now">时间提供器（便于测试）。</param>
    public VerifiedLifecycleLedger(Func<DateTimeOffset>? now = null)
    {
        _now = now ?? (() => DateTimeOffset.UtcNow);
    }

    /// <summary>当前身份代次。</summary>
    public int CurrentGeneration { get; private set; }

    /// <summary>全部历史记录（只读快照）。</summary>
    public IReadOnlyList<VerifiedLifecycleRecord> History
    {
        get
        {
            lock (_gate)
            {
                return _history.ToArray();
            }
        }
    }

    /// <summary>取得当前有效的 Verified 记录；没有时为 <c>null</c>。</summary>
    /// <param name="fingerprint">存档身份指纹。</param>
    /// <param name="uid">球员 UID。</param>
    /// <returns>当前有效记录。</returns>
    public VerifiedLifecycleRecord? Active(string fingerprint, uint uid)
    {
        lock (_gate)
        {
            return _active.TryGetValue((fingerprint, uid), out var record) ? record : null;
        }
    }

    /// <summary>开始一次验证，记录当前 generation。</summary>
    /// <returns>验证令牌。</returns>
    public VerificationAttempt Begin()
    {
        lock (_gate)
        {
            CurrentGeneration = Math.Max(CurrentGeneration, 1);
            return new VerificationAttempt(CurrentGeneration, _now());
        }
    }

    /// <summary>推进身份代次，并使所有当前 Verified 失效。</summary>
    /// <param name="reason">失效原因码。</param>
    /// <returns>新的代次。</returns>
    public int AdvanceGeneration(string reason)
    {
        if (string.IsNullOrWhiteSpace(reason))
        {
            throw new ArgumentException("失效原因不能为空。", nameof(reason));
        }

        lock (_gate)
        {
            foreach (var record in _active.Values.ToArray())
            {
                Append(record.SaveIdentityFingerprint, record.PersonUid, VerificationState.Invalidated,
                    VerifiedAt: record.VerifiedAt, ValidatorVersion: record.ValidatorVersion,
                    EvidenceDigest: record.EvidenceDigest, reason: reason);
            }

            _active.Clear();
            CurrentGeneration++;
            return CurrentGeneration;
        }
    }

    /// <summary>管理员/审核显式撤销某个 Verified；同时推进代次，旧任务无法恢复。</summary>
    /// <param name="fingerprint">存档身份指纹。</param>
    /// <param name="uid">球员 UID。</param>
    /// <param name="reason">撤销原因码。</param>
    /// <returns>是否真的撤销了一条有效记录。</returns>
    public bool Revoke(string fingerprint, uint uid, string reason)
    {
        lock (_gate)
        {
            if (!_active.Remove((fingerprint, uid), out var record))
            {
                return false;
            }

            Append(record.SaveIdentityFingerprint, record.PersonUid, VerificationState.Invalidated,
                record.VerifiedAt, record.ValidatorVersion, record.EvidenceDigest, reason);
            CurrentGeneration++;
            return true;
        }
    }

    /// <summary>提交一次验证结果。</summary>
    /// <param name="attempt">开始验证时取得的令牌。</param>
    /// <param name="evidence">证据摘要。</param>
    /// <param name="state">验证结论；只有 <see cref="VerificationState.Verified"/> 会写入有效记录。</param>
    /// <returns>提交结果。</returns>
    public VerificationCommitResult Commit(
        VerificationAttempt attempt,
        VerificationEvidence evidence,
        VerificationState state = VerificationState.Verified)
    {
        ArgumentNullException.ThrowIfNull(attempt);
        ArgumentNullException.ThrowIfNull(evidence);

        if (state != VerificationState.Verified || !evidence.IsComplete)
        {
            return new VerificationCommitResult(
                VerificationCommitOutcome.InsufficientEvidence,
                null,
                "证据不完整：不允许写入 Verified。");
        }

        lock (_gate)
        {
            if (attempt.Generation != CurrentGeneration)
            {
                return new VerificationCommitResult(
                    VerificationCommitOutcome.StaleGeneration,
                    null,
                    $"generation 已过期（任务 {attempt.Generation} / 当前 {CurrentGeneration}），结果被丢弃。");
            }

            var key = (evidence.SaveIdentityFingerprint, evidence.PersonUid);
            if (_active.TryGetValue(key, out var existing)
                && existing.Generation == attempt.Generation
                && string.Equals(existing.EvidenceDigest, evidence.EvidenceDigest, StringComparison.Ordinal)
                && existing.ValidatorVersion == evidence.ValidatorVersion)
            {
                return new VerificationCommitResult(
                    VerificationCommitOutcome.Duplicate,
                    existing,
                    "同一作用域、同一证据重复验证：幂等返回既有记录。");
            }

            if (existing is not null)
            {
                Append(existing.SaveIdentityFingerprint, existing.PersonUid, VerificationState.RevalidationRequired,
                    existing.VerifiedAt, existing.ValidatorVersion, existing.EvidenceDigest,
                    reason: "evidence_changed");
            }

            var record = Append(
                evidence.SaveIdentityFingerprint,
                evidence.PersonUid,
                VerificationState.Verified,
                VerifiedAt: _now(),
                ValidatorVersion: evidence.ValidatorVersion,
                EvidenceDigest: evidence.EvidenceDigest,
                reason: null,
                generation: attempt.Generation);

            _active[key] = record;
            return new VerificationCommitResult(VerificationCommitOutcome.Applied, record, "已写入新的 Verified 记录。");
        }
    }

    /// <summary>使某个 Verified 进入重新确认状态（不推进代次，用于证据变化）。</summary>
    /// <param name="fingerprint">存档身份指纹。</param>
    /// <param name="uid">球员 UID。</param>
    /// <param name="reason">原因码。</param>
    /// <returns>是否处理了有效记录。</returns>
    public bool RequireRevalidation(string fingerprint, uint uid, string reason)
    {
        lock (_gate)
        {
            if (!_active.Remove((fingerprint, uid), out var record))
            {
                return false;
            }

            Append(record.SaveIdentityFingerprint, record.PersonUid, VerificationState.RevalidationRequired,
                record.VerifiedAt, record.ValidatorVersion, record.EvidenceDigest, reason);
            return true;
        }
    }

    private VerifiedLifecycleRecord Append(
        string fingerprint,
        uint uid,
        VerificationState state,
        DateTimeOffset VerifiedAt,
        string ValidatorVersion,
        string EvidenceDigest,
        string? reason,
        int? generation = null)
    {
        var record = new VerifiedLifecycleRecord(
            Sequence: ++_sequence,
            SaveIdentityFingerprint: fingerprint,
            PersonUid: uid,
            State: state,
            Generation: generation ?? CurrentGeneration,
            VerifiedAt: VerifiedAt,
            ValidatorVersion: ValidatorVersion,
            EvidenceDigest: EvidenceDigest,
            Reason: reason,
            RecordedAt: _now());
        _history.Add(record);
        return record;
    }
}

/// <summary>
/// Verified 状态的 API/前端序列化规则：未知状态绝不能显示为成功。
/// </summary>
public static class VerificationStateText
{
    /// <summary>转为稳定的 API 文本。</summary>
    /// <param name="state">状态。</param>
    /// <returns>文本。</returns>
    public static string ToApiText(VerificationState state) => state switch
    {
        VerificationState.Unverified => "unverified",
        VerificationState.Verifying => "verifying",
        VerificationState.Verified => "verified",
        VerificationState.RevalidationRequired => "revalidation_required",
        VerificationState.Conflict => "conflict",
        VerificationState.Ambiguous => "ambiguous",
        VerificationState.Invalidated => "invalidated",
        VerificationState.Failed => "failed",
        _ => "unknown",
    };

    /// <summary>只有 <c>verified</c> 才允许显示为成功；未知/空值一律不是成功。</summary>
    /// <param name="apiText">API 文本。</param>
    /// <returns>是否成功。</returns>
    public static bool IsSuccess(string? apiText) =>
        string.Equals(apiText, "verified", StringComparison.Ordinal);
}
