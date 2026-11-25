using System.Globalization;
using System.Text;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// Person 与属性记录的关联结果状态。
///
/// 关键规则：<see cref="MultipleCandidates"/> 与 <see cref="ConflictingIdentity"/> 都**不允许**自动挑选一个结果；
/// <see cref="VerifiedMatch"/> 只表示字段级唯一匹配，不等于 Mark(Verified)（后者还需要 Phase 5 的人工核对门控）。
/// </summary>
public enum AttributeLinkStatus
{
    /// <summary>没有字段可比的记录。</summary>
    NoMatch,

    /// <summary>恰好一个候选，且没有冲突证据。</summary>
    SingleCandidate,

    /// <summary>多个候选；禁止自动选择第一个。</summary>
    MultipleCandidates,

    /// <summary>存在身份冲突证据（同名不同生日/俱乐部/UID，或候选之间存在互斥证据）。</summary>
    ConflictingIdentity,

    /// <summary>字段级唯一匹配，且调用方明确声明已人工确认。</summary>
    VerifiedMatch,

    /// <summary>目标本身身份字段不足，无法关联。</summary>
    RejectedMatch,
}

/// <summary>用于关联的目标身份字段（来自 Person 对象）。</summary>
/// <param name="FirstName">名。</param>
/// <param name="SecondName">姓。</param>
/// <param name="CommonName">常用名。</param>
/// <param name="DateOfBirth">出生日期；未知为 <c>null</c>。</param>
/// <param name="ClubName">俱乐部；未知为 <c>null</c>。</param>
/// <param name="Uid">UID；未知为 <c>null</c>。</param>
public sealed record PersonIdentityFields(
    string? FirstName,
    string? SecondName,
    string? CommonName,
    DateOnly? DateOfBirth,
    string? ClubName,
    uint? Uid)
{
    /// <summary>从属性记录快照构造目标身份。</summary>
    /// <param name="facts">记录快照。</param>
    /// <returns>目标身份。</returns>
    public static PersonIdentityFields FromFacts(PlayerRecordFacts facts)
    {
        ArgumentNullException.ThrowIfNull(facts);
        return new PersonIdentityFields(
            facts.FirstName,
            facts.SecondName,
            facts.CommonName,
            facts.DateOfBirth,
            facts.ClubName,
            facts.Uid);
    }
}

/// <summary>单个字段的比较证据。</summary>
/// <param name="Field">字段代码（<c>name</c>/<c>date_of_birth</c>/<c>club</c>/<c>uid</c>）。</param>
/// <param name="TargetValue">目标值。</param>
/// <param name="CandidateValue">候选值。</param>
/// <param name="Applicable">双方都有值、可以比较。</param>
/// <param name="Matched">可比较且一致。</param>
public sealed record LinkFieldComparison(
    string Field,
    string? TargetValue,
    string? CandidateValue,
    bool Applicable,
    bool Matched);

/// <summary>一个属性记录候选及其比较证据。</summary>
/// <param name="RecordPointer">记录地址（仅本机诊断）。</param>
/// <param name="Facts">记录快照。</param>
/// <param name="Comparisons">逐字段比较。</param>
/// <param name="Reasons">候选被排除的原因码。</param>
public sealed record AttributeLinkCandidate(
    ulong RecordPointer,
    PlayerRecordFacts Facts,
    IReadOnlyList<LinkFieldComparison> Comparisons,
    IReadOnlyList<string> Reasons);

/// <summary>关联结果。</summary>
/// <param name="Status">关联状态。</param>
/// <param name="Target">目标身份。</param>
/// <param name="CompatibleCandidates">所有兼容候选（多个时禁止自动取第一个）。</param>
/// <param name="RejectedCandidates">被排除的候选（保留冲突证据）。</param>
/// <param name="Conflicts">姓名一致但其它字段冲突的候选（冲突证据）。</param>
/// <param name="MissingFields">目标或唯一候选缺失的字段。</param>
/// <param name="Reason">结论原因码。</param>
public sealed record AttributeLinkResult(
    AttributeLinkStatus Status,
    PersonIdentityFields Target,
    IReadOnlyList<AttributeLinkCandidate> CompatibleCandidates,
    IReadOnlyList<AttributeLinkCandidate> RejectedCandidates,
    IReadOnlyList<AttributeLinkCandidate> Conflicts,
    IReadOnlyList<string> MissingFields,
    string Reason);

/// <summary>
/// Person → 属性记录的多字段关联器（路线 A）。
///
/// 只做字段比较，不读内存；所有数据由调用方以只读快照传入。
/// 字段可用性完全取决于真实快照：缺失字段不参与匹配，也不会被默认为 0。
/// </summary>
public sealed class AttributeRecordLinker
{
    /// <summary>执行关联。</summary>
    /// <param name="target">目标身份。</param>
    /// <param name="records">候选属性记录。</param>
    /// <param name="humanConfirmed">是否已人工确认唯一候选（只有为 <c>true</c> 才可能返回 VerifiedMatch）。</param>
    /// <returns>关联结果。</returns>
    public AttributeLinkResult Link(
        PersonIdentityFields target,
        IReadOnlyList<PlayerRecordFacts> records,
        bool humanConfirmed = false)
    {
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(records);

        var targetKeys = NameKeys(target.FirstName, target.SecondName, target.CommonName);
        var targetMissing = TargetMissingFields(target, targetKeys);
        if (targetKeys.Count == 0 && target.Uid is null)
        {
            return new AttributeLinkResult(
                AttributeLinkStatus.RejectedMatch,
                target,
                Array.Empty<AttributeLinkCandidate>(),
                Array.Empty<AttributeLinkCandidate>(),
                Array.Empty<AttributeLinkCandidate>(),
                targetMissing,
                "target_identity_insufficient");
        }

        var compatible = new List<AttributeLinkCandidate>();
        var rejected = new List<AttributeLinkCandidate>();
        var conflicts = new List<AttributeLinkCandidate>();
        foreach (var record in records)
        {
            var candidate = Compare(target, targetKeys, record);
            var mismatched = candidate.Comparisons.Any(item => item.Applicable && !item.Matched);
            // 只有姓名或 UID 能构成强匹配；生日单独命中不足以建立关联。
            var strongMatch = candidate.Comparisons.Any(item =>
                item.Applicable && item.Matched
                && item.Field is "name" or "uid");
            if (!mismatched && strongMatch)
            {
                compatible.Add(candidate);
                continue;
            }

            rejected.Add(candidate);
            var nameMatched = candidate.Comparisons.Any(item =>
                item.Field == "name" && item.Applicable && item.Matched);
            if (nameMatched && mismatched)
            {
                conflicts.Add(candidate);
            }
        }

        if (compatible.Count == 0)
        {
            var status = conflicts.Count > 0
                ? AttributeLinkStatus.ConflictingIdentity
                : AttributeLinkStatus.NoMatch;
            return new AttributeLinkResult(
                status,
                target,
                Array.Empty<AttributeLinkCandidate>(),
                rejected,
                conflicts,
                targetMissing,
                conflicts.Count > 0 ? "same_name_conflicting_fields" : "no_candidate_matched");
        }

        if (compatible.Count > 1)
        {
            return new AttributeLinkResult(
                AttributeLinkStatus.MultipleCandidates,
                target,
                compatible,
                rejected,
                conflicts,
                targetMissing,
                "multiple_candidates_require_human_review");
        }

        var single = compatible[0];
        if (conflicts.Count > 0)
        {
            return new AttributeLinkResult(
                AttributeLinkStatus.ConflictingIdentity,
                target,
                compatible,
                rejected,
                conflicts,
                UnionMissing(targetMissing, single.Facts.MissingFields),
                "candidate_conflicts_with_same_name_records");
        }

        var nameMatchedForSingle = single.Comparisons.Any(item =>
            item.Field == "name" && item.Applicable && item.Matched);
        var dobMatchedForSingle = single.Comparisons.Any(item =>
            item.Field == "date_of_birth" && item.Applicable && item.Matched);
        var canVerify = humanConfirmed && nameMatchedForSingle && dobMatchedForSingle
                        && target.DateOfBirth is not null && single.Facts.DateOfBirth is not null;
        return new AttributeLinkResult(
            canVerify ? AttributeLinkStatus.VerifiedMatch : AttributeLinkStatus.SingleCandidate,
            target,
            new[] { single },
            rejected,
            conflicts,
            UnionMissing(targetMissing, single.Facts.MissingFields),
            canVerify ? "human_confirmed_unique_match" : "single_candidate_requires_human_review");
    }

    private static AttributeLinkCandidate Compare(
        PersonIdentityFields target,
        IReadOnlySet<string> targetKeys,
        PlayerRecordFacts record)
    {
        var comparisons = new List<LinkFieldComparison>(4);
        var reasons = new List<string>();

        var candidateKeys = NameKeys(record.FirstName, record.SecondName, record.CommonName);
        var nameApplicable = targetKeys.Count > 0 && candidateKeys.Count > 0;
        var nameMatched = nameApplicable && targetKeys.Overlaps(candidateKeys);
        comparisons.Add(new LinkFieldComparison(
            "name",
            JoinKeys(targetKeys),
            JoinKeys(candidateKeys),
            nameApplicable,
            nameMatched));
        if (!nameApplicable)
        {
            reasons.Add(candidateKeys.Count == 0 ? "candidate_missing_name" : "target_missing_name");
        }
        else if (!nameMatched)
        {
            reasons.Add("name_mismatch");
        }

        var dobApplicable = target.DateOfBirth is not null && record.DateOfBirth is not null;
        var dobMatched = dobApplicable && target.DateOfBirth == record.DateOfBirth;
        comparisons.Add(new LinkFieldComparison(
            "date_of_birth",
            FormatDate(target.DateOfBirth),
            FormatDate(record.DateOfBirth),
            dobApplicable,
            dobMatched));
        if (!dobApplicable)
        {
            reasons.Add(record.DateOfBirth is null ? "candidate_missing_date_of_birth" : "target_missing_date_of_birth");
        }
        else if (!dobMatched)
        {
            reasons.Add("date_of_birth_mismatch");
        }

        var clubApplicable = !string.IsNullOrWhiteSpace(target.ClubName)
                             && !string.IsNullOrWhiteSpace(record.ClubName);
        var clubMatched = clubApplicable
                          && string.Equals(
                              Normalize(target.ClubName!),
                              Normalize(record.ClubName!),
                              StringComparison.Ordinal);
        comparisons.Add(new LinkFieldComparison(
            "club",
            target.ClubName,
            record.ClubName,
            clubApplicable,
            clubMatched));
        if (!clubApplicable)
        {
            reasons.Add(record.ClubName is null ? "candidate_missing_club" : "target_missing_club");
        }
        else if (!clubMatched)
        {
            reasons.Add("club_mismatch");
        }

        var uidApplicable = target.Uid is not null && record.Uid is not null;
        var uidMatched = uidApplicable && target.Uid == record.Uid;
        comparisons.Add(new LinkFieldComparison(
            "uid",
            target.Uid?.ToString(CultureInfo.InvariantCulture),
            record.Uid?.ToString(CultureInfo.InvariantCulture),
            uidApplicable,
            uidMatched));
        if (!uidApplicable)
        {
            reasons.Add(record.Uid is null ? "candidate_missing_uid" : "target_missing_uid");
        }
        else if (!uidMatched)
        {
            reasons.Add("uid_mismatch");
        }

        return new AttributeLinkCandidate(record.RecordPointer, record, comparisons, reasons);
    }

    private static IReadOnlyList<string> TargetMissingFields(
        PersonIdentityFields target,
        IReadOnlySet<string> keys)
    {
        var missing = new List<string>(4);
        if (keys.Count == 0)
        {
            missing.Add("name");
        }

        if (target.DateOfBirth is null)
        {
            missing.Add("date_of_birth");
        }

        if (string.IsNullOrWhiteSpace(target.ClubName))
        {
            missing.Add("club");
        }

        if (target.Uid is null)
        {
            missing.Add("uid");
        }

        return missing;
    }

    private static IReadOnlyList<string> UnionMissing(
        IReadOnlyList<string> first,
        IReadOnlyList<string> second)
    {
        var union = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var item in first)
        {
            union.Add(item);
        }

        foreach (var item in second)
        {
            union.Add(item);
        }

        return union.ToArray();
    }

    private static string? JoinKeys(IReadOnlySet<string> keys) =>
        keys.Count == 0 ? null : string.Join(" / ", keys.OrderBy(key => key, StringComparer.Ordinal));

    private static string? FormatDate(DateOnly? value) =>
        value?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

    private static IReadOnlySet<string> NameKeys(string? first, string? second, string? common)
    {
        var keys = new HashSet<string>(StringComparer.Ordinal);
        Add(common);

        // 只有"名 + 姓"都齐全时才使用完整组合；不使用单个词作为键，
        // 否则 "Ahmed Rashid" 会与 "Ahmed Al-Hosani" 这类同名词误判为同名球员。
        if (!string.IsNullOrWhiteSpace(first) && !string.IsNullOrWhiteSpace(second))
        {
            Add($"{first} {second}");
            Add($"{second} {first}");
        }
        else
        {
            Add(first);
            Add(second);
        }

        return keys;

        void Add(string? value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return;
            }

            var normalized = Normalize(value);
            if (normalized.Length > 0)
            {
                keys.Add(normalized);
            }
        }
    }

    /// <summary>归一化：去首尾空白、折叠空白、忽略重音与大小写。</summary>
    private static string Normalize(string value)
    {
        var decomposed = value.Trim().Normalize(NormalizationForm.FormD);
        var builder = new StringBuilder(decomposed.Length);
        var previousSpace = false;
        foreach (var ch in decomposed)
        {
            if (CharUnicodeInfo.GetUnicodeCategory(ch) == UnicodeCategory.NonSpacingMark)
            {
                continue;
            }

            if (char.IsWhiteSpace(ch))
            {
                if (!previousSpace && builder.Length > 0)
                {
                    builder.Append(' ');
                }

                previousSpace = true;
                continue;
            }

            previousSpace = false;
            builder.Append(char.ToLowerInvariant(ch));
        }

        return builder.ToString().TrimEnd().Normalize(NormalizationForm.FormC);
    }
}
