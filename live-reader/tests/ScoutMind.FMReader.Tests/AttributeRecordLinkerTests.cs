using System.Globalization;
using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>Person → 属性记录关联器与字段快照读取器的单元测试（全部使用模拟内存）。</summary>
internal static class AttributeRecordLinkerTests
{
    public static void Run(TestHarness harness)
    {
        harness.Run("关联：唯一匹配为 SingleCandidate，不自动 Verified", SingleCandidate);
        harness.Run("关联：人工确认后才可能是 VerifiedMatch", VerifiedAfterHumanConfirmation);
        harness.Run("关联：多个候选为 MultipleCandidates 且不取第一个", MultipleCandidates);
        harness.Run("关联：同名不同生日为 ConflictingIdentity", SameNameDifferentBirthday);
        harness.Run("关联：仅名字相同不构成冲突", SameFirstNameIsNotConflict);
        harness.Run("关联：无匹配为 NoMatch", NoMatch);
        harness.Run("关联：目标身份不足为 RejectedMatch", RejectedTarget);
        harness.Run("关联：只有生日不足以建立关联", BirthdayOnlyTargetRejected);
        harness.Run("关联：UID 冲突保留证据", UidConflict);
        harness.Run("关联：俱乐部冲突保留证据", ClubConflict);
        harness.Run("关联：目标缺少生日时不能 Verified", TargetMissingBirthday);
        harness.Run("关联：姓名匹配忽略重音与大小写", AccentInsensitiveName);
        harness.Run("关联：候选缺少生日时不能 Verified", CandidateMissingBirthday);
        harness.Run("字段快照：完整记录读取姓名/生日/CA/PA/俱乐部/UID", FactsReaderReadsFields);
        harness.Run("字段快照：缺失俱乐部与 UID 不默认为 0", FactsReaderKeepsMissingFieldsNull);
        harness.Run("字段快照：不可读记录优雅失败", FactsReaderUnreadableRecord);
    }

    private static void SingleCandidate()
    {
        var result = Link(Target(), Facts(0x1000));
        TestHarness.Equal(AttributeLinkStatus.SingleCandidate, result.Status, "状态");
        TestHarness.Equal(1, result.CompatibleCandidates.Count, "候选数量");
        TestHarness.Equal("single_candidate_requires_human_review", result.Reason, "原因");
        TestHarness.Equal(0, result.MissingFields.Count, "完整字段不应有缺失");
    }

    private static void VerifiedAfterHumanConfirmation()
    {
        var result = Link(Target(), Facts(0x1000), humanConfirmed: true);
        TestHarness.Equal(AttributeLinkStatus.VerifiedMatch, result.Status, "人工确认后唯一匹配");
        TestHarness.Equal("human_confirmed_unique_match", result.Reason, "原因");
    }

    private static void MultipleCandidates()
    {
        var result = Link(Target(), Facts(0x1000), Facts(0x2000));
        TestHarness.Equal(AttributeLinkStatus.MultipleCandidates, result.Status, "状态");
        TestHarness.Equal(2, result.CompatibleCandidates.Count, "两个候选都要保留");
        TestHarness.Equal(0x1000uL, result.CompatibleCandidates[0].RecordPointer, "第一个候选");
        TestHarness.Equal(0x2000uL, result.CompatibleCandidates[1].RecordPointer, "第二个候选");
    }

    private static void SameNameDifferentBirthday()
    {
        var result = Link(Target(), Facts(0x1000), Facts(0x2000, dateOfBirth: "2000-09-14"));
        TestHarness.Equal(AttributeLinkStatus.ConflictingIdentity, result.Status, "同名不同生日必须冲突");
        TestHarness.Equal(1, result.RejectedCandidates.Count, "冲突证据要保留");
        TestHarness.Equal(1, result.Conflicts.Count, "应单独列出冲突候选");
        TestHarness.True(
            result.RejectedCandidates[0].Reasons.Contains("date_of_birth_mismatch"),
            "应记录生日不一致");
    }

    private static void SameFirstNameIsNotConflict()
    {
        var result = Link(
            Target(first: "Ahmed", second: "Rashid", club: null, uid: 1),
            Facts(0x1000, first: "Ahmed", second: "Al-Hosani", dateOfBirth: "1995-07-01", club: null, uid: 2));
        TestHarness.Equal(AttributeLinkStatus.NoMatch, result.Status, "仅名相同不应视为同名球员");
        TestHarness.Equal(0, result.Conflicts.Count, "不应产生冲突证据");
    }

    private static void NoMatch()
    {        var result = Link(
            Target(),
            Facts(0x1000, first: "Someone", second: "Else", dateOfBirth: "1980-01-01", club: "Other", uid: 2002));
        TestHarness.Equal(AttributeLinkStatus.NoMatch, result.Status, "状态");
        TestHarness.Equal("no_candidate_matched", result.Reason, "原因");
    }

    private static void RejectedTarget()
    {
        var result = Link(
            Target(first: null, second: null, common: null, dateOfBirth: null, club: null, uid: null),
            Facts(0x1000));
        TestHarness.Equal(AttributeLinkStatus.RejectedMatch, result.Status, "状态");
        TestHarness.Equal("target_identity_insufficient", result.Reason, "原因");
    }

    private static void BirthdayOnlyTargetRejected()
    {
        var result = Link(
            Target(first: null, second: null, common: null, club: null, uid: null),
            Facts(0x1000, club: null, uid: null));
        TestHarness.Equal(AttributeLinkStatus.RejectedMatch, result.Status, "只有生日不能建立关联");
        TestHarness.Equal("target_identity_insufficient", result.Reason, "原因");
    }

    private static void UidConflict()
    {
        var result = Link(Target(), Facts(0x1000, uid: 2002));
        TestHarness.Equal(AttributeLinkStatus.ConflictingIdentity, result.Status, "UID 冲突");
        TestHarness.True(
            result.RejectedCandidates[0].Reasons.Contains("uid_mismatch"),
            "应记录 UID 不一致");
    }

    private static void ClubConflict()
    {
        var result = Link(Target(), Facts(0x1000, club: "Chelsea"));
        TestHarness.Equal(AttributeLinkStatus.ConflictingIdentity, result.Status, "俱乐部冲突");
        TestHarness.True(
            result.RejectedCandidates[0].Reasons.Contains("club_mismatch"),
            "应记录俱乐部不一致");
    }

    private static void TargetMissingBirthday()
    {
        var result = Link(Target(dateOfBirth: null), Facts(0x1000), humanConfirmed: true);
        TestHarness.Equal(AttributeLinkStatus.SingleCandidate, result.Status, "缺生日不能 Verified");
        TestHarness.True(result.MissingFields.Contains("date_of_birth"), "应标记缺失生日");
    }

    private static void AccentInsensitiveName()
    {
        var result = Link(
            Target(first: "José", second: "Mário", club: null, uid: null),
            Facts(0x1000, first: "Jose", second: "Mario", club: null, uid: null));
        TestHarness.Equal(AttributeLinkStatus.SingleCandidate, result.Status, "重音差异不应阻断匹配");
        var name = result.CompatibleCandidates[0].Comparisons.Single(item => item.Field == "name");
        TestHarness.True(name.Matched, "姓名应匹配");
    }

    private static void CandidateMissingBirthday()
    {
        var result = Link(Target(), Facts(0x1000, dateOfBirth: null), humanConfirmed: true);
        TestHarness.Equal(AttributeLinkStatus.SingleCandidate, result.Status, "候选缺生日不能 Verified");
        TestHarness.True(result.MissingFields.Contains("date_of_birth"), "应标记缺失生日");
    }

    private static void FactsReaderReadsFields()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var record = FakeSave.WritePlayer(memory, layout, 0, ca: 151, pa: 162, birthYear: 2000, birthDoy: 40);
        var facts = new PlayerRecordFactsReader(memory, layout).Read(record);

        TestHarness.Equal("Test Player", facts.CommonName, "常用名");
        TestHarness.Equal(new DateOnly(2000, 2, 9), facts.DateOfBirth, "生日");
        TestHarness.Equal(151, facts.Ca, "CA");
        TestHarness.Equal(162, facts.Pa, "PA");
        TestHarness.Equal("Test FC", facts.ClubName, "俱乐部");
        TestHarness.Equal(9000u, facts.Uid, "UID");
        TestHarness.Equal(0, facts.MissingFields.Count, "完整记录不应有缺失");
    }

    private static void FactsReaderKeepsMissingFieldsNull()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var record = FakeSave.WritePlayer(memory, layout, 0);
        memory.WritePointer(record.Person + layout["PERO_FULL_CONTRACT"], 0);
        memory.WriteUInt32(record.Db + layout["OBJ_DUNI"], 0xFFFF_FFFF);

        var facts = new PlayerRecordFactsReader(memory, layout).Read(record);
        TestHarness.True(facts.ClubName is null, "俱乐部缺失必须保持 null");
        TestHarness.True(facts.Uid is null, "哨兵 UID 必须保持 null");
        TestHarness.True(facts.MissingFields.Contains("club"), "应标记缺失俱乐部");
        TestHarness.True(facts.MissingFields.Contains("uid"), "应标记缺失 UID");
        TestHarness.Equal(150, facts.Ca ?? 0, "CA 仍可读");
    }

    private static void FactsReaderUnreadableRecord()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var record = new LocatedObject(0x3000_0000, 0, 0x1000, 0x1800);
        var facts = new PlayerRecordFactsReader(memory, layout).Read(record);

        TestHarness.True(facts.DateOfBirth is null, "不可读生日保持 null");
        TestHarness.True(facts.Ca is null, "不可读 CA 保持 null");
        TestHarness.True(facts.MissingFields.Contains("date_of_birth"), "应标记缺失生日");
        TestHarness.True(facts.MissingFields.Contains("name"), "应标记缺失姓名");
    }

    private static AttributeLinkResult Link(
        PersonIdentityFields target,
        params PlayerRecordFacts[] records) =>
        new AttributeRecordLinker().Link(target, records);

    private static AttributeLinkResult Link(
        PersonIdentityFields target,
        PlayerRecordFacts record,
        bool humanConfirmed) =>
        new AttributeRecordLinker().Link(target, new[] { record }, humanConfirmed);

    private static PersonIdentityFields Target(
        string? first = "Dominic",
        string? second = "Calvert-Lewin",
        string? common = null,
        string? dateOfBirth = "1997-03-16",
        string? club = "Everton",
        uint? uid = 1001) =>
        new(first, second, common, ParseDate(dateOfBirth), club, uid);

    private static PlayerRecordFacts Facts(
        ulong record,
        string? first = "Dominic",
        string? second = "Calvert-Lewin",
        string? common = null,
        string? dateOfBirth = "1997-03-16",
        int? ca = 150,
        int? pa = 160,
        string? club = "Everton",
        uint? uid = 1001)
    {
        var missing = new List<string>();
        if (first is null && second is null && common is null)
        {
            missing.Add("name");
        }

        var date = ParseDate(dateOfBirth);
        if (date is null)
        {
            missing.Add("date_of_birth");
        }

        if (ca is null)
        {
            missing.Add("ca");
        }

        if (pa is null)
        {
            missing.Add("pa");
        }

        if (club is null)
        {
            missing.Add("club");
        }

        if (uid is null)
        {
            missing.Add("uid");
        }

        return new PlayerRecordFacts(
            record,
            record + 0x1000,
            first,
            second,
            common,
            date,
            ca,
            pa,
            club,
            uid,
            missing);
    }

    private static DateOnly? ParseDate(string? value) =>
        value is null ? null : DateOnly.ParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture);
}
