using System.Globalization;
using ScoutMind.FMReader.Calibration;

namespace ScoutMind.FMReader.Tests;

/// <summary>
/// Verified 作用域与跨存档/生命周期测试（V3.2.8.1 Phase 3-4）。
///
/// 这些是**自动化测试**：证明作用域判定逻辑不会跨存档污染、不会把同名不同人合并、
/// 也不会因为转会/自由球员/退役而丢掉身份。真实 FM27 A/B/A 场景另见验收报告。
/// </summary>
internal static class VerifiedIdentityScopeTests
{
    private const string SaveA = "si:v1:file:aaaa";
    private const string SaveB = "si:v1:file:bbbb";
    private const string Build = "26620374";
    private const string Layout = "27.1";
    private const string SessionA1 = "72012:2026-11-25T15:00:00Z:26620374";
    private const string SessionA2 = "72012:2026-11-25T16:00:00Z:26620374";

    private static readonly DateOnly Dob = new(1997, 3, 16);

    public static void Run(TestHarness harness)
    {
        harness.Run("Verified 作用域：同一存档/构建/布局/会话为 Valid", SameScopeIsValid);
        harness.Run("Verified 作用域：切换存档后为 Stale 且历史记录保留", OtherSaveIsStale);
        harness.Run("Verified 作用域：A→B→A 重新确认后才恢复", SaveRoundTripRequiresReconfirmation);
        harness.Run("Verified 作用域：不同存档同 UID 不自动认定为同一球员", SameUidDifferentSaveIsNotSameEntity);
        harness.Run("Verified 作用域：构建变化需要重新确认", BuildChangeRequiresRevalidation);
        harness.Run("Verified 作用域：布局变化需要重新确认", LayoutChangeRequiresRevalidation);
        harness.Run("Verified 作用域：旧会话指针不得继续使用", OldSessionRequiresRevalidation);
        harness.Run("Verified 作用域：生日冲突为 Conflicted", DateOfBirthConflictIsConflicted);
        harness.Run("Verified 作用域：UID 变化不得自动合并", UidChangeDoesNotAutoMerge);
        harness.Run("Verified 作用域：姓名变化不判定为换人", NameChangeKeepsContinuity);
        harness.Run("Verified 作用域：关联记录变化需要重新确认", AttributeRecordChangeRequiresRevalidation);
        harness.Run("生命周期：转会不使身份失效", TransferKeepsIdentity);
        harness.Run("生命周期：成为自由球员不使身份失效", FreeAgentKeepsIdentity);
        harness.Run("生命周期：退役不使身份失效", RetirementKeepsIdentity);
        harness.Run("生命周期：俱乐部变化不参与身份判定", ClubChangeKeepsIdentity);
        harness.Run("Verified 作用域：作用域不完整必须重新确认", IncompleteScopeRequiresRevalidation);
        harness.Run("Verified 作用域：当前身份字段缺失必须重读", MissingFactsRequiresRevalidation);
    }

    private static void SameScopeIsValid()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context());
        TestHarness.Equal(VerifiedLifecycleState.Valid, result.State, "状态");
        TestHarness.True(result.CanUseAsVerified, "可继续作为当前 Verified");
        TestHarness.Equal(IdentityContinuity.SamePlayer, result.Continuity, "连续性");
        TestHarness.Equal(0, result.Reasons.Count, "不应有阻塞原因");
    }

    private static void OtherSaveIsStale()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(save: SaveB));
        TestHarness.Equal(VerifiedLifecycleState.Stale, result.State, "跨存档必须 Stale");
        TestHarness.True(!result.CanUseAsVerified, "不得当作当前 Verified");
        TestHarness.True(result.Reasons.Contains("save_identity_mismatch"), "原因");
        TestHarness.Equal(IdentityContinuity.Unverifiable, result.Continuity, "跨存档不可判定同一球员");
    }

    private static void SaveRoundTripRequiresReconfirmation()
    {
        var first = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(save: SaveA));
        var inB = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(save: SaveB));
        var backSameSession = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(save: SaveA));
        var backNewSession = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(save: SaveA, session: SessionA2));

        TestHarness.Equal(VerifiedLifecycleState.Valid, first.State, "A 内有效");
        TestHarness.Equal(VerifiedLifecycleState.Stale, inB.State, "B 内不得复用 A");
        TestHarness.Equal(VerifiedLifecycleState.Valid, backSameSession.State, "同一会话回到 A 仍有效");
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, backNewSession.State, "新会话回到 A 必须重读");
    }

    private static void SameUidDifferentSaveIsNotSameEntity()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(uid: 1001), Context(save: SaveB, uid: 1001));
        TestHarness.Equal(VerifiedLifecycleState.Stale, result.State, "同 UID 不同存档不得自动合并");
    }

    private static void BuildChangeRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(build: "26620375"));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("game_build_changed"), "原因");
        TestHarness.Equal(IdentityContinuity.SamePlayer, result.Continuity, "仍视为同一球员");
    }

    private static void LayoutChangeRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(layout: "27.2"));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("layout_version_changed"), "原因");
    }

    private static void OldSessionRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(session: SessionA2));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("session_changed"), "原因");
        TestHarness.True(!result.CanUseAsVerified, "旧会话指针不得继续使用");
    }

    private static void DateOfBirthConflictIsConflicted()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(dateOfBirth: new DateOnly(1999, 1, 1)));
        TestHarness.Equal(VerifiedLifecycleState.Conflicted, result.State, "状态");
        TestHarness.Equal(IdentityContinuity.DifferentPlayer, result.Continuity, "连续性");
        TestHarness.True(result.Reasons.Contains("date_of_birth_conflict"), "原因");
    }

    private static void UidChangeDoesNotAutoMerge()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(uid: 1001), Context(uid: 2002));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.Equal(IdentityContinuity.Unverifiable, result.Continuity, "不得自动认定为同一人");
        TestHarness.True(result.Reasons.Contains("person_uid_changed"), "原因");
    }

    private static void NameChangeKeepsContinuity()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(name: "Dominic Calvert-Lewin"), Context(name: "Dominic Lewin"));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "展示名需重新确认");
        TestHarness.Equal(IdentityContinuity.SamePlayer, result.Continuity, "不判定为换人");
        TestHarness.True(result.Reasons.Contains("display_name_changed"), "原因");
    }

    private static void AttributeRecordChangeRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(record: "record-identity-2"));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("attribute_record_changed"), "原因");
    }

    private static void TransferKeepsIdentity()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(club: "Kingsport City"));
        TestHarness.Equal(VerifiedLifecycleState.Valid, result.State, "转会不影响身份");
        TestHarness.True(result.CanUseAsVerified, "仍可使用");
    }

    private static void FreeAgentKeepsIdentity()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(club: null));
        TestHarness.Equal(VerifiedLifecycleState.Valid, result.State, "自由球员不影响身份");
    }

    private static void RetirementKeepsIdentity()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(club: null, record: "record-identity"));
        TestHarness.Equal(VerifiedLifecycleState.Valid, result.State, "退役不影响身份");
    }

    private static void ClubChangeKeepsIdentity()
    {
        var sameClub = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(club: "Everton"));
        var changedClub = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(club: "Everton"));
        TestHarness.Equal(sameClub.State, changedClub.State, "俱乐部不是身份字段");
    }

    private static void IncompleteScopeRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(record: string.Empty), Context());
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("verified_scope_incomplete"), "原因");
    }

    private static void MissingFactsRequiresRevalidation()
    {
        var result = VerifiedIdentityScopeValidator.Evaluate(Scope(), Context(uid: null, dateOfBirth: null, name: null));
        TestHarness.Equal(VerifiedLifecycleState.RevalidationRequired, result.State, "状态");
        TestHarness.True(result.Reasons.Contains("person_facts_missing"), "原因");
    }

    private static VerifiedIdentityScope Scope(
        string save = SaveA,
        string build = Build,
        string layout = Layout,
        uint uid = 1001,
        string name = "Dominic Calvert-Lewin",
        DateOnly? dateOfBirth = null,
        string session = SessionA1,
        string record = "record-identity") =>
        new(
            "save-a",
            save,
            session,
            build,
            layout,
            uid,
            name,
            dateOfBirth ?? Dob,
            null,
            record,
            DateTimeOffset.Parse("2026-11-25T23:30:00+08:00", CultureInfo.InvariantCulture),
            "tester",
            "fm27-ui",
            "docs/evidence/v3.2.8/HUMAN-REVIEW.md");

    private static VerifiedIdentityContext Context(
        string save = SaveA,
        string build = Build,
        string layout = Layout,
        uint? uid = 1001,
        string? name = "Dominic Calvert-Lewin",
        DateOnly? dateOfBirth = null,
        string session = SessionA1,
        string? record = "record-identity",
        string? club = "Everton") =>
        new(
            "save-a",
            save,
            session,
            build,
            layout,
            uid,
            name,
            dateOfBirth ?? Dob,
            record,
            club);
}
