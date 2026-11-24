using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>候选追踪与可信度状态机：会话验证、跨进程重启、歧义、回退与不匹配。</summary>
public static class DateCandidateTrackerTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("日期追踪：无界面证据时只能到 heuristic", () =>
        {
            var result = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                null,
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            TestHarness.Equal("heuristic", result.Status, "无界面证据不能升级");
            TestHarness.Equal(DateConfidenceLevel.Heuristic, result.Confidence, "可信度只能是 heuristic");
            TestHarness.Equal("2026-11-06", result.SelectedDate, "仍给出启发式日期");
            TestHarness.True(
                result.Candidates.Count == 1 && result.Candidates[0].Kind == DateCandidateKind.UnknownDate,
                "启发式候选必须标记 UNKNOWN_DATE");
        });

        harness.Run("日期追踪：界面日期一致时升级 session_verified", () =>
        {
            var result = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            TestHarness.Equal("session_verified", result.Status, "本会话验证应成功");
            TestHarness.Equal(DateConfidenceLevel.SessionVerified, result.Confidence, "可信度应为 session_verified");
            TestHarness.Equal("2026-11-06", result.State.LastConfirmedDate, "应记录确认日期");
            TestHarness.True(
                result.Candidates[0].Kind == DateCandidateKind.CurrentWorldDate,
                "验证通过的候选应标记 CURRENT_WORLD_DATE");
        });

        harness.Run("日期追踪：界面日期不一致时不写入确认日期", () =>
        {
            var result = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 12, 25),
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            TestHarness.Equal("verification_mismatch", result.Status, "不一致应明确报告");
            TestHarness.True(result.SelectedDate is null, "不一致时不能选中其它日期");
            TestHarness.True(result.State.LastConfirmedDate is null, "不能把未验证日期写为确认日期");
        });

        harness.Run("日期追踪：日期倒退时拒绝升级", () =>
        {
            var verified = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            var rollback = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 10, 1),
                Collection(new DateOnly(2026, 10, 1)),
                verified.State,
                DateCandidateDiagnosticsTests.Now.AddMinutes(5));

            TestHarness.Equal("date_rollback", rollback.Status, "日期倒退必须显式失败");
            TestHarness.Equal(
                DateConfidenceLevel.VerificationPending,
                rollback.Confidence,
                "倒退后可信度必须降级");
            TestHarness.Equal("2026-11-06", rollback.State.LastConfirmedDate, "不能覆盖已确认日期");
        });

        harness.Run("日期追踪：同签名跨三次独立进程会话后 restart_verified", () =>
        {
            var state = DateVerificationState.Empty;
            DateTrackingResult result = null!;
            for (var index = 0; index < DateCandidateTracker.RequiredVerifiedSessionsForRestart; index++)
            {
                result = DateCandidateTracker.Observe(
                    DateCandidateDiagnosticsTests.Session($"s{index}"),
                    null,
                    new DateOnly(2026, 11, 6),
                    Collection(new DateOnly(2026, 11, 6)),
                    state,
                    DateCandidateDiagnosticsTests.Now.AddMinutes(index * 10));
                state = result.State;
            }

            TestHarness.Equal("restart_verified", result.Status, "三次独立会话验证后才能跨重启");
            TestHarness.Equal(DateConfidenceLevel.RestartVerified, result.Confidence, "可信度应为 restart_verified");
            TestHarness.Equal(
                DateCandidateTracker.RequiredVerifiedSessionsForRestart,
                result.State.Candidates[0].VerifiedSessionKeys.Count,
                "三个独立进程会话都应留下验证证据");
        });

        harness.Run("日期追踪：绝对地址变化但结构指纹相同仍能重新关联", () =>
        {
            var first = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            var second = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s2"),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6), address: 0x3000_5A00, fingerprint: "fp-1"),
                first.State,
                DateCandidateDiagnosticsTests.Now.AddMinutes(10));

            TestHarness.Equal("session_verified", second.Status, "同一逻辑身份的第二次会话验证应成功");
            TestHarness.Equal(2, second.Candidates[0].ReadCount / 3, "读取次数应跨会话累计");
            TestHarness.True(
                second.State.Candidates[0].LastAddress == "0x30005A00",
                "新会话的绝对地址应被记录");
        });

        harness.Run("日期追踪：构建号变化清空旧验证证据", () =>
        {
            var verified = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6)),
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            var newBuild = DateCandidateTracker.Observe(
                new ProcessSessionIdentity("s2", 100, "2026-11-24T03:10:00.0000000Z", "99999999", "27.2.0", 0x1000_0000),
                null,
                new DateOnly(2026, 11, 6),
                Collection(new DateOnly(2026, 11, 6)),
                verified.State,
                DateCandidateDiagnosticsTests.Now.AddMinutes(10));

            TestHarness.Equal("session_verified", newBuild.Status, "新构建仍需重新验证");
            TestHarness.True(
                newBuild.State.Candidates[0].VerifiedSessionKeys.Count == 1,
                "旧构建的验证会话不能计入新构建");
        });
    }

    internal static WorldDateCandidateCollection Collection(
        DateOnly date,
        string fingerprint = "fp-1",
        ulong address = 0x3000_1000,
        DateCandidateKind kind = DateCandidateKind.UnknownDate,
        int consistentReads = 3)
    {
        var observation = new DateCandidateObservation(
            Address: address,
            BaseAddress: address - 0x44,
            RegionStart: 0x3000_0000,
            Module: "heap",
            RawValue: DateDiscovery.Encode(date),
            RawReference: DateDiscovery.Encode(date.AddDays(90)),
            Signature: WorldDateCandidateCollector.Signature,
            Source: "test",
            StructureFingerprint: fingerprint,
            LogicalSignature: $"heap:{fingerprint}",
            RelativeAddress: 0x44,
            RelatedObject: null,
            StructureEvidence: "test",
            KindHint: kind,
            ConsecutiveConsistentReads: consistentReads,
            RawBytes: "0x00000000 0x00000000 0xFFFFFFFF");

        return new WorldDateCandidateCollection(
            new[] { observation },
            TotalMatches: 1,
            BytesScanned: 4,
            Truncated: false,
            Evidences: Array.Empty<string>());
    }
}
