namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// Person 定位结果状态。
///
/// 关键规则：<see cref="Candidate"/> 不等于 <see cref="Verified"/>；定位器本身**永不**返回
/// <see cref="Verified"/>，人工核对与安全门控在更高层完成。
/// </summary>
public enum PersonCandidateStatus
{
    /// <summary>Person 指针为 0 或明显非法。</summary>
    InvalidPointer,

    /// <summary>对象头或字段不可读。</summary>
    UnreadableMemory,

    /// <summary>对象头存在，但 vtable 不在游戏模块内，判定为非对象。</summary>
    InvalidObject,

    /// <summary>找不到姓名。</summary>
    NameNotFound,

    /// <summary>读到了字符串，但不是合法姓名（乱码/控制字符/纯数字）。</summary>
    InvalidName,

    /// <summary>找不到出生日期。</summary>
    DateOfBirthNotFound,

    /// <summary>读到了出生日期原始值，但无法解码为合法日期。</summary>
    InvalidDateOfBirth,

    /// <summary>姓名与出生日期都通过内部校验；仍只是候选。</summary>
    Candidate,

    /// <summary>已在游戏界面人工核对通过（定位器不产生该状态）。</summary>
    Verified,
}

/// <summary>一次 Person 定位的候选结果。</summary>
/// <param name="CandidateId">候选布局标识。</param>
/// <param name="PersonPointer">Person 指针（仅本机诊断使用）。</param>
/// <param name="Status">定位状态。</param>
/// <param name="DisplayName">用于展示的姓名（common 优先，否则 first + second）。</param>
/// <param name="FirstName">名。</param>
/// <param name="SecondName">姓。</param>
/// <param name="CommonName">常用名。</param>
/// <param name="DateOfBirthRaw">出生日期原始 u32；读不到为 0。</param>
/// <param name="DateOfBirthYear">解码年份；无效为 0。</param>
/// <param name="DateOfBirthDayOfYear">解码年内序日；无效为 0。</param>
/// <param name="Fields">逐字段观测结果。</param>
/// <param name="FailureReason">失败原因码；成功时为 <c>null</c>。</param>
public sealed record PersonCandidate(
    string CandidateId,
    ulong PersonPointer,
    PersonCandidateStatus Status,
    string? DisplayName,
    string? FirstName,
    string? SecondName,
    string? CommonName,
    uint DateOfBirthRaw,
    int DateOfBirthYear,
    int DateOfBirthDayOfYear,
    IReadOnlyList<PersonFieldObservation> Fields,
    string? FailureReason)
{
    /// <summary>是否为可继续下游校验的候选（仍不是 Verified）。</summary>
    public bool IsCandidate => Status == PersonCandidateStatus.Candidate;
}
