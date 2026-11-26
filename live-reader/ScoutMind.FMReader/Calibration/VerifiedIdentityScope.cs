using System.Globalization;
using System.Text;
using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 一次 Verified 身份的完整作用域（V3.2.8.1）。
///
/// Verified 不能脱离存档身份、游戏构建和内存布局独立存在：
/// 同一个球员姓名/生日在不同存档里不代表同一实体，旧会话的 Person 指针也不能继续使用。
/// 因此把"当时为什么可以 Verified"的全部依据固化在作用域里，历史记录只追加、不覆盖。
/// </summary>
/// <param name="SaveId">存档标识（通常与指纹一致，可由用户另起可读标签）。</param>
/// <param name="SaveIdentityFingerprint">Save Identity 复合指纹（复用 <see cref="SaveIdentityFingerprint"/>）。</param>
/// <param name="SaveSessionKey">采集会话键（PID + 启动时间 + 构建）；旧会话不得复用指针。</param>
/// <param name="GameBuild">验证时的游戏构建号。</param>
/// <param name="LayoutVersion">验证时的布局版本。</param>
/// <param name="PersonUid">存档内 UID；0 视为缺失。</param>
/// <param name="DisplayName">验证时的展示姓名。</param>
/// <param name="DateOfBirth">验证时的出生日期；使用批准的替代策略时可为默认值。</param>
/// <param name="ApprovedAlternativeStrategy">经明确批准的替代生日验证策略；没有则为 <c>null</c>。</param>
/// <param name="AttributeRecordIdentity">关联属性记录的稳定摘要（不保存原始内存地址）。</param>
/// <param name="VerifiedAt">验证时间。</param>
/// <param name="Reviewer">人工确认人。</param>
/// <param name="ConfirmationSource">确认来源。</param>
/// <param name="EvidenceReference">证据引用。</param>
public sealed record VerifiedIdentityScope(
    string SaveId,
    string SaveIdentityFingerprint,
    string SaveSessionKey,
    string GameBuild,
    string LayoutVersion,
    uint PersonUid,
    string DisplayName,
    DateOnly DateOfBirth,
    string? ApprovedAlternativeStrategy,
    string AttributeRecordIdentity,
    DateTimeOffset VerifiedAt,
    string Reviewer,
    string ConfirmationSource,
    string EvidenceReference)
{
    /// <summary>作用域是否具备全部必需证据；缺任意一项都不允许 Mark(Verified)。</summary>
    public bool IsComplete =>
        !string.IsNullOrWhiteSpace(SaveId)
        && !string.IsNullOrWhiteSpace(SaveIdentityFingerprint)
        && !string.IsNullOrWhiteSpace(SaveSessionKey)
        && !string.IsNullOrWhiteSpace(GameBuild)
        && !string.IsNullOrWhiteSpace(LayoutVersion)
        && PersonUid != 0
        && !string.IsNullOrWhiteSpace(DisplayName)
        && (DateOfBirth != default || !string.IsNullOrWhiteSpace(ApprovedAlternativeStrategy))
        && !string.IsNullOrWhiteSpace(AttributeRecordIdentity)
        && VerifiedAt != default
        && !string.IsNullOrWhiteSpace(Reviewer)
        && !string.IsNullOrWhiteSpace(ConfirmationSource)
        && !string.IsNullOrWhiteSpace(EvidenceReference);

    /// <summary>属性记录的稳定身份摘要：只含身份字段，不含任何内存地址。</summary>
    /// <param name="facts">属性记录快照。</param>
    /// <returns>SHA-256 摘要。</returns>
    public static string AttributeRecordIdentityOf(PlayerRecordFacts facts)
    {
        ArgumentNullException.ThrowIfNull(facts);
        var name = string.Join(
            "|",
            new[] { facts.FirstName, facts.SecondName, facts.CommonName }
                .Select(NormalizeName));
        var dob = facts.DateOfBirth?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture) ?? "unknown";
        var uid = facts.Uid?.ToString(CultureInfo.InvariantCulture) ?? "unknown";
        return Discovery.SaveIdentityFingerprint.Sha256($"record|{name}|{dob}|{uid}");
    }

    /// <summary>姓名规范化：去空白、转小写、压缩内部空格；只用于摘要，不改变展示姓名。</summary>
    /// <param name="value">原始姓名片段。</param>
    /// <returns>规范化结果；空值为空字符串。</returns>
    public static string NormalizeName(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var builder = new StringBuilder(value.Length);
        var previousSpace = false;
        foreach (var ch in value.Trim())
        {
            if (char.IsWhiteSpace(ch))
            {
                if (!previousSpace)
                {
                    builder.Append(' ');
                    previousSpace = true;
                }

                continue;
            }

            builder.Append(char.ToLowerInvariant(ch));
            previousSpace = false;
        }

        return builder.ToString();
    }
}

/// <summary>当前上下文：用于判断历史 Verified 是否还能当作"当前有效身份"使用。</summary>
/// <param name="SaveId">当前存档标识。</param>
/// <param name="SaveIdentityFingerprint">当前 Save Identity 指纹。</param>
/// <param name="SaveSessionKey">当前会话键。</param>
/// <param name="GameBuild">当前构建号。</param>
/// <param name="LayoutVersion">当前布局版本。</param>
/// <param name="PersonUid">当前读到的 UID；缺失为 <c>null</c>。</param>
/// <param name="DisplayName">当前读到的姓名；缺失为 <c>null</c>。</param>
/// <param name="DateOfBirth">当前读到的生日；缺失为 <c>null</c>。</param>
/// <param name="AttributeRecordIdentity">当前属性记录摘要；未关联为 <c>null</c>。</param>
/// <param name="ClubName">当前俱乐部；只作审计，不参与身份判定。</param>
public sealed record VerifiedIdentityContext(
    string SaveId,
    string SaveIdentityFingerprint,
    string SaveSessionKey,
    string GameBuild,
    string LayoutVersion,
    uint? PersonUid,
    string? DisplayName,
    DateOnly? DateOfBirth,
    string? AttributeRecordIdentity,
    string? ClubName = null);

/// <summary>历史 Verified 在当前上下文下的生命周期状态。</summary>
public enum VerifiedLifecycleState
{
    /// <summary>全部作用域一致，可继续作为当前有效身份。</summary>
    Valid,

    /// <summary>存档身份已变化（跨存档/未解析）；历史记录保留，但当前不可用。</summary>
    Stale,

    /// <summary>作用域内的证据已变化（构建/布局/会话/字段缺失/记录变化），必须重读后再确认。</summary>
    RevalidationRequired,

    /// <summary>关键身份字段互相矛盾，必须人工审核，禁止自动合并。</summary>
    Conflicted,
}

/// <summary>身份连续性：与"Verified 是否仍然有效"分开判断，避免把名称变化误判成换人。</summary>
public enum IdentityContinuity
{
    /// <summary>仍可解释为同一名球员。</summary>
    SamePlayer,

    /// <summary>证据不足，无法判断是否为同一名球员。</summary>
    Unverifiable,

    /// <summary>关键身份字段矛盾，必须按不同球员处理。</summary>
    DifferentPlayer,
}

/// <summary>生命周期评估结果。</summary>
/// <param name="State">Verified 是否仍可用。</param>
/// <param name="Continuity">身份连续性判断。</param>
/// <param name="CanUseAsVerified">是否允许把历史记录当作当前 Verified 使用。</param>
/// <param name="Reasons">阻塞原因码（可追踪）。</param>
/// <param name="Warnings">非阻塞提示（如俱乐部变化、显示名变化）。</param>
public sealed record VerifiedLifecycleEvaluation(
    VerifiedLifecycleState State,
    IdentityContinuity Continuity,
    bool CanUseAsVerified,
    IReadOnlyList<string> Reasons,
    IReadOnlyList<string> Warnings);

/// <summary>
/// Verified 身份作用域校验器。
///
/// 规则（按优先级）：作用域不完整 → 缺字段；存档身份变化 → Stale；
/// 当前身份字段缺失 → 重读；构建/布局/会话/属性记录变化 → 重新确认；
/// 生日冲突 → 冲突；UID/姓名单独变化 → 重新确认且不得自动合并。
/// 俱乐部变化本身不影响身份（转会、自由球员、退役都不改变"同一个人"）。
/// </summary>
public static class VerifiedIdentityScopeValidator
{
    /// <summary>评估历史 Verified 是否仍可作为当前有效身份。</summary>
    /// <param name="scope">历史验证作用域。</param>
    /// <param name="current">当前上下文。</param>
    /// <returns>生命周期评估。</returns>
    public static VerifiedLifecycleEvaluation Evaluate(
        VerifiedIdentityScope scope,
        VerifiedIdentityContext current)
    {
        ArgumentNullException.ThrowIfNull(scope);
        ArgumentNullException.ThrowIfNull(current);

        if (!scope.IsComplete)
        {
            return Result(
                VerifiedLifecycleState.RevalidationRequired,
                IdentityContinuity.Unverifiable,
                "verified_scope_incomplete");
        }

        if (!string.Equals(
                scope.SaveIdentityFingerprint,
                current.SaveIdentityFingerprint,
                StringComparison.Ordinal))
        {
            return Result(
                VerifiedLifecycleState.Stale,
                IdentityContinuity.Unverifiable,
                "save_identity_mismatch");
        }

        if (current.PersonUid is not { } uid
            || current.DateOfBirth is not { } dateOfBirth
            || string.IsNullOrWhiteSpace(current.DisplayName))
        {
            return Result(
                VerifiedLifecycleState.RevalidationRequired,
                IdentityContinuity.Unverifiable,
                "person_facts_missing");
        }

        var reasons = new List<string>();
        var warnings = new List<string>();

        if (!string.Equals(scope.GameBuild, current.GameBuild, StringComparison.Ordinal))
        {
            reasons.Add("game_build_changed");
        }

        if (!string.Equals(scope.LayoutVersion, current.LayoutVersion, StringComparison.Ordinal))
        {
            reasons.Add("layout_version_changed");
        }

        if (!string.Equals(scope.SaveSessionKey, current.SaveSessionKey, StringComparison.Ordinal))
        {
            reasons.Add("session_changed");
        }

        if (dateOfBirth != scope.DateOfBirth)
        {
            reasons.Add("date_of_birth_conflict");
            return Result(
                VerifiedLifecycleState.Conflicted,
                IdentityContinuity.DifferentPlayer,
                reasons);
        }

        if (uid != scope.PersonUid)
        {
            // UID 可能随版本/存档重排而变化；不能据此自动合并，也不能直接判为换人。
            reasons.Add("person_uid_changed");
            return Result(
                VerifiedLifecycleState.RevalidationRequired,
                IdentityContinuity.Unverifiable,
                reasons);
        }

        if (!string.Equals(
                VerifiedIdentityScope.NormalizeName(scope.DisplayName),
                VerifiedIdentityScope.NormalizeName(current.DisplayName),
                StringComparison.Ordinal))
        {
            // 姓名变化本身不等于换人（改名、常用名切换），但必须重新人工确认展示名。
            reasons.Add("display_name_changed");
            warnings.Add("姓名变化不单独构成身份变更，但需要重新确认展示名。");
            return new VerifiedLifecycleEvaluation(
                VerifiedLifecycleState.RevalidationRequired,
                IdentityContinuity.SamePlayer,
                CanUseAsVerified: false,
                reasons,
                warnings);
        }

        if (!string.IsNullOrWhiteSpace(scope.AttributeRecordIdentity)
            && !string.IsNullOrWhiteSpace(current.AttributeRecordIdentity)
            && !string.Equals(
                scope.AttributeRecordIdentity,
                current.AttributeRecordIdentity,
                StringComparison.Ordinal))
        {
            reasons.Add("attribute_record_changed");
        }

        if (!string.Equals(scope.SaveId, current.SaveId, StringComparison.Ordinal))
        {
            warnings.Add("save_label_changed");
        }

        return reasons.Count == 0
            ? new VerifiedLifecycleEvaluation(
                VerifiedLifecycleState.Valid,
                IdentityContinuity.SamePlayer,
                CanUseAsVerified: true,
                Array.Empty<string>(),
                warnings)
            : new VerifiedLifecycleEvaluation(
                VerifiedLifecycleState.RevalidationRequired,
                IdentityContinuity.SamePlayer,
                CanUseAsVerified: false,
                reasons,
                warnings);
    }

    private static VerifiedLifecycleEvaluation Result(
        VerifiedLifecycleState state,
        IdentityContinuity continuity,
        string reason) =>
        new(state, continuity, state == VerifiedLifecycleState.Valid, new[] { reason }, Array.Empty<string>());

    private static VerifiedLifecycleEvaluation Result(
        VerifiedLifecycleState state,
        IdentityContinuity continuity,
        IReadOnlyList<string> reasons) =>
        new(state, continuity, state == VerifiedLifecycleState.Valid, reasons, Array.Empty<string>());
}
