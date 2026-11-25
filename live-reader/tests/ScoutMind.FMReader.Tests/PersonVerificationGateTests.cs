using System.Globalization;
using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Tests;

/// <summary>Mark(Verified) 安全门控与布局字段验证入口的单元测试。</summary>
internal static class PersonVerificationGateTests
{
    private static readonly DateTimeOffset ObservedAt =
        DateTimeOffset.Parse("2026-11-25T23:30:00+08:00", CultureInfo.InvariantCulture);

    public static void Run(TestHarness harness)
    {
        harness.Run("验证门控：没有人工确认时保持 HumanReviewPending", NoHumanConfirmation);
        harness.Run("验证门控：全部前置条件满足且人工确认后才 Verified", FullyVerified);
        harness.Run("验证门控：人工确认信息不完整仍保持 Pending", IncompleteConfirmation);
        harness.Run("验证门控：多候选为 Conflicted", MultipleCandidates);
        harness.Run("验证门控：身份冲突为 Conflicted", ConflictingIdentity);
        harness.Run("验证门控：无属性记录匹配为 Rejected", NoAttributeMatch);
        harness.Run("验证门控：读取不稳定为 Unstable 且不可 Verified", UnstableReads);
        harness.Run("验证门控：构建不匹配为 UnsupportedBuild", UnsupportedBuild);
        harness.Run("验证门控：姓名缺失为 Rejected", MissingName);
        harness.Run("验证门控：生日缺失为 Rejected，除非有批准策略", MissingBirthday);
        harness.Run("验证门控：没有属性记录关联最多到 StructurallyValid", MissingAttributeLink);
        harness.Run("验证门控：指针无效为 Rejected", InvalidPointer);
        harness.Run("验证门控：结构校验失败为 Rejected", InvalidStructure);
        harness.Run("验证审计：包含必需字段且不含内存地址", AuditLineIsCompleteAndSanitized);
        harness.Run("布局入口：Verified 必须来自 GameUiAgreement 且有证据", LayoutMarkRequiresEvidence);
    }

    private static void NoHumanConfirmation()
    {
        var decision = Evaluate(Request());
        TestHarness.Equal(PersonVerificationState.HumanReviewPending, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "未确认不得 Mark(Verified)");
        TestHarness.True(decision.Reasons.Contains("human_review_pending"), "应记录待人工确认");
    }

    private static void FullyVerified()
    {
        var decision = Evaluate(Request(humanConfirmed: true));
        TestHarness.Equal(PersonVerificationState.Verified, decision.State, "状态");
        TestHarness.True(decision.MarkVerified, "全部条件满足后允许 Mark(Verified)");
        TestHarness.Equal(0, decision.Reasons.Count, "不应有阻塞原因");
        TestHarness.True(decision.Audit.VerifiedFields.Contains("name"), "记录已验证姓名");
        TestHarness.True(decision.Audit.VerifiedFields.Contains("date_of_birth"), "记录已验证生日");
    }

    private static void IncompleteConfirmation()
    {
        var decision = Evaluate(Request(humanConfirmed: true, evidence: null));
        TestHarness.Equal(PersonVerificationState.HumanReviewPending, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "缺证据不得 Mark");
        TestHarness.True(decision.Reasons.Contains("human_confirmation_incomplete"), "应记录确认信息不完整");
    }

    private static void MultipleCandidates()
    {
        var decision = Evaluate(Request(humanConfirmed: true, linkStatus: AttributeLinkStatus.MultipleCandidates, compatibleCount: 2));
        TestHarness.Equal(PersonVerificationState.Conflicted, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "多候选不得 Mark");
        TestHarness.True(decision.Reasons.Contains("multiple_candidates"), "原因");
    }

    private static void ConflictingIdentity()
    {
        var decision = Evaluate(Request(humanConfirmed: true, linkStatus: AttributeLinkStatus.ConflictingIdentity, conflicts: 1));
        TestHarness.Equal(PersonVerificationState.Conflicted, decision.State, "状态");
        TestHarness.True(decision.Reasons.Contains("identity_conflict"), "原因");
    }

    private static void NoAttributeMatch()
    {
        var decision = Evaluate(Request(humanConfirmed: true, linkStatus: AttributeLinkStatus.NoMatch, compatibleCount: 0));
        TestHarness.Equal(PersonVerificationState.Rejected, decision.State, "状态");
        TestHarness.True(decision.Reasons.Contains("attribute_record_not_found"), "原因");
    }

    private static void UnstableReads()
    {
        var decision = Evaluate(Request(humanConfirmed: true, stable: false));
        TestHarness.Equal(PersonVerificationState.Unstable, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "不稳定不得 Mark");
        TestHarness.True(decision.Reasons.Contains("unstable_reads"), "原因");
    }

    private static void UnsupportedBuild()
    {
        var decision = Evaluate(Request(humanConfirmed: true, observedBuild: "26620375"));
        TestHarness.Equal(PersonVerificationState.UnsupportedBuild, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "构建不匹配不得 Mark");
    }

    private static void MissingName()
    {
        var decision = Evaluate(Request(humanConfirmed: true, name: null));
        TestHarness.Equal(PersonVerificationState.Rejected, decision.State, "状态");
        TestHarness.True(decision.Reasons.Contains("name_missing"), "原因");
    }

    private static void MissingBirthday()
    {
        var rejected = Evaluate(Request(humanConfirmed: true, dateOfBirth: null));
        TestHarness.Equal(PersonVerificationState.Rejected, rejected.State, "无替代策略时拒绝");
        TestHarness.True(rejected.Reasons.Contains("date_of_birth_missing"), "原因");

        var approved = Evaluate(Request(humanConfirmed: true, dateOfBirth: null, alternative: "approved-uid+name"));
        TestHarness.Equal(PersonVerificationState.Verified, approved.State, "批准策略下允许继续");
        TestHarness.True(approved.Warnings.Any(item => item.Contains("替代生日验证策略")), "应提示替代策略");
    }

    private static void MissingAttributeLink()
    {
        var decision = Evaluate(Request(humanConfirmed: true, withLink: false));
        TestHarness.Equal(PersonVerificationState.StructurallyValid, decision.State, "状态");
        TestHarness.True(!decision.MarkVerified, "无关联不得 Mark");
        TestHarness.True(decision.Reasons.Contains("attribute_link_missing"), "原因");
    }

    private static void InvalidPointer()
    {
        var decision = Evaluate(Request(humanConfirmed: true, pointer: false));
        TestHarness.Equal(PersonVerificationState.Rejected, decision.State, "状态");
        TestHarness.True(decision.Reasons.Contains("person_pointer_invalid"), "原因");
    }

    private static void InvalidStructure()
    {
        var decision = Evaluate(Request(humanConfirmed: true, structure: false));
        TestHarness.Equal(PersonVerificationState.Rejected, decision.State, "状态");
        TestHarness.True(decision.Reasons.Contains("structure_invalid"), "原因");
    }

    private static void AuditLineIsCompleteAndSanitized()
    {
        var decision = Evaluate(Request(humanConfirmed: true));
        var line = decision.Audit.ToJsonLine();

        TestHarness.Contains(line, "\"outcome\":\"Verified\"", "结果");
        TestHarness.Contains(line, "\"candidate_id\":\"fm27.1.person.2026-11-25\"", "候选");
        TestHarness.Contains(line, "\"layout_version\":\"27.1\"", "布局版本");
        TestHarness.Contains(line, "\"game_build\":\"26620374\"", "构建");
        TestHarness.Contains(line, "\"player_identity\"", "球员身份");
        TestHarness.Contains(line, "\"reviewer\":\"tester\"", "确认人");
        TestHarness.Contains(line, "\"mark_verified\":true", "Mark 结果");
        TestHarness.True(!line.Contains("0x", StringComparison.OrdinalIgnoreCase), "审计日志不得包含内存地址");
    }

    private static void LayoutMarkRequiresEvidence()
    {
        var layout = new FM27_1_Layout();
        TestHarness.Throws<ArgumentException>(
            () => layout.Mark("PLAO_CA", FieldStatus.Verified),
            "默认参数不得标为 Verified");
        TestHarness.Throws<ArgumentException>(
            () => layout.Mark("PLAO_CA", FieldStatus.Verified, EvidenceKind.InternalCheck, "internal"),
            "内部检查不得标为 Verified");
        TestHarness.Throws<ArgumentException>(
            () => layout.Mark("PLAO_CA", FieldStatus.Verified, EvidenceKind.GameUiAgreement),
            "缺少证据不得标为 Verified");

        layout.Mark("PLAO_CA", FieldStatus.Verified, EvidenceKind.GameUiAgreement, "FM27 界面核对");
        TestHarness.Equal(FieldStatus.Verified, layout.Verification("PLAO_CA").Status, "有界面证据后可 Verified");
    }

    private static PersonVerificationDecision Evaluate(PersonVerificationRequest request) =>
        new PersonVerificationGate().Evaluate(request);

    private static PersonVerificationRequest Request(
        bool humanConfirmed = false,
        string? reviewer = "tester",
        string? source = "fm27-ui",
        string? evidence = "docs/evidence/v3.2.8/HUMAN-REVIEW.md",
        AttributeLinkStatus linkStatus = AttributeLinkStatus.SingleCandidate,
        int compatibleCount = 1,
        int conflicts = 0,
        bool withLink = true,
        bool pointer = true,
        bool structure = true,
        string? name = "Dominic Calvert-Lewin",
        string? dateOfBirth = "1997-03-16",
        string? alternative = null,
        bool stable = true,
        int stableCount = 3,
        string observedBuild = "26620374",
        string expectedBuild = "26620374",
        bool buildSupported = true,
        bool layoutMatches = true) =>
        new(
            PersonLayoutCandidate.Fm27_1_20261125.CandidateId,
            "27.1",
            observedBuild,
            expectedBuild,
            buildSupported,
            layoutMatches,
            pointer,
            structure,
            name,
            ParseDate(dateOfBirth),
            alternative,
            150,
            withLink ? BuildLink(linkStatus, compatibleCount, conflicts) : null,
            stable,
            stableCount,
            0.5,
            humanConfirmed,
            reviewer,
            source,
            evidence,
            ObservedAt);

    private static AttributeLinkResult BuildLink(
        AttributeLinkStatus status,
        int compatibleCount,
        int conflicts)
    {
        var date = ParseDate("1997-03-16");
        var facts = new PlayerRecordFacts(
            0x1000,
            0x2000,
            "Dominic",
            "Calvert-Lewin",
            null,
            date,
            150,
            160,
            "Everton",
            1001,
            Array.Empty<string>());
        var candidate = new AttributeLinkCandidate(
            0x1000,
            facts,
            Array.Empty<LinkFieldComparison>(),
            Array.Empty<string>());
        var compatible = compatibleCount <= 0
            ? Array.Empty<AttributeLinkCandidate>()
            : Enumerable.Repeat(candidate, compatibleCount).ToArray();
        var conflictList = conflicts <= 0
            ? Array.Empty<AttributeLinkCandidate>()
            : Enumerable.Repeat(candidate, conflicts).ToArray();
        return new AttributeLinkResult(
            status,
            PersonIdentityFields.FromFacts(facts),
            compatible,
            Array.Empty<AttributeLinkCandidate>(),
            conflictList,
            Array.Empty<string>(),
            "test");
    }

    private static DateOnly? ParseDate(string? value) =>
        value is null ? null : DateOnly.ParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture);
}
