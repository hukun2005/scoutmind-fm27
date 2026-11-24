using System.Text;

namespace ScoutMind.FMReader.Tests;

/// <summary>ScoutMind.FMReader 自测入口（无 xunit，离线可跑）。</summary>
internal static class Program
{
    private static async Task<int> Main()
    {
        try
        {
            Console.OutputEncoding = Encoding.UTF8;
        }
        catch (IOException)
        {
            // 重定向输出时没有控制台句柄，保持默认编码。
        }

        Console.WriteLine("ScoutMind.FMReader 自测（原生只读读取引擎）");
        Console.WriteLine($"测试进程：{Environment.ProcessPath}");
        Console.WriteLine();

        var testRoot = Path.Combine(AppContext.BaseDirectory, "test-tmp");
        Directory.CreateDirectory(testRoot);
        Environment.SetEnvironmentVariable("TMP", testRoot);
        Environment.SetEnvironmentVariable("TEMP", testRoot);

        var harness = new TestHarness();
        LocatorTests.Run(harness);
        VersionGateTests.Run(harness);
        LayoutAndProbeTests.Run(harness);
        RoundTwoTests.Run(harness);
        ExecutionLayoutTests.Run(harness);
        CompatibilityConfigTests.Run(harness);
        EngineResourceTests.Run(harness);
        StabilityTests.Run(harness);
        MapperTests.Run(harness);
        MapperSentinelUidTests.Run(harness);
UnresolvedObjectCollectorTests.Run(harness);
DateDiscoveryTests.Run(harness);
PointerAndLocatorTests.Run(harness);
StaticDateScanTests.Run(harness);
WorldDateResolverTests.Run(harness);
        await EngineTests.RunAsync(harness).ConfigureAwait(false);

        return harness.Summary();
    }
}
