using System.Text;
using ScoutMind.Reader.Tests;

// The same executable doubles as the fake external scanner spawned by the adapter tests.
if (FakeScanner.IsFakeScannerInvocation(args))
{
    return await FakeScanner.RunAsync(args);
}

try
{
    Console.OutputEncoding = Encoding.UTF8;
}
catch (IOException)
{
    // Redirected stdout without a console handle: keep the default encoding.
}

Console.WriteLine("ScoutMind 读取器自测（无 xunit）");
Console.WriteLine($"测试进程：{Environment.ProcessPath}");
Console.WriteLine();

// Keep every temp path the tests (and the code under test) create inside one writable root. Restricted
// environments can deny child-process writes under %TEMP%, which would otherwise fail filesystem-only cases.
var testRoot = Path.Combine(AppContext.BaseDirectory, "test-tmp");
Directory.CreateDirectory(testRoot);
Environment.SetEnvironmentVariable("TMP", testRoot);
Environment.SetEnvironmentVariable("TEMP", testRoot);

var harness = new TestHarness();

StateMachineTests.Run(harness);
VdfParserTests.Run(harness);
CompatibilityTests.Run(harness);
ScanEnvelopeTests.Run(harness);
await CliParserTests.RunAsync(harness);
ProbeReportTests.Run(harness);
await ScannerAdapterTests.RunAsync(harness);

return harness.Summary();
