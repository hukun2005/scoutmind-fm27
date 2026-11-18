using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Reader.Tests;

/// <summary>
/// 扫描器适配器用例：状态拒绝、真实进程启动、超时终止、非零退出、非法输出与成功落盘。
/// </summary>
public static class ScannerAdapterTests
{
    private static readonly GameInfo TestGame = new("4530370", "26620374", null, null, "27.1.0");

    /// <summary>注册并执行适配器用例。</summary>
    /// <param name="harness">测试框架。</param>
    /// <returns>表示执行完成的任务。</returns>
    public static async Task RunAsync(TestHarness harness)
    {
        var testExecutable = Path.Combine(AppContext.BaseDirectory, "ScoutMind.Reader.Tests.exe");
        Assert.FileExists(testExecutable, "测试程序自身的 apphost 必须存在，供假扫描器复用");

        await harness.CaseAsync("状态不满足时拒绝 probe 且不启动进程", async () =>
        {
            using var workspace = new TempWorkspace();
            var marker = workspace.Combine("probe.marker");
            Environment.SetEnvironmentVariable(FakeScanner.MarkerEnvironmentVariable, marker);
            try
            {
                var adapter = new ScannerAdapter(ProbeConfig(testExecutable, "mark"));
                await Assert.ThrowsAsync<ScanRefusedException>(
                    () => adapter.ProbeAsync(ReaderState.NotFound, CancellationToken.None),
                    "NotFound 状态必须拒绝 probe").ConfigureAwait(false);
                await Assert.ThrowsAsync<ScanRefusedException>(
                    () => adapter.ProbeAsync(ReaderState.VersionIdentified, CancellationToken.None),
                    "VersionIdentified 状态必须拒绝 probe").ConfigureAwait(false);

                await Task.Delay(300).ConfigureAwait(false);
                Assert.False(File.Exists(marker), "被拒绝时不得启动外部进程");
            }
            finally
            {
                Environment.SetEnvironmentVariable(FakeScanner.MarkerEnvironmentVariable, null);
            }
        }).ConfigureAwait(false);

        await harness.CaseAsync("状态不满足时拒绝扫描且不启动进程", async () =>
        {
            using var workspace = new TempWorkspace();
            var marker = workspace.Combine("scan.marker");
            Environment.SetEnvironmentVariable(FakeScanner.MarkerEnvironmentVariable, marker);
            try
            {
                var adapter = new ScannerAdapter(ScanConfig(testExecutable, "mark"));
                await Assert.ThrowsAsync<ScanRefusedException>(
                    () => adapter.ScanAsync(
                        new ScanRequest(workspace.Combine("out"), 30, null),
                        ReaderState.Compatible,
                        TestGame,
                        CancellationToken.None),
                    "未通过 probe 时扫描必须被拒绝").ConfigureAwait(false);

                await Task.Delay(300).ConfigureAwait(false);
                Assert.False(File.Exists(marker), "被拒绝时不得启动外部进程");
                Assert.False(Directory.Exists(workspace.Combine("out")), "被拒绝时不得创建输出目录");
            }
            finally
            {
                Environment.SetEnvironmentVariable(FakeScanner.MarkerEnvironmentVariable, null);
            }
        }).ConfigureAwait(false);

        await harness.CaseAsync("probe 成功时返回通过", async () =>
        {
            var adapter = new ScannerAdapter(ProbeConfig(testExecutable, "probe-ok"));
            var probe = await adapter.ProbeAsync(ReaderState.Compatible, CancellationToken.None).ConfigureAwait(false);

            Assert.True(probe.Passed, "退出码为 0 的 probe 应通过");
            Assert.Equal<int?>(0, probe.ExitCode, "退出码应为 0");
            Assert.Contains(probe.Output, "probe", "应捕获 stdout 内容");
            Assert.True(probe.FailureReason is null, "通过时不应有失败原因");
        }).ConfigureAwait(false);

        await harness.CaseAsync("probe 非零退出码 → 失败", async () =>
        {
            var adapter = new ScannerAdapter(ProbeConfig(testExecutable, "probe-fail"));
            var probe = await adapter.ProbeAsync(ReaderState.Compatible, CancellationToken.None).ConfigureAwait(false);

            Assert.False(probe.Passed, "非零退出码必须失败");
            Assert.Equal<int?>(3, probe.ExitCode, "退出码应被记录");
            Assert.Contains(probe.FailureReason, "退出码", "失败原因应说明退出码");
        }).ConfigureAwait(false);

        await harness.CaseAsync("扫描成功时落盘信封与边车", async () =>
        {
            using var workspace = new TempWorkspace();
            var outputDirectory = workspace.Combine("out");
            var adapter = new ScannerAdapter(ScanConfig(testExecutable, "scan-ok"));

            var result = await adapter.ScanAsync(
                new ScanRequest(outputDirectory, 30, null),
                ReaderState.ProbePassed,
                TestGame,
                CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ReaderState.ScanCompleted, result.State, $"扫描应成功，失败原因：{result.FailureReason}");
            Assert.Equal(1, result.PlayersCount, "球员数量应为 1");
            Assert.Equal(0, result.TransfersCount, "转会数量应为 0");
            Assert.Equal("test-scan-0001", result.ScanId, "应采用扫描器提供的 scan_id");
            Assert.True(result.FailureReason is null, "成功时不应有失败原因");
            Assert.True(result.OutputFile is not null, "应写出信封文件");

            var envelopePath = result.OutputFile;
            if (envelopePath is null)
            {
                throw new AssertionException("信封路径不应为空");
            }

            Assert.FileExists(envelopePath, "信封文件必须存在");
            var envelopeJson = await File.ReadAllTextAsync(envelopePath).ConfigureAwait(false);
            using var document = JsonDocument.Parse(envelopeJson);
            var root = document.RootElement;
            Assert.True(root.TryGetProperty("schemaVersion", out _), "信封应使用 camelCase");
            Assert.Equal(1, root.GetProperty("players").GetArrayLength(), "球员数组应保留原始记录");
            Assert.Equal("test-scan-0001", root.GetProperty("scan").GetProperty("scanId").GetString(), "scanId 应写入信封");
            Assert.Equal("26620374", root.GetProperty("game").GetProperty("build").GetString(), "构建号应来自扫描器输出");
            Assert.True(result.Warnings.Count >= 2, "告警应包含扫描器告警与读取器补充说明");

            var metaPath = Path.Combine(outputDirectory, "scan-test-scan-0001.meta.json");
            Assert.FileExists(metaPath, "应写出边车文件");
            var metaJson = await File.ReadAllTextAsync(metaPath).ConfigureAwait(false);
            Assert.Contains(metaJson, "\"exitCode\": 0", "边车应记录退出码");
            Assert.Contains(metaJson, "\"scanId\": \"test-scan-0001\"", "边车应记录扫描 ID");
        }).ConfigureAwait(false);

        await harness.CaseAsync("扫描输出不是 JSON → 失败", async () =>
        {
            using var workspace = new TempWorkspace();
            var adapter = new ScannerAdapter(ScanConfig(testExecutable, "scan-invalid-json"));

            var result = await adapter.ScanAsync(
                new ScanRequest(workspace.Combine("out"), 30, null),
                ReaderState.ProbePassed,
                TestGame,
                CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ReaderState.ProbeFailed, result.State, "非法 JSON 必须判为 ProbeFailed");
            Assert.Contains(result.FailureReason, "协议校验", "失败原因应说明协议校验");
            Assert.True(result.OutputFile is null, "失败时不得写出信封");
        }).ConfigureAwait(false);

        await harness.CaseAsync("扫描输出缺少 schema_version → 失败", async () =>
        {
            using var workspace = new TempWorkspace();
            var adapter = new ScannerAdapter(ScanConfig(testExecutable, "scan-missing-schema"));

            var result = await adapter.ScanAsync(
                new ScanRequest(workspace.Combine("out"), 30, null),
                ReaderState.ProbePassed,
                TestGame,
                CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ReaderState.ProbeFailed, result.State, "缺少 schema_version 必须失败");
            Assert.Contains(result.FailureReason, "schema_version", "失败原因应指出缺少 schema_version");
        }).ConfigureAwait(false);

        await harness.CaseAsync("扫描器非零退出码 → 失败", async () =>
        {
            using var workspace = new TempWorkspace();
            var adapter = new ScannerAdapter(ScanConfig(testExecutable, "scan-fail"));

            var result = await adapter.ScanAsync(
                new ScanRequest(workspace.Combine("out"), 30, null),
                ReaderState.ProbePassed,
                TestGame,
                CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ReaderState.ProbeFailed, result.State, "非零退出码必须失败");
            Assert.Equal<int?>(2, result.ExitCode, "退出码应被记录");
            Assert.Contains(result.FailureReason, "退出码", "失败原因应说明退出码");
            Assert.Contains(result.FailureReason, "模拟失败", "失败原因应包含 stderr 摘要");
        }).ConfigureAwait(false);

        await harness.CaseAsync("扫描超时 → ProbeFailed 且终止子进程", async () =>
        {
            using var workspace = new TempWorkspace();
            var pidFile = workspace.Combine("scanner.pid");
            Environment.SetEnvironmentVariable(FakeScanner.PidFileEnvironmentVariable, pidFile);
            try
            {
                var adapter = new ScannerAdapter(ScanConfig(testExecutable, "sleep"));
                var scanTask = adapter.ScanAsync(
                    new ScanRequest(workspace.Combine("out"), 1, null),
                    ReaderState.ProbePassed,
                    TestGame,
                    CancellationToken.None);

                var pid = await ReadPidFileAsync(pidFile, TimeSpan.FromSeconds(20)).ConfigureAwait(false);
                if (pid is not int childPid)
                {
                    throw new AssertionException("假扫描器应写出 PID 文件（超时用例无法验证进程被终止）");
                }

                var result = await scanTask.ConfigureAwait(false);

                Assert.Equal(ReaderState.ProbeFailed, result.State, "超时必须判为 ProbeFailed");
                Assert.Contains(result.FailureReason, "未完成", "失败原因应说明超时");
                Assert.True(
                    await WaitForProcessGoneAsync(childPid, TimeSpan.FromSeconds(10)).ConfigureAwait(false),
                    $"超时后子进程 {childPid} 必须被终止");
            }
            finally
            {
                Environment.SetEnvironmentVariable(FakeScanner.PidFileEnvironmentVariable, null);
            }
        }).ConfigureAwait(false);

        await harness.CaseAsync("未配置扫描器时拒绝 probe 与 scan", async () =>
        {
            using var workspace = new TempWorkspace();
            var adapter = new ScannerAdapter(new ScannerConfig());

            Assert.Throws<ScannerConfigurationException>(
                () => { adapter.EnsureScannerConfigured(); },
                "空扫描器路径必须报配置错误");

            await Assert.ThrowsAsync<ScannerConfigurationException>(
                () => adapter.ScanAsync(
                    new ScanRequest(workspace.Combine("out"), 5, null),
                    ReaderState.ProbePassed,
                    null,
                    CancellationToken.None),
                "未配置扫描器时扫描必须被拒绝").ConfigureAwait(false);

            Assert.False(Directory.Exists(workspace.Combine("out")), "配置错误时不得创建输出目录");
        }).ConfigureAwait(false);
    }

    private static ScannerConfig ProbeConfig(string testExecutable, string mode) => new()
    {
        ScannerPath = testExecutable,
        ProbeArguments = new List<string> { FakeScanner.ModeArgument, mode },
        ScanArgumentsTemplate = $"{FakeScanner.ModeArgument} {mode}",
        TimeoutSeconds = 30,
    };

    private static ScannerConfig ScanConfig(string testExecutable, string mode) => new()
    {
        ScannerPath = testExecutable,
        ProbeArguments = new List<string> { FakeScanner.ModeArgument, "probe-ok" },
        ScanArgumentsTemplate = $"{FakeScanner.ModeArgument} {mode}",
        TimeoutSeconds = 30,
    };

    private static async Task<int?> ReadPidFileAsync(string path, TimeSpan timeout)
    {
        var deadline = DateTimeOffset.UtcNow.Add(timeout);
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (File.Exists(path))
            {
                try
                {
                    var text = await File.ReadAllTextAsync(path).ConfigureAwait(false);
                    if (int.TryParse(text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var pid))
                    {
                        return pid;
                    }
                }
                catch (IOException)
                {
                    // The child may still be flushing the file; retry until the deadline.
                }
                catch (UnauthorizedAccessException)
                {
                    // Same as above: transient sharing violation while the child writes.
                }
            }

            await Task.Delay(100).ConfigureAwait(false);
        }

        return null;
    }

    private static async Task<bool> WaitForProcessGoneAsync(int pid, TimeSpan timeout)
    {
        var deadline = DateTimeOffset.UtcNow.Add(timeout);
        while (DateTimeOffset.UtcNow < deadline)
        {
            try
            {
                using var process = Process.GetProcessById(pid);
                if (process.HasExited)
                {
                    return true;
                }
            }
            catch (ArgumentException)
            {
                return true;
            }

            await Task.Delay(100).ConfigureAwait(false);
        }

        return false;
    }
}
