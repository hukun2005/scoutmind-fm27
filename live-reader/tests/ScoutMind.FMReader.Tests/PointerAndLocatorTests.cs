using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>指针扫描与世界日期签名定位的单元测试。</summary>
public static class PointerAndLocatorTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("指针扫描：命中指向目标区间的 8 字节指针并标记模块归属", () =>
        {
            var memory = new FakeMemory();
            const ulong target = 0x2A00_0000;
            const ulong regionStart = 0x2000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, 256));
            var buffer = new byte[256];
            BitConverter.GetBytes(target + 0x40).CopyTo(buffer, 128);
            memory.Write(regionStart, buffer);

            var result = PointerScan.Scan(memory, target, target + 0x1000, maxBytes: 1 << 20);

            TestHarness.Equal(1, result.Hits.Count, "应命中一个指针");
            TestHarness.Equal(regionStart + 128, result.Hits[0].SlotAddress, "槽位地址应精确");
            TestHarness.Equal(target + 0x40, result.Hits[0].Value, "指针值应保留");
            TestHarness.True(!result.Hits[0].InModule, "堆内槽位不应标记为模块内");
        });

        harness.Run("指针扫描：预算生效并截断，越界值不算命中", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x2000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, 4096));
            var buffer = new byte[4096];
            BitConverter.GetBytes(0xDEAD_BEEFUL).CopyTo(buffer, 0);
            BitConverter.GetBytes(0x2100_0000UL).CopyTo(buffer, 2048);
            memory.Write(regionStart, buffer);

            var result = PointerScan.Scan(memory, 0x2100_0000, 0x2100_1000, maxBytes: 512);

            TestHarness.Equal(0, result.Hits.Count, "预算内不应扫描到尾部指针");
            TestHarness.True(result.Truncated, "达到预算必须标记截断");
            TestHarness.True(result.BytesScanned <= 512, "扫描量不能超过预算");
        });

        harness.Run("世界日期定位：日期+参考日期+哨兵+两个零字段才命中", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            const int dateOffset = 0x100;
            memory.RegionList.Add(new MemoryRegion(regionStart, 512));
            var buffer = new byte[512];
            BitConverter.GetBytes(DateDiscovery.Encode(new DateOnly(2026, 10, 28))).CopyTo(buffer, dateOffset);
            BitConverter.GetBytes(DateDiscovery.Encode(new DateOnly(2027, 2, 1))).CopyTo(buffer, dateOffset + 4);
            BitConverter.GetBytes(0xFFFFFFFFu).CopyTo(buffer, dateOffset + 8);
            memory.Write(regionStart, buffer);

            var result = WorldDateLocator.Scan(memory, maxBytes: 1 << 20);

            TestHarness.Equal(1, result.Matches.Count, "应命中一处世界日期");
            TestHarness.Equal("2026-10-28", result.Matches[0].Date, "当前日期应解码正确");
            TestHarness.Equal("2027-02-01", result.Matches[0].Reference, "参考日期应解码正确");
            TestHarness.Equal(regionStart + dateOffset, result.Matches[0].DateAddress, "字段地址应精确");
            TestHarness.Equal(
                regionStart + dateOffset - WorldDateLocator.DateFieldOffset,
                result.Matches[0].BaseAddress,
                "基址应按固定偏移回推");
        });

        harness.Run("世界日期定位：哨兵或零字段不成立时不命中", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x3000_0000;
            memory.RegionList.Add(new MemoryRegion(regionStart, 256));
            var buffer = new byte[256];
            BitConverter.GetBytes(DateDiscovery.Encode(new DateOnly(2026, 10, 28))).CopyTo(buffer, 0x40);
            BitConverter.GetBytes(DateDiscovery.Encode(new DateOnly(2027, 2, 1))).CopyTo(buffer, 0x44);
            BitConverter.GetBytes(0u).CopyTo(buffer, 0x48);
            memory.Write(regionStart, buffer);

            var result = WorldDateLocator.Scan(memory, maxBytes: 1 << 20);

            TestHarness.Equal(0, result.Matches.Count, "哨兵不成立时不能命中");
        });

        harness.Run("世界日期定位：没有区域时安全失败", () =>
        {
            var result = WorldDateLocator.Scan(new FakeMemory());
            TestHarness.Equal(0, result.Matches.Count, "没有区域就没有命中");
            TestHarness.True(result.Truncated, "没有区域应标记无法完成");
        });
    }
}
