using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>模块静态引用链：发现、解析、同构去重与跨重启身份稳定性。</summary>
public static class ReferenceChainTests
{
    private const ulong ModuleBase = 0x1000_0000;
    private const ulong HeapBase = 0x3000_0000;

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("引用链：模块静态槽位一跳解析到日期字段", () =>
        {
            var memory = BuildMemory();
            var dateAddress = HeapBase + 0x100;
            WriteRecord(memory, dateAddress);
            memory.WritePointer(ModuleBase + 0x200, ObjectBase(dateAddress));

            var discovery = Discover(memory, dateAddress, maxDepth: 1);

            TestHarness.Equal(1, discovery.Candidates.Count, "应发现一条引用链");
            var chain = discovery.Candidates[0].Chain;
            TestHarness.Equal(0x200UL, chain.Rva, "静态槽位 RVA 应精确");
            TestHarness.Equal(0, chain.PointerOffsets.Count, "一跳链不应有中间指针");
            TestHarness.Equal(WorldDateLocator.DateFieldOffset, chain.DateOffset, "日期偏移应为 +0x44");

            var resolution = ReferenceChainResolver.Resolve(memory, Modules(), chain);
            TestHarness.True(resolution.Resolved, "链应能重新解析");
            TestHarness.Equal(dateAddress, resolution.DateAddress, "应解析回同一日期字段");
            TestHarness.Equal("2026-11-06", resolution.Date, "日期应解码正确");
        });

        harness.Run("引用链：两跳（模块→对象→对象）解析到日期字段", () =>
        {
            var memory = BuildMemory();
            var secondHeap = 0x3200_0000UL;
            var firstHopHeap = 0x3100_0000UL;
            memory.RegionList.Add(new MemoryRegion(firstHopHeap, 0x2000));
            memory.Write(firstHopHeap, new byte[0x2000]);
            memory.RegionList.Add(new MemoryRegion(secondHeap, 0x2000));
            memory.Write(secondHeap, new byte[0x2000]);

            var firstHop = firstHopHeap + 0x100;
            var dateAddress = secondHeap + 0x144;
            WriteRecord(memory, dateAddress);
            memory.WritePointer(firstHop + 0x10, ObjectBase(dateAddress));
            memory.WritePointer(ModuleBase + 0x300, firstHop);

            var discovery = Discover(memory, dateAddress, maxDepth: 2);

            TestHarness.True(
                discovery.Candidates.Any(item => item.Chain.Level == 2),
                "应发现两跳引用链");
            var chain = discovery.Candidates.First(item => item.Chain.Level == 2).Chain;
            TestHarness.Equal(0x300UL, chain.Rva, "静态槽位 RVA 应精确");
            TestHarness.Equal(0x10, chain.PointerOffsets[0], "第二跳指针偏移应为 +0x10");
            TestHarness.Equal(WorldDateLocator.DateFieldOffset, chain.DateOffset, "日期偏移应为 +0x44");
        });

        harness.Run("引用链：槽位越界/为空或哨兵不成立时不解析", () =>
        {
            var memory = BuildMemory();
            var outside = ReferenceChainResolver.Resolve(
                memory,
                Modules(),
                new ReferenceChain("gp", 0x2000, Array.Empty<int>(), 0x44));
            TestHarness.True(!outside.Resolved, "越界槽位不能被当作引用链");
            TestHarness.Equal("slot_out_of_module", outside.Status, "应报告槽位越界");

            var empty = ReferenceChainResolver.Resolve(
                memory,
                Modules(),
                new ReferenceChain("gp", 0x800, Array.Empty<int>(), 0x44));
            TestHarness.True(!empty.Resolved, "空槽位不能被当作引用链");
            TestHarness.Equal("invalid_pointer", empty.Status, "应报告指针非法");

            memory.WritePointer(ModuleBase + 0x200, HeapBase + 0x200);
            var mismatch = ReferenceChainResolver.Resolve(
                memory,
                Modules(),
                new ReferenceChain("gp", 0x200, Array.Empty<int>(), 0x44));
            TestHarness.True(!mismatch.Resolved, "哨兵不成立时不能解析成功");
            TestHarness.Equal("structure_mismatch", mismatch.Status, "应报告结构不匹配");
        });

        harness.Run("引用链：同构重复记录中只有引用链那一条被保留并 session_verified", () =>
        {
            var memory = BuildMemory();
            var first = HeapBase + 0x100;
            var second = HeapBase + 0x300;
            WriteRecord(memory, first);
            WriteRecord(memory, second);
            memory.WritePointer(ModuleBase + 0x200, ObjectBase(first));

            var collection = WorldDateCandidateCollector.Collect(
                memory,
                maxBytes: 1 << 20,
                moduleRegions: Modules());
            TestHarness.Equal(2, collection.Observations.Count, "两条同构记录都应被采集");
            TestHarness.Equal(
                1,
                collection.Observations.Count(item => item.ReferenceChain is not null),
                "只有被静态指针引用的记录应有引用链：" + string.Join(
                    " | ",
                    collection.Observations.Select(item =>
                        $"0x{item.Address:X}={item.ReferenceChain?.Signature ?? "none"}")));

            var tracked = DateCandidateTracker.Observe(
                DateCandidateDiagnosticsTests.Session("s1"),
                null,
                new DateOnly(2026, 11, 6),
                collection,
                DateVerificationState.Empty,
                DateCandidateDiagnosticsTests.Now);

            TestHarness.Equal("session_verified", tracked.Status, "引用链应消除同构歧义");
            TestHarness.Equal(1, tracked.Candidates.Count, "只保留引用链指向的候选");
            TestHarness.Equal(1, tracked.RejectedCandidates.Count, "另一条同构记录必须写明排除原因");
            TestHarness.True(
                tracked.Candidates[0].IdentitySignature.StartsWith("chain:", StringComparison.Ordinal),
                "候选身份应使用引用链签名");
        });

        harness.Run("引用链：跨进程重启按同一 RVA/偏移链重新验证到 restart_verified", () =>
        {
            var state = DateVerificationState.Empty;
            DateTrackingResult result = null!;
            for (var index = 0; index < DateCandidateTracker.RequiredVerifiedSessionsForRestart; index++)
            {
                var memory = BuildMemory(HeapBase + (ulong)(index * 0x10_0000));
                WriteRecord(memory, memory.RegionList[1].Start + 0x100);
                memory.WritePointer(ModuleBase + 0x200, ObjectBase(memory.RegionList[1].Start + 0x100));
                var collection = WorldDateCandidateCollector.Collect(
                    memory,
                    maxBytes: 1 << 20,
                    moduleRegions: Modules());

                result = DateCandidateTracker.Observe(
                    DateCandidateDiagnosticsTests.Session($"s{index}"),
                    null,
                    new DateOnly(2026, 11, 6),
                    collection,
                    state,
                    DateCandidateDiagnosticsTests.Now.AddMinutes(index * 10));
                state = result.State;
            }

            TestHarness.Equal("restart_verified", result.Status, "同一引用链在三次独立会话后应跨重启验证");
            TestHarness.Equal(
                DateCandidateTracker.RequiredVerifiedSessionsForRestart,
                result.State.Candidates[0].VerifiedSessionKeys.Count,
                "每个进程会话都应留下验证证据");
            TestHarness.True(
                result.State.Candidates[0].ChainLevel == 1,
                "持久化状态应保留引用链跳数");
        });
    }

    private static FakeMemory BuildMemory(ulong heapBase = HeapBase)
    {
        var memory = new FakeMemory();
        memory.RegionList.Add(new MemoryRegion(ModuleBase, 0x1000));
        memory.Write(ModuleBase, new byte[0x1000]);
        memory.RegionList.Add(new MemoryRegion(heapBase, 0x4000));
        memory.Write(heapBase, new byte[0x4000]);
        return memory;
    }

    private static IReadOnlyList<ModuleRegion> Modules() =>
        new[] { new ModuleRegion("gp", ModuleBase, ModuleBase, 0x1000) };

    private static ulong ObjectBase(ulong dateAddress) => dateAddress - WorldDateLocator.DateFieldOffset;

    private static void WriteRecord(FakeMemory memory, ulong dateAddress) =>
        DateCandidateDiagnosticsTests.WriteRecord(
            memory,
            dateAddress,
            new DateOnly(2026, 11, 6),
            new DateOnly(2027, 2, 25),
            0x33);

    private static ReferenceChainDiscovery Discover(FakeMemory memory, ulong dateAddress, int maxDepth) =>
        ReferenceChainFinder.Discover(
            memory,
            new[] { new ReferenceChainTarget(dateAddress, DateDiscovery.Encode(new DateOnly(2026, 11, 6))) },
            Modules(),
            maxDepth,
            maxBytes: 1 << 20,
            budget: TimeSpan.FromSeconds(5));
}
