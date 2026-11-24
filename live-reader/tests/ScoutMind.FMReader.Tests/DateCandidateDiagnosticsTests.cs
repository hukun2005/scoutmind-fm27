using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>候选诊断：所有命中都被保留或明确排除，且结构指纹不依赖日期值。</summary>
public static class DateCandidateDiagnosticsTests
{
    private const int RegionSize = 0x4000;
    private const ulong RegionStart = 0x3000_0000;

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("候选诊断：签名命中全部进入保留或排除列表", () =>
        {
            var memory = CreateMemory();
            WriteRecord(memory, RegionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2026, 12, 1), 0x11);
            WriteRecord(memory, RegionStart + 0x300, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x22);

            var collection = WorldDateCandidateCollector.Collect(memory, RegionSize);
            var tracked = DateCandidateTracker.Observe(Session("s1"), null, null, collection, DateVerificationState.Empty, Now);

            TestHarness.Equal(2, collection.Observations.Count, "两次签名命中都应被采集");
            TestHarness.Equal(2, tracked.Candidates.Count + tracked.RejectedCandidates.Count, "命中不能被静默丢弃");
            TestHarness.Equal("heuristic", tracked.Status, "只剩一条合理候选时应为启发式");
            TestHarness.Equal(1, tracked.RejectedCandidates.Count, "间隔只有 25 天的记录应被排除");
            TestHarness.Equal(
                DateRejectionReason.OutOfSupportedRange,
                tracked.RejectedCandidates[0].Rejection,
                "间隔不合理应标记 OUT_OF_SUPPORTED_RANGE");
        });

        harness.Run("候选诊断：同结构签名重复时判歧义且全部排除", () =>
        {
            var memory = CreateMemory();
            WriteRecord(memory, RegionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x33, writeContext: false);
            WriteRecord(memory, RegionStart + 0x300, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x33, writeContext: false);

            var collection = WorldDateCandidateCollector.Collect(memory, RegionSize);
            var tracked = DateCandidateTracker.Observe(Session("s1"), null, null, collection, DateVerificationState.Empty, Now);

            TestHarness.Equal("ambiguous", tracked.Status, "同签名多命中不能随便挑一个");
            TestHarness.True(tracked.SelectedDate is null, "歧义时不能给出日期");
            TestHarness.True(
                tracked.RejectedCandidates.All(item => item.Rejection == DateRejectionReason.DuplicateSignature),
                "重复签名必须逐条标记 DUPLICATE_SIGNATURE");
        });

        harness.Run("候选诊断：对象提示把比赛日期排除", () =>
        {
            var memory = CreateMemory();
            var address = RegionStart + 0x200;
            WriteRecord(memory, address, new DateOnly(2027, 2, 1), new DateOnly(2027, 3, 5), 0x44);
            var hints = new[]
            {
                new DateObjectHint(address - WorldDateLocator.DateFieldOffset, 0x100, DateCandidateKind.MatchDate, "match fixture"),
            };

            var collection = WorldDateCandidateCollector.Collect(memory, RegionSize, hints);
            var tracked = DateCandidateTracker.Observe(Session("s1"), null, null, collection, DateVerificationState.Empty, Now);

            TestHarness.Equal(1, tracked.RejectedCandidates.Count, "比赛对象应被排除");
            TestHarness.Equal(DateRejectionReason.MatchObject, tracked.RejectedCandidates[0].Rejection, "排除原因应为 MATCH_OBJECT");
            TestHarness.Equal(DateCandidateKind.MatchDate, tracked.RejectedCandidates[0].Kind, "类别应保留为 MATCH_DATE");
        });

        harness.Run("候选诊断：晚于界面确认日期的记录标记 FUTURE_EVENT", () =>
        {
            var memory = CreateMemory();
            WriteRecord(memory, RegionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x55);
            WriteRecord(memory, RegionStart + 0x300, new DateOnly(2027, 2, 1), new DateOnly(2027, 3, 5), 0x66);

            var collection = WorldDateCandidateCollector.Collect(memory, RegionSize);
            var tracked = DateCandidateTracker.Observe(
                Session("s1"), null, new DateOnly(2026, 11, 6), collection, DateVerificationState.Empty, Now);

            TestHarness.Equal("session_verified", tracked.Status, "界面日期应匹配唯一候选");
            TestHarness.Equal("2026-11-06", tracked.SelectedDate, "应选中界面确认日期");
            TestHarness.True(
                tracked.RejectedCandidates.Any(item => item.Rejection == DateRejectionReason.FutureEvent),
                "未来日期必须标记 FUTURE_EVENT");
        });

        harness.Run("候选诊断：稳定性复读记录一致次数", () =>
        {
            var memory = CreateMemory();
            WriteRecord(memory, RegionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x77);

            var collection = WorldDateCandidateCollector.Collect(memory, RegionSize);

            TestHarness.Equal(3, collection.Observations[0].ConsecutiveConsistentReads, "稳定内存应连续三次一致");
        });

        harness.Run("候选身份：结构指纹不包含日期值", () =>
        {
            var first = CreateMemory();
            var a = RegionStart + 0x100;
            WriteRecord(first, a, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25), 0x88, writeContext: false);
            var second = CreateMemory();
            WriteRecord(second, a, new DateOnly(2026, 11, 20), new DateOnly(2027, 3, 30), 0x88, writeContext: false);

            var left = CandidateIdentity.ComputeFingerprint(first, a, "heap");
            var right = CandidateIdentity.ComputeFingerprint(second, a, "heap");

            TestHarness.Equal(left, right, "日期推进不能改变结构指纹");
        });
    }

    internal static readonly DateTimeOffset Now = new(2026, 11, 24, 4, 0, 0, TimeSpan.Zero);

    internal static ProcessSessionIdentity Session(string key) =>
        new(key, 100, "2026-11-24T03:00:00.0000000Z", "26620374", "27.1.0", 0x1000_0000);

    internal static FakeMemory CreateMemory()
    {
        var memory = new FakeMemory();
        memory.RegionList.Add(new MemoryRegion(RegionStart, RegionSize));
        memory.Write(RegionStart, new byte[RegionSize]);
        return memory;
    }

    internal static void WriteRecord(
        FakeMemory memory,
        ulong address,
        DateOnly date,
        DateOnly reference,
        byte marker,
        bool writeContext = true)
    {
        if (writeContext)
        {
            memory.Write(address - WorldDateLocator.DateFieldOffset, Enumerable.Repeat(marker, WorldDateLocator.DateFieldOffset).ToArray());
            memory.Write(address + 0x18, Enumerable.Repeat(marker, 0x80).ToArray());
        }

        memory.WriteUInt32(address, DateDiscovery.Encode(date));
        memory.WriteUInt32(address + 4, DateDiscovery.Encode(reference));
        memory.WriteUInt32(address + 8, WorldDateLocator.GuardValue);
        memory.WriteUInt32(address + 12, 0);
        memory.WriteUInt32(address + 16, 0);
    }
}
