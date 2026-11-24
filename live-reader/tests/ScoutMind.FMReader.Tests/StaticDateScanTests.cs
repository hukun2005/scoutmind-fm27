using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>静态根扫描：模块边界、跳数与越界行为。</summary>
public static class StaticDateScanTests
{
    private const int RegionSize = 0x1000;

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("静态根扫描：模块内指针一跳命中日期字段", () =>
        {
            var memory = new FakeMemory();
            const ulong moduleBase = 0x1000_0000;
            const ulong heapObject = 0x3000_0000;
            memory.Write(moduleBase, new byte[RegionSize]);
            memory.Write(heapObject, new byte[RegionSize]);
            memory.WritePointer(moduleBase + 0x120, heapObject);
            memory.WriteUInt32(heapObject + 0x1E4, DateDiscovery.Encode(new DateOnly(2026, 10, 26)));

            var result = StaticDateScan.Scan(
                memory,
                new[] { new MemoryRegion(moduleBase, RegionSize) },
                new DateOnly(2026, 10, 26),
                maxDepth: 1);

            TestHarness.Equal(1, result.Roots.Count, "应命中一条静态根");
            TestHarness.Equal(0x120UL, result.Roots[0].Rva, "RVA 应精确");
            TestHarness.Equal(heapObject, result.Roots[0].Target, "目标对象应精确");
            TestHarness.Equal(0x1E4, result.Roots[0].DateOffset, "日期字段偏移应精确");
            TestHarness.Equal(1, result.Roots[0].Hop, "应标记为一跳");
        });

        harness.Run("静态根扫描：模块内指针指向模块自身时不算堆引用", () =>
        {
            var memory = new FakeMemory();
            const ulong moduleBase = 0x1000_0000;
            memory.Write(moduleBase, new byte[RegionSize]);
            memory.WritePointer(moduleBase + 0x40, moduleBase + 0x800);
            memory.WriteUInt32(moduleBase + 0x800, DateDiscovery.Encode(new DateOnly(2026, 10, 26)));

            var result = StaticDateScan.Scan(
                memory,
                new[] { new MemoryRegion(moduleBase, RegionSize) },
                new DateOnly(2026, 10, 26));

            TestHarness.Equal(0, result.Roots.Count, "模块内自引用不应被当成日期对象");
        });

        harness.Run("静态根扫描：没有模块区域时安全失败", () =>
        {
            var result = StaticDateScan.Scan(
                new FakeMemory(),
                Array.Empty<MemoryRegion>(),
                new DateOnly(2026, 10, 26));

            TestHarness.Equal(0, result.Roots.Count, "没有模块就没有候选");
            TestHarness.True(result.Truncated, "没有模块应标记为无法完成");
        });

        harness.Run("静态根扫描：两跳路径可命中", () =>
        {
            var memory = new FakeMemory();
            const ulong moduleBase = 0x1000_0000;
            const ulong container = 0x3000_0000;
            const ulong leaf = 0x3100_0000;
            memory.Write(moduleBase, new byte[RegionSize]);
            memory.Write(container, new byte[RegionSize]);
            memory.Write(leaf, new byte[RegionSize]);
            memory.WritePointer(moduleBase + 0x80, container);
            memory.WritePointer(container + 0x10, leaf);
            memory.WriteUInt32(leaf + 0x40, DateDiscovery.Encode(new DateOnly(2026, 10, 26)));

            var result = StaticDateScan.Scan(
                memory,
                new[] { new MemoryRegion(moduleBase, RegionSize) },
                new DateOnly(2026, 10, 26),
                maxDepth: 2);

            var twoHop = result.Roots.FirstOrDefault(item => item.Hop == 2);
            TestHarness.True(twoHop is not null, "应存在两跳候选");
            TestHarness.Equal(0x40, twoHop!.DateOffset, "两跳日期偏移应精确");
        });

        harness.Run("静态根扫描：期望日期不同则没有候选", () =>
        {
            var memory = new FakeMemory();
            const ulong moduleBase = 0x1000_0000;
            const ulong heapObject = 0x3000_0000;
            memory.Write(moduleBase, new byte[RegionSize]);
            memory.Write(heapObject, new byte[RegionSize]);
            memory.WritePointer(moduleBase + 0x20, heapObject);
            memory.WriteUInt32(heapObject + 0x10, DateDiscovery.Encode(new DateOnly(2026, 10, 26)));

            var result = StaticDateScan.Scan(
                memory,
                new[] { new MemoryRegion(moduleBase, RegionSize) },
                new DateOnly(2026, 11, 15));

            TestHarness.Equal(0, result.Roots.Count, "日期不匹配时不能有候选");
        });
    }
}
