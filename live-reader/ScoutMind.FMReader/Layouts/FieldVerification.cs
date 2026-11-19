namespace ScoutMind.FMReader.Layouts;

/// <summary>
/// 证据种类。四种证据**不可混为一谈**：
/// 只有 <see cref="GameUiAgreement"/> 才能把字段标成 <see cref="FieldStatus.Verified"/>。
/// </summary>
public enum EvidenceKind
{
    /// <summary>没有任何外部依据。</summary>
    None = 0,

    /// <summary>只通过程序内部合理性检查（范围/指针/关系/跨字段）。</summary>
    InternalCheck = 1,

    /// <summary>与 FMSuperScout 的导出逐字段一致（同一存档、同一构建）。</summary>
    UpstreamAgreement = 2,

    /// <summary>与游戏界面显示一致（人工核对）。</summary>
    GameUiAgreement = 3,
}

/// <summary>一个偏移字段的验证状态。</summary>
public enum FieldStatus
{
    /// <summary>没有证据，或证据只来自内部检查。</summary>
    Pending,

    /// <summary>与 FMSuperScout 导出一致，但没在游戏界面核对。</summary>
    Candidate,

    /// <summary>已在游戏界面核对一致。</summary>
    Verified,

    /// <summary>探测或核对失败。</summary>
    Failed,

    /// <summary>当前布局没有该字段（例如租借关系）。</summary>
    NotSupported,
}

/// <summary>单个字段的验证记录。</summary>
/// <param name="Field">字段名。</param>
/// <param name="Status">状态。</param>
/// <param name="EvidenceKind">证据种类。</param>
/// <param name="Evidence">证据（谁、怎么核对的）。</param>
/// <param name="Note">补充说明。</param>
public sealed record FieldVerification(
    string Field,
    FieldStatus Status,
    EvidenceKind Kind = EvidenceKind.None,
    string? Evidence = null,
    string? Note = null);
