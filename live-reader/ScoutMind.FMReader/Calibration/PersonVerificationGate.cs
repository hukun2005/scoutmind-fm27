using System.Globalization;
using System.Text.Json;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// Person 验证状态机（Phase 5）。
///
/// 只允许按 UnverifiedCandidate → StructurallyValid → IdentityMatched → HumanReviewPending → Verified
/// 逐级推进；任何一级失败都进入对应的拒绝状态，不得跳到 Verified。
/// </summary>
public enum PersonVerificationState
{
    /// <summary>尚未完成结构校验。</summary>
    UnverifiedCandidate,

    /// <summary>指针、结构、姓名、生日、版本与稳定性都通过，但还没有属性记录关联。</summary>
    StructurallyValid,

    /// <summary>属性记录已唯一关联，但还没有人工确认。</summary>
    IdentityMatched,

    /// <summary>已具备人工确认条件，但用户尚未确认（或确认信息不完整）。</summary>
    HumanReviewPending,

    /// <summary>全部前置条件满足且已有人工确认。</summary>
    Verified,

    /// <summary>前置条件失败。</summary>
    Rejected,

    /// <summary>存在身份冲突（多候选/同名冲突）。</summary>
    Conflicted,

    /// <summary>多次读取不稳定。</summary>
    Unstable,

    /// <summary>构建或布局不匹配。</summary>
    UnsupportedBuild,
}

/// <summary>验证输入：全部来自只读观测与人工确认，不包含内存写入。</summary>
/// <param name="CandidateId">候选布局标识。</param>
/// <param name="LayoutVersion">布局对应版本。</param>
/// <param name="ObservedBuild">本次检测到的构建。</param>
/// <param name="ExpectedBuild">候选声明支持的构建。</param>
/// <param name="BuildSupported">版本闸门是否允许扫描。</param>
/// <param name="LayoutMatches">布局版本是否匹配。</param>
/// <param name="PersonPointerValid">Person 指针是否有效。</param>
/// <param name="StructureValid">对象结构是否通过校验。</param>
/// <param name="DisplayName">读取到的展示姓名。</param>
/// <param name="DateOfBirth">读取到的出生日期。</param>
/// <param name="ApprovedAlternativeStrategy">经明确批准的替代生日验证策略；没有则为 <c>null</c>。</param>
/// <param name="Ca">CA（只作为证据记录，不参与身份判定）。</param>
/// <param name="AttributeLink">属性记录关联结果。</param>
/// <param name="ReadsStable">多次读取是否稳定。</param>
/// <param name="StableReadCount">用于稳定性判断的读取次数。</param>
/// <param name="Confidence">校准置信度（结构上限 0.5）。</param>
/// <param name="HumanConfirmed">用户是否已在 FM27 界面人工核对确认。</param>
/// <param name="Reviewer">确认人或确认来源标识。</param>
/// <param name="ConfirmationSource">确认方式（例如游戏界面截图、人工核对记录）。</param>
/// <param name="EvidenceReference">证据文档或记录引用。</param>
/// <param name="ObservedAt">观测时间。</param>
public sealed record PersonVerificationRequest(
    string CandidateId,
    string LayoutVersion,
    string ObservedBuild,
    string ExpectedBuild,
    bool BuildSupported,
    bool LayoutMatches,
    bool PersonPointerValid,
    bool StructureValid,
    string? DisplayName,
    DateOnly? DateOfBirth,
    string? ApprovedAlternativeStrategy,
    int? Ca,
    AttributeLinkResult? AttributeLink,
    bool ReadsStable,
    int StableReadCount,
    double Confidence,
    bool HumanConfirmed,
    string? Reviewer,
    string? ConfirmationSource,
    string? EvidenceReference,
    DateTimeOffset ObservedAt);

/// <summary>验证审计记录（脱敏，不含任何内存地址）。</summary>
/// <param name="Timestamp">操作时间。</param>
/// <param name="Outcome">验证结果。</param>
/// <param name="MarkVerified">是否执行 Mark(Verified)。</param>
/// <param name="CandidateId">Person 候选标识。</param>
/// <param name="LayoutVersion">布局版本。</param>
/// <param name="GameBuild">游戏构建号。</param>
/// <param name="PlayerName">球员姓名。</param>
/// <param name="DateOfBirth">出生日期。</param>
/// <param name="ClubName">俱乐部。</param>
/// <param name="PlayerUid">UID。</param>
/// <param name="Ca">CA。</param>
/// <param name="AttributeLinkStatus">属性记录关联状态。</param>
/// <param name="Confidence">置信度。</param>
/// <param name="VerifiedFields">通过核对的字段。</param>
/// <param name="RejectionReasons">阻塞/拒绝原因码。</param>
/// <param name="Reviewer">确认人。</param>
/// <param name="ConfirmationSource">确认来源。</param>
/// <param name="EvidenceReference">证据引用。</param>
public sealed record PersonVerificationAuditEntry(
    DateTimeOffset Timestamp,
    string Outcome,
    bool MarkVerified,
    string CandidateId,
    string LayoutVersion,
    string GameBuild,
    string? PlayerName,
    DateOnly? DateOfBirth,
    string? ClubName,
    uint? PlayerUid,
    int? Ca,
    string? AttributeLinkStatus,
    double Confidence,
    IReadOnlyList<string> VerifiedFields,
    IReadOnlyList<string> RejectionReasons,
    string? Reviewer,
    string? ConfirmationSource,
    string? EvidenceReference)
{
    /// <summary>序列化为单行 JSON（用于审计日志）。</summary>
    /// <returns>单行 JSON。</returns>
    public string ToJsonLine() => JsonSerializer.Serialize(new
    {
        timestamp = Timestamp.ToString("O"),
        outcome = Outcome,
        mark_verified = MarkVerified,
        candidate_id = CandidateId,
        layout_version = LayoutVersion,
        game_build = GameBuild,
        player_identity = new
        {
            name = PlayerName,
            date_of_birth = DateOfBirth?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
            club = ClubName,
            uid = PlayerUid,
            ca = Ca,
        },
        attribute_link_status = AttributeLinkStatus,
        confidence = Confidence,
        verified_fields = VerifiedFields,
        rejection_reasons = RejectionReasons,
        reviewer = Reviewer,
        confirmation_source = ConfirmationSource,
        evidence_reference = EvidenceReference,
    }, new JsonSerializerOptions
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    });
}

/// <summary>验证决定。</summary>
/// <param name="State">状态机结果。</param>
/// <param name="MarkVerified">是否允许 Mark(Verified)。</param>
/// <param name="Reasons">阻塞原因码（可追踪）。</param>
/// <param name="Warnings">非阻塞警告。</param>
/// <param name="Audit">审计记录。</param>
public sealed record PersonVerificationDecision(
    PersonVerificationState State,
    bool MarkVerified,
    IReadOnlyList<string> Reasons,
    IReadOnlyList<string> Warnings,
    PersonVerificationAuditEntry Audit);

/// <summary>
/// Mark(Verified) 安全门控。
///
/// 核心约束：缺少任意前置条件都不得 Mark(Verified)；没有人工确认时保持 HumanReviewPending；
/// 本类从不写内存、不写存档、不修改布局。
/// </summary>
public sealed class PersonVerificationGate
{
    /// <summary>评估验证请求。</summary>
    /// <param name="request">验证输入。</param>
    /// <returns>验证决定与审计记录。</returns>
    public PersonVerificationDecision Evaluate(PersonVerificationRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        var reasons = new List<string>();
        var warnings = new List<string>(2);

        var versionOk = request.BuildSupported
                        && request.LayoutMatches
                        && !string.IsNullOrWhiteSpace(request.ObservedBuild)
                        && string.Equals(request.ObservedBuild, request.ExpectedBuild, StringComparison.Ordinal);
        var pointerOk = request.PersonPointerValid;
        var structureOk = request.StructureValid;
        var nameOk = !string.IsNullOrWhiteSpace(request.DisplayName);
        var dobOk = request.DateOfBirth is not null
                    || !string.IsNullOrWhiteSpace(request.ApprovedAlternativeStrategy);
        var stableOk = request.ReadsStable && request.StableReadCount >= 2;

        if (!versionOk)
        {
            reasons.Add("layout_version_mismatch");
        }

        if (!pointerOk)
        {
            reasons.Add("person_pointer_invalid");
        }

        if (!structureOk)
        {
            reasons.Add("structure_invalid");
        }

        if (!nameOk)
        {
            reasons.Add("name_missing");
        }

        if (!dobOk)
        {
            reasons.Add("date_of_birth_missing");
        }

        if (!stableOk)
        {
            reasons.Add("unstable_reads");
        }

        PersonVerificationState state;
        if (!versionOk)
        {
            state = PersonVerificationState.UnsupportedBuild;
        }
        else if (!stableOk)
        {
            state = PersonVerificationState.Unstable;
        }
        else if (!pointerOk || !structureOk || !nameOk || !dobOk)
        {
            state = PersonVerificationState.Rejected;
        }
        else if (request.AttributeLink is null)
        {
            reasons.Add("attribute_link_missing");
            state = PersonVerificationState.StructurallyValid;
        }
        else if (request.AttributeLink.Status is AttributeLinkStatus.MultipleCandidates
                 or AttributeLinkStatus.ConflictingIdentity
                 || request.AttributeLink.Conflicts.Count > 0)
        {
            reasons.Add(request.AttributeLink.Status == AttributeLinkStatus.MultipleCandidates
                ? "multiple_candidates"
                : "identity_conflict");
            state = PersonVerificationState.Conflicted;
        }
        else if (request.AttributeLink.Status is AttributeLinkStatus.NoMatch
                 or AttributeLinkStatus.RejectedMatch)
        {
            reasons.Add(request.AttributeLink.Status == AttributeLinkStatus.NoMatch
                ? "attribute_record_not_found"
                : "target_identity_insufficient");
            state = PersonVerificationState.Rejected;
        }
        else if (!request.HumanConfirmed)
        {
            reasons.Add("human_review_pending");
            state = PersonVerificationState.HumanReviewPending;
        }
        else if (string.IsNullOrWhiteSpace(request.Reviewer)
                 || string.IsNullOrWhiteSpace(request.ConfirmationSource)
                 || string.IsNullOrWhiteSpace(request.EvidenceReference))
        {
            reasons.Add("human_confirmation_incomplete");
            state = PersonVerificationState.HumanReviewPending;
        }
        else
        {
            state = PersonVerificationState.Verified;
        }

        if (request.AttributeLink is null)
        {
            warnings.Add("没有属性记录关联结果：最多只能到 StructurallyValid");
        }

        if (request.ApprovedAlternativeStrategy is { Length: > 0 } alternative)
        {
            warnings.Add($"使用批准的替代生日验证策略：{alternative}");
        }

        var verifiedFields = CollectVerifiedFields(request, state);
        var audit = new PersonVerificationAuditEntry(
            request.ObservedAt,
            state.ToString(),
            state == PersonVerificationState.Verified,
            request.CandidateId,
            request.LayoutVersion,
            request.ObservedBuild,
            request.DisplayName,
            request.DateOfBirth,
            request.AttributeLink?.Target.ClubName,
            request.AttributeLink?.Target.Uid,
            request.Ca,
            request.AttributeLink?.Status.ToString(),
            request.Confidence,
            verifiedFields,
            reasons,
            request.Reviewer,
            request.ConfirmationSource,
            request.EvidenceReference);

        return new PersonVerificationDecision(
            state,
            state == PersonVerificationState.Verified,
            reasons,
            warnings,
            audit);
    }

    private static IReadOnlyList<string> CollectVerifiedFields(
        PersonVerificationRequest request,
        PersonVerificationState state)
    {
        if (state != PersonVerificationState.Verified)
        {
            return Array.Empty<string>();
        }

        var fields = new List<string> { "name", "date_of_birth" };
        if (request.AttributeLink is { CompatibleCandidates.Count: 1 } link)
        {
            foreach (var comparison in link.CompatibleCandidates[0].Comparisons)
            {
                if (comparison.Applicable && comparison.Matched && !fields.Contains(comparison.Field))
                {
                    fields.Add(comparison.Field);
                }
            }
        }

        return fields;
    }
}
