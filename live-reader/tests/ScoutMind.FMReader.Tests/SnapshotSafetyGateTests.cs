using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>自动快照安全门：默认必须 BLOCKED，只有全部硬性条件成立才 ENABLED。</summary>
public static class SnapshotSafetyGateTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("安全门：默认证据不足时保持 BLOCKED", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input());

            TestHarness.Equal("BLOCKED", decision.Status, "默认必须 BLOCKED");
            TestHarness.True(decision.Reasons.Count > 0, "必须给出逐条原因");
        });

        harness.Run("安全门：仅 session_verified 仍不足", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input(confidence: DateConfidenceLevel.SessionVerified));

            TestHarness.Equal("BLOCKED", decision.Status, "会话验证不足以自动快照");
            TestHarness.True(
                decision.Reasons.Any(reason => reason.Contains("restart_verified", StringComparison.Ordinal)),
                "应说明未达到 restart_verified");
        });

        harness.Run("安全门：存档身份未知时即使 restart_verified 也 BLOCKED", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input(confidence: DateConfidenceLevel.RestartVerified));

            TestHarness.Equal("BLOCKED", decision.Status, "存档身份缺失必须阻止自动快照");
            TestHarness.True(
                decision.Reasons.Any(reason => reason.Contains("存档身份", StringComparison.Ordinal)),
                "应说明存档身份未验证");
        });

        harness.Run("安全门：全部条件成立才 ENABLED", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input(
                confidence: DateConfidenceLevel.RestartVerified,
                saveIdentityValid: true));

            TestHarness.Equal("ENABLED", decision.Status, "全部条件成立才允许");
            TestHarness.True(decision.Allowed, "应允许自动快照");
            TestHarness.Equal(0, decision.Reasons.Count, "允许时不应有原因");
        });

        harness.Run("诊断报告：跨进程验证通过但存档身份未知时仍 BLOCKED", () =>
        {
            var memory = DateCandidateDiagnosticsTests.CreateMemory();
            DateCandidateDiagnosticsTests.WriteRecord(
                memory, 0x3000_0100, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0xA1);
            var visible = new DateOnly(2026, 11, 6);

            var state = DateVerificationState.Empty;
            for (var index = 0; index < 2; index++)
            {
                var collection = WorldDateCandidateCollector.Collect(memory, 0x4000);
                var step = DateCandidateTracker.Observe(
                    DateCandidateDiagnosticsTests.Session($"s{index}"),
                    null,
                    visible,
                    collection,
                    state,
                    DateCandidateDiagnosticsTests.Now.AddMinutes(index * 5));
                state = step.State;
            }

            var outcome = WorldDateDiagnostics.Analyze(
                memory,
                DateCandidateDiagnosticsTests.Session("s2"),
                visible,
                saveKey: null,
                state,
                maxBytes: 0x4000,
                now: DateCandidateDiagnosticsTests.Now.AddMinutes(10));

            TestHarness.Equal("restart_verified", outcome.Report.Status, "第三次会话应达到 restart_verified");
            TestHarness.Equal("BLOCKED", outcome.Report.Snapshot.Status, "存档身份未知时仍必须 BLOCKED");
            TestHarness.True(
                outcome.Report.Snapshot.Reasons.Any(reason => reason.Contains("存档身份", StringComparison.Ordinal)),
                "原因中应包含存档身份");
        });
        harness.Run("安全门：自动快照总开关关闭时即使身份 verified 也 BLOCKED", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input(
                confidence: DateConfidenceLevel.RestartVerified,
                saveIdentityValid: true,
                identity: Identity(
                    SaveIdentityStatus.Verified,
                    snapshotEligible: true,
                    automaticSnapshotEnabled: false)));

            TestHarness.Equal("BLOCKED", decision.Status, "V3.2.7 不开放自动快照");
            TestHarness.True(
                decision.Reasons.Any(reason => reason.Contains("automatic_snapshot_enabled", StringComparison.Ordinal)),
                "应说明自动快照开关关闭");
        });

        harness.Run("安全门：身份仅 candidate 时 BLOCKED", () =>
        {
            var decision = SnapshotSafetyGate.Evaluate(Input(
                confidence: DateConfidenceLevel.RestartVerified,
                saveIdentityValid: false,
                identity: Identity(SaveIdentityStatus.Candidate, snapshotEligible: false)));

            TestHarness.Equal("BLOCKED", decision.Status, "candidate 不得放行");
            TestHarness.True(
                decision.Reasons.Any(reason => reason.Contains("candidate", StringComparison.Ordinal)),
                "应说明身份状态为 candidate");
        });

        harness.Run("安全门：身份冲突或缺少会话时 BLOCKED", () =>
        {
            var conflicted = SnapshotSafetyGate.Evaluate(Input(
                confidence: DateConfidenceLevel.RestartVerified,
                saveIdentityValid: true,
                identity: Identity(
                    SaveIdentityStatus.Verified,
                    snapshotEligible: true,
                    automaticSnapshotEnabled: true,
                    conflicts: new[] { "两个存档文件都声称自己是当前存档" })));
            var noSession = SnapshotSafetyGate.Evaluate(Input(
                confidence: DateConfidenceLevel.RestartVerified,
                saveIdentityValid: true,
                identity: Identity(
                    SaveIdentityStatus.Verified,
                    snapshotEligible: true,
                    automaticSnapshotEnabled: true,
                    sessionKey: null)));

            TestHarness.Equal("BLOCKED", conflicted.Status, "冲突必须阻止");
            TestHarness.True(
                conflicted.Reasons.Any(reason => reason.Contains("冲突", StringComparison.Ordinal)),
                "应说明冲突");
            TestHarness.Equal("BLOCKED", noSession.Status, "缺少会话必须阻止");
            TestHarness.True(
                noSession.Reasons.Any(reason => reason.Contains("会话标识", StringComparison.Ordinal)),
                "应说明缺少会话");
        });

        harness.Run("安全门：身份事实来自解析结果时 snapshot_eligible 恒为 false", () =>
        {
            var facts = SnapshotIdentityFacts.From(new SaveIdentityResolution(
                SaveIdentityStatus.Verified,
                SaveIdentityConfidence.Verified,
                "si:v1:file:abc",
                SaveIdentityKind.SaveFile,
                "4242:start:26577676",
                "26577676",
                "27.1.0",
                Array.Empty<SaveEvidence>(),
                Array.Empty<SaveEvidenceType>(),
                Array.Empty<string>(),
                new[] { "测试用解析结果。" },
                false,
                false));

            TestHarness.True(facts is not null, "应能映射");
            TestHarness.True(!facts!.SnapshotEligible, "总开关关闭时 eligible 必须为 false");
            TestHarness.True(!facts.AutomaticSnapshotEnabled, "本版本自动快照必须关闭");
        });

    }

    private static SnapshotIdentityFacts Identity(
        SaveIdentityStatus status,
        bool snapshotEligible,
        bool automaticSnapshotEnabled = false,
        string? sessionKey = "4242:start:26577676",
        IReadOnlyList<string>? conflicts = null) => new(
        status,
        status == SaveIdentityStatus.Verified ? SaveIdentityConfidence.Verified : SaveIdentityConfidence.Medium,
        "si:v1:file:abc",
        sessionKey,
        "26577676",
        snapshotEligible,
        automaticSnapshotEnabled,
        conflicts ?? Array.Empty<string>());

    private static SnapshotSafetyInput Input(
        DateConfidenceLevel confidence = DateConfidenceLevel.Heuristic,
        bool saveIdentityValid = false,
        SnapshotIdentityFacts? identity = null) => new(
        DateAvailable: true,
        CandidateUnambiguous: true,
        Confidence: confidence,
        ProcessSessionValid: true,
        SaveIdentityValid: saveIdentityValid,
        ReaderVersionSupported: true,
        DateSourceValid: true,
        Identity: identity);
}
