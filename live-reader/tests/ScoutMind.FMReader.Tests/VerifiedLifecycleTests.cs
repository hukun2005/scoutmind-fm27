using ScoutMind.FMReader.Calibration;

namespace ScoutMind.FMReader.Tests;

/// <summary>
/// V3.2.9.2 阶段 2：Verified 生命周期不变量。
///
/// 覆盖：重复 Verify 幂等、切档/重启失效、generation 过期拒绝提交、不同存档互不覆盖、
/// 旧任务不得污染新状态、无证据不能 Verified、撤销后旧任务不能恢复、未知状态不显示成功、
/// 历史可追溯。
/// </summary>
public static class VerifiedLifecycleTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 26, 9, 0, 0, TimeSpan.Zero);

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("生命周期：同一作用域重复 Verify 幂等", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var attempt = ledger.Begin();
            var evidence = Evidence("si:v1:file:A", 101, "digest-1");

            var first = ledger.Commit(attempt, evidence);
            var second = ledger.Commit(attempt, evidence);

            TestHarness.Equal(VerificationCommitOutcome.Applied, first.Outcome, "首次应写入");
            TestHarness.Equal(VerificationCommitOutcome.Duplicate, second.Outcome, "重复应幂等");
            TestHarness.Equal(1, ledger.History.Count, "幂等不得新增历史");
            TestHarness.Equal(first.Record!.Sequence, second.Record!.Sequence, "应返回同一条记录");
        });

        harness.Run("生命周期：存档切换使旧 Verified 失效且记录原因", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            ledger.Commit(ledger.Begin(), Evidence("si:v1:file:A", 101, "digest-1"));

            var generation = ledger.AdvanceGeneration("save_identity_changed");

            TestHarness.Equal(null, ledger.Active("si:v1:file:A", 101), "旧存档不得保留有效 Verified");
            TestHarness.Equal(2, generation, "切档必须推进 generation");
            var last = ledger.History[^1];
            TestHarness.Equal(VerificationState.Invalidated, last.State, "必须追加失效记录");
            TestHarness.Equal("save_identity_changed", last.Reason, "必须记录失效原因");
        });

        harness.Run("生命周期：进程重启后必须重新验证", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            ledger.Commit(ledger.Begin(), Evidence("si:v1:file:A", 101, "digest-1"));

            ledger.AdvanceGeneration("session_changed");

            TestHarness.Equal(null, ledger.Active("si:v1:file:A", 101), "旧会话 Verified 必须失效");
            TestHarness.True(ledger.History.Any(row => row.Reason == "session_changed"), "必须记录会话变化原因");
        });

        harness.Run("生命周期：generation 不一致时拒绝提交", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var stale = ledger.Begin();
            ledger.AdvanceGeneration("save_identity_changed");

            var result = ledger.Commit(stale, Evidence("si:v1:file:A", 101, "digest-1"));

            TestHarness.Equal(VerificationCommitOutcome.StaleGeneration, result.Outcome, "旧代次必须被拒绝");
            TestHarness.Equal(0, ledger.History.Count, "旧任务不得写入任何记录");
        });

        harness.Run("生命周期：不同存档的 Verify 不互相覆盖", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var attempt = ledger.Begin();
            ledger.Commit(attempt, Evidence("si:v1:file:A", 101, "digest-a"));
            ledger.Commit(attempt, Evidence("si:v1:file:B", 101, "digest-b"));

            TestHarness.Equal(VerificationState.Verified, ledger.Active("si:v1:file:A", 101)!.State, "A 存档必须保持有效");
            TestHarness.Equal(VerificationState.Verified, ledger.Active("si:v1:file:B", 101)!.State, "B 存档必须独立有效");
        });

        harness.Run("生命周期：旧任务晚到不得污染新状态", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var oldTask = ledger.Begin();
            ledger.AdvanceGeneration("save_identity_changed");
            var newTask = ledger.Begin();
            ledger.Commit(newTask, Evidence("si:v1:file:B", 101, "digest-b"));

            var late = ledger.Commit(oldTask, Evidence("si:v1:file:A", 101, "digest-a"));

            TestHarness.Equal(VerificationCommitOutcome.StaleGeneration, late.Outcome, "旧任务必须被丢弃");
            TestHarness.Equal(null, ledger.Active("si:v1:file:A", 101), "旧任务不得恢复 A");
            TestHarness.Equal(VerificationState.Verified, ledger.Active("si:v1:file:B", 101)!.State, "新状态必须保留");
        });

        harness.Run("生命周期：无证据不能 Verified", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var incomplete = Evidence("si:v1:file:A", 101, "digest-1") with { EvidenceDigest = string.Empty };

            var result = ledger.Commit(ledger.Begin(), incomplete);

            TestHarness.Equal(VerificationCommitOutcome.InsufficientEvidence, result.Outcome, "缺证据必须拒绝");
            TestHarness.Equal(0, ledger.History.Count, "不得写入 Verified");
        });

        harness.Run("生命周期：已撤销 Verified 不能被旧任务恢复", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var oldTask = ledger.Begin();
            ledger.Commit(oldTask, Evidence("si:v1:file:A", 101, "digest-1"));

            TestHarness.True(ledger.Revoke("si:v1:file:A", 101, "admin_revoked"), "撤销应成功");
            var restored = ledger.Commit(oldTask, Evidence("si:v1:file:A", 101, "digest-1"));

            TestHarness.Equal(VerificationCommitOutcome.StaleGeneration, restored.Outcome, "撤销必须使旧令牌过期");
            TestHarness.Equal(null, ledger.Active("si:v1:file:A", 101), "不得恢复被撤销的 Verified");
            TestHarness.True(
                ledger.History.Any(row => row.State == VerificationState.Invalidated && row.Reason == "admin_revoked"),
                "撤销必须留下历史");
        });

        harness.Run("生命周期：未知状态不得显示为成功", () =>
        {
            TestHarness.True(VerificationStateText.IsSuccess("verified"), "verified 才是成功");
            TestHarness.True(!VerificationStateText.IsSuccess("whatever"), "未知状态不能是成功");
            TestHarness.True(!VerificationStateText.IsSuccess(null), "空状态不能是成功");
            TestHarness.Equal("unknown", VerificationStateText.ToApiText((VerificationState)999), "未知状态必须序列化为 unknown");
        });

        harness.Run("生命周期：并发提交同一作用域只产生一条 Verified", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            var attempt = ledger.Begin();
            var evidence = Evidence("si:v1:file:A", 101, "digest-1");
            var results = new VerificationCommitResult[32];

            Parallel.For(0, results.Length, index => results[index] = ledger.Commit(attempt, evidence));

            TestHarness.Equal(
                1,
                results.Count(result => result.Outcome == VerificationCommitOutcome.Applied),
                "并发下只能有一个写入者");
            TestHarness.Equal(
                results.Length - 1,
                results.Count(result => result.Outcome == VerificationCommitOutcome.Duplicate),
                "其余并发提交必须幂等");
            TestHarness.Equal(1, ledger.History.Count, "不得产生重复历史");
        });

        harness.Run("生命周期：历史记录可追溯", () =>
        {
            var ledger = new VerifiedLifecycleLedger(() => Now);
            ledger.Commit(ledger.Begin(), Evidence("si:v1:file:A", 101, "digest-1"));
            ledger.AdvanceGeneration("save_identity_changed");
            ledger.Commit(ledger.Begin(), Evidence("si:v1:file:A", 101, "digest-2"));

            TestHarness.Equal(3, ledger.History.Count, "应为 Verified + Invalidated + 新 Verified");
            TestHarness.Equal("digest-1", ledger.History[0].EvidenceDigest, "旧证据必须保留");
            TestHarness.Equal(VerificationState.Invalidated, ledger.History[1].State, "失效记录必须保留");
            TestHarness.Equal("digest-2", ledger.History[2].EvidenceDigest, "新证据必须记录");
            TestHarness.Equal(
                ledger.History.Select(row => row.Sequence).Distinct().Count(),
                ledger.History.Count,
                "序号必须唯一且只追加");
        });
    }

    private static VerificationEvidence Evidence(string fingerprint, uint uid, string digest) => new(
        SaveIdentityFingerprint: fingerprint,
        SaveSessionKey: "123:start:26620374",
        GameBuild: "26620374",
        LayoutVersion: "FM27_1",
        PersonUid: uid,
        DisplayName: "Test Player",
        DateOfBirth: new DateOnly(2000, 1, 1),
        AttributeRecordIdentity: "record-digest",
        ValidatorVersion: "v3.2.9.2",
        EvidenceDigest: digest);
}
