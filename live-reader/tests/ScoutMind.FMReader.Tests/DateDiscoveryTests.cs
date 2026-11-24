using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>日期候选发现：只认与期望日期逐位相等的编码，预算与取消必须生效。</summary>
public static class DateDiscoveryTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("日期编码：编码与解码可逆，非法原始值被拒绝", () =>
        {
            var date = new DateOnly(2026, 10, 23);
            var encoded = DateDiscovery.Encode(date);
            TestHarness.Equal(2026u, encoded >> 16, "高 16 位是年份");
            TestHarness.Equal((uint)date.DayOfYear, encoded & 0x1FF, "低 9 位是年内序日");
            TestHarness.Equal(date, DateDiscovery.Decode(encoded)!.Value, "解码应还原日期");

            TestHarness.True(DateDiscovery.Decode(0x076C0002) is null, "年份 1900 不是合法当前日期");
            TestHarness.True(DateDiscovery.Decode((2026u << 16) | 400u) is null, "序日 400 必须拒绝");
            TestHarness.True(DateDiscovery.Decode(0) is null, "0 必须拒绝");
        });

        harness.Run("候选发现：命中与期望日期一致的对齐 u32", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x2000_0000;
            const int size = 256;
            memory.RegionList.Add(new MemoryRegion(regionStart, size));
            var buffer = new byte[size];
            var date = new DateOnly(2026, 10, 23);
            BitConverter.GetBytes(DateDiscovery.Encode(date)).CopyTo(buffer, 64);
            memory.Write(regionStart, buffer);

            var result = DateDiscovery.Discover(memory, date);

            TestHarness.Equal(1, result.Candidates.Count, "应命中一个候选");
            TestHarness.Equal(regionStart + 64, result.Candidates[0].Address, "候选地址应精确");
            TestHarness.Equal(1, result.RegionsExamined, "应扫描一个区域");
            TestHarness.True(!result.Truncated, "预算充足时不应截断");
        });

        harness.Run("候选发现：没有命中时明确为空，不臆造日期", () =>
        {
            var memory = new FakeMemory();
            memory.RegionList.Add(new MemoryRegion(0x2000_0000, 128));
            memory.Write(0x2000_0000, new byte[128]);

            var result = DateDiscovery.Discover(memory, new DateOnly(2026, 10, 23));

            TestHarness.Equal(0, result.Candidates.Count, "不应有候选");
            TestHarness.True(result.Diagnostics.Count > 0, "应给出诊断");
        });

        harness.Run("候选发现：没有可读区域时安全失败", () =>
        {
            var result = DateDiscovery.Discover(new FakeMemory(), new DateOnly(2026, 10, 23));
            TestHarness.Equal(0, result.Candidates.Count, "没有区域就没有候选");
            TestHarness.True(result.Truncated, "没有区域应标记为无法完成");
            TestHarness.True(
                result.Diagnostics.Any(item => item.Contains("可读区域", StringComparison.Ordinal)),
                result.Diagnostics.FirstOrDefault() ?? "应说明缺少可读区域");
        });

        harness.Run("候选发现：字节预算生效并标记截断", () =>
        {
            var memory = new FakeMemory();
            const ulong regionStart = 0x2000_0000;
            const int size = 4096;
            memory.RegionList.Add(new MemoryRegion(regionStart, size));
            var buffer = new byte[size];
            BitConverter.GetBytes(DateDiscovery.Encode(new DateOnly(2026, 10, 23))).CopyTo(buffer, size - 8);
            memory.Write(regionStart, buffer);

            var result = DateDiscovery.Discover(memory, new DateOnly(2026, 10, 23), maxBytes: 512);

            TestHarness.Equal(0, result.Candidates.Count, "候选在预算之外，不应被读到");
            TestHarness.True(result.Truncated, "达到预算必须标记截断");
            TestHarness.True(result.BytesScanned <= 512, "扫描字节数不能超过预算");
        });

        harness.Run("候选发现：取消令牌立即生效", () =>
        {
            var memory = new FakeMemory();
            memory.RegionList.Add(new MemoryRegion(0x2000_0000, 4096));
            memory.Write(0x2000_0000, new byte[4096]);
            using var source = new CancellationTokenSource();
            source.Cancel();

            var result = DateDiscovery.Discover(
                memory, new DateOnly(2026, 10, 23), cancellationToken: source.Token);

            TestHarness.Equal(0, result.Candidates.Count, "取消后不应继续产出候选");
            TestHarness.True(
                result.Diagnostics.Any(item => item.Contains("取消", StringComparison.Ordinal)),
                "应说明已取消");
        });
    }
}
