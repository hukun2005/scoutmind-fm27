namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 候选布局的验证状态。
///
/// 关键规则：<see cref="Unverified"/> 与 <see cref="StructurallyValid"/> 都**不等于**
/// <see cref="Verified"/>；从 <see cref="Unverified"/> 不允许直接跳到 <see cref="Verified"/>。
/// </summary>
public enum CandidateVerificationStatus
{
    /// <summary>只是候选，尚未通过任何结构校验。</summary>
    Unverified,

    /// <summary>对象结构、姓名与出生日期都通过了内部校验（仍不是人工核对）。</summary>
    StructurallyValid,

    /// <summary>姓名/生日与属性记录唯一匹配（仍不是人工核对）。</summary>
    IdentityMatched,

    /// <summary>等待真实 FM27 人工核对。</summary>
    HumanReviewPending,

    /// <summary>已在游戏界面人工核对通过。</summary>
    Verified,

    /// <summary>对象无效或读取失败。</summary>
    Rejected,

    /// <summary>存在身份冲突。</summary>
    Conflicted,

    /// <summary>多次读取不稳定。</summary>
    Unstable,

    /// <summary>游戏构建不受支持。</summary>
    UnsupportedBuild,
}

/// <summary>候选字段类型。</summary>
public enum CandidateFieldKind
{
    /// <summary>嵌套字符串姓名（ptr → ptr → inner+4 的 UTF-8）。</summary>
    NestedName,

    /// <summary>出生日期（u32：高 16 位年、低 9 位年内序日）。</summary>
    DateOfBirth,
}

/// <summary>
/// 一份只读 Person 候选布局。
///
/// 这里的所有偏移都只是"待验证假设"，**不得直接写入生产布局常量**，也不得因为某一字段读取成功
/// 就认定整份布局可用。
/// </summary>
/// <param name="CandidateId">候选标识。</param>
/// <param name="GameVersion">适配的 FM 主次版本，例如 <c>27.1</c>。</param>
/// <param name="BuildNumber">Steam 构建号。</param>
/// <param name="NameOffsetCandidates">姓名候选偏移（相对 Person 指针）。</param>
/// <param name="DateOfBirthOffsetCandidate">出生日期候选偏移。</param>
/// <param name="PointerValidationRules">指针校验规则（人类可读，便于写入证据）。</param>
/// <param name="Confidence">置信度 0..1；候选阶段保持 0，避免被误读为已验证。</param>
/// <param name="Evidence">证据文档路径或说明。</param>
/// <param name="VerificationStatus">验证状态。</param>
public sealed record PersonLayoutCandidate(
    string CandidateId,
    string GameVersion,
    string BuildNumber,
    IReadOnlyList<uint> NameOffsetCandidates,
    uint DateOfBirthOffsetCandidate,
    IReadOnlyList<string> PointerValidationRules,
    double Confidence,
    string Evidence,
    CandidateVerificationStatus VerificationStatus)
{
    /// <summary>2026-11-25 在真实 FM27 build 26620374（插件 27.1）上观察到的候选，尚未验证。</summary>
    public static PersonLayoutCandidate Fm27_1_20261125 { get; } = new(
        CandidateId: "fm27.1.person.2026-11-25",
        GameVersion: "27.1",
        BuildNumber: "26620374",
        NameOffsetCandidates: new uint[] { 0x50, 0x58, 0x60 },
        DateOfBirthOffsetCandidate: 0x88,
        PointerValidationRules: new[]
        {
            "Person 指针必须非 0 且 8 字节对齐",
            "姓名槽读出的指针必须非 0 且 8 字节对齐",
            "指针目标必须可读（至少 1 字节）",
            "NestedString 解码结果必须非空，且只含字母/空格/撇号/连字符/句点",
            "出生日期必须能按 u32 规则解码，且年在 1900..2100、年内序日在 1..366",
        },
        Confidence: 0.0,
        Evidence: "docs/evidence/v3.2.8/PERSON-LAYOUT-CANDIDATES.md",
        VerificationStatus: CandidateVerificationStatus.Unverified);
}

/// <summary>单个候选字段的只读观测结果。</summary>
/// <param name="Kind">字段类型。</param>
/// <param name="Offset">相对 Person 指针的偏移。</param>
/// <param name="ReadType">读取方式（人类可读）。</param>
/// <param name="RawValue">原始值；读不到时为 <c>null</c>。</param>
/// <param name="DecodedValue">解码结果；失败时为 <c>null</c>。</param>
/// <param name="PointerValid">指针是否有效（仅姓名候选有意义）。</param>
/// <param name="StringValid">字符串是否有效（仅姓名候选有意义）。</param>
/// <param name="DateValid">日期是否有效（仅生日候选有意义）。</param>
/// <param name="FailureReason">失败原因码；成功时为 <c>null</c>。</param>
public sealed record PersonFieldObservation(
    CandidateFieldKind Kind,
    uint Offset,
    string ReadType,
    string? RawValue,
    string? DecodedValue,
    bool PointerValid,
    bool StringValid,
    bool DateValid,
    string? FailureReason)
{
    /// <summary>该字段是否有效（姓名看字符串，生日看日期）。</summary>
    public bool IsValid => Kind == CandidateFieldKind.NestedName ? StringValid : DateValid;
}

/// <summary>一个 Person 对象在某个候选布局下的完整观测结果。</summary>
/// <param name="CandidateId">候选标识。</param>
/// <param name="PersonPointer">Person 指针（仅本机诊断使用）。</param>
/// <param name="Fields">逐字段观测结果。</param>
/// <param name="Status">候选状态；本阶段最高只到 <see cref="CandidateVerificationStatus.StructurallyValid"/>。</param>
/// <param name="Note">补充说明。</param>
public sealed record PersonCandidateSnapshot(
    string CandidateId,
    ulong PersonPointer,
    IReadOnlyList<PersonFieldObservation> Fields,
    CandidateVerificationStatus Status,
    string? Note);
