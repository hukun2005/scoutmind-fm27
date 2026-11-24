using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>启发式世界日期解析：最新日期、歧义与稳定性。</summary>
public static class WorldDateResolverTests
{
    private const int RegionSize = 0x1000;

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("世界日期解析：多条候选时取最新日期", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, RegionSize));
            memory.Write(regionStart, new byte[RegionSize]);
            WriteRecord(memory, regionStart + 0x100, new DateOnly(2026, 11, 5), new DateOnly(2027, 2, 1));
            WriteRecord(memory, regionStart + 0x200, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25));

            var result = WorldDateResolver.Resolve(memory);

            TestHarness.Equal("ok", result.Status, "应成功解析");
            TestHarness.Equal("2026-11-06", result.Date, "应取最新日期");
            TestHarness.Equal("heuristic", result.Confidence, "只能声明为启发式");
        });

        harness.Run("世界日期解析：同一天多条记录返回 ambiguous", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, RegionSize));
            memory.Write(regionStart, new byte[RegionSize]);
            WriteRecord(memory, regionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25));
            WriteRecord(memory, regionStart + 0x200, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 1));

            var result = WorldDateResolver.Resolve(memory);

            TestHarness.Equal("ambiguous", result.Status, "同一天多条应判歧义");
            TestHarness.Equal("2026-11-06", result.Date, "仍应报告冲突日期");
            TestHarness.True(result.Reason is not null, "应给出原因");
        });

        harness.Run("世界日期解析：没有候选时 not_found", () =>
        {
            var memory = new FakeMemory();
            memory.RegionList.Add(new MemoryRegion(0x3000_0000, RegionSize));
            memory.Write(0x3000_0000, new byte[RegionSize]);

            var result = WorldDateResolver.Resolve(memory);

            TestHarness.Equal("not_found", result.Status, "没有候选应返回 not_found");
            TestHarness.True(result.Date is null, "不能凭空给出日期");
        });

        harness.Run("世界日期解析：参考日期间隔不合理时被过滤", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, RegionSize));
            memory.Write(regionStart, new byte[RegionSize]);
            WriteRecord(memory, regionStart + 0x100, new DateOnly(2026, 11, 6), new DateOnly(2026, 11, 20));

            var result = WorldDateResolver.Resolve(memory);

            TestHarness.Equal("not_found", result.Status, "间隔 14 天不满足 30..400 天");
        });

        harness.Run("世界日期解析：字段复读一致才算稳定", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, RegionSize));
            memory.Write(regionStart, new byte[RegionSize]);
            WriteRecord(memory, regionStart + 0x300, new DateOnly(2026, 11, 6), new DateOnly(2027, 2, 25));

            var result = WorldDateResolver.Resolve(memory);

            TestHarness.Equal("ok", result.Status, "复读一致应成功");
            TestHarness.Equal(regionStart + 0x300, result.Candidates[0].DateAddress, "候选地址应精确");
        });
    }

    private static void WriteRecord(FakeMemory memory, ulong address, DateOnly date, DateOnly reference)
    {
        memory.WriteUInt32(address, DateDiscovery.Encode(date));
        memory.WriteUInt32(address + 4, DateDiscovery.Encode(reference));
        memory.WriteUInt32(address + 8, 0xFFFFFFFF);
        memory.WriteUInt32(address + 12, 0);
        memory.WriteUInt32(address + 16, 0);
    }
}

