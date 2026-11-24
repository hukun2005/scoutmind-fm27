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
    }

    private static SnapshotSafetyInput Input(
        DateConfidenceLevel confidence = DateConfidenceLevel.Heuristic,
        bool saveIdentityValid = false) => new(
        DateAvailable: true,
        CandidateUnambiguous: true,
        Confidence: confidence,
        ProcessSessionValid: true,
        SaveIdentityValid: saveIdentityValid,
        ReaderVersionSupported: true,
        DateSourceValid: true);
}
