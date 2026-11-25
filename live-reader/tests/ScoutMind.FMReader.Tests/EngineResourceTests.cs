using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>SM-006：扫描超时、并发闸门与临时目录清理。</summary>
internal static class EngineResourceTests
{
    private sealed class FixedLocator : IFmProcessLocator
    {
        private readonly FmProcessLocation _location;

        public FixedLocator(int pid, string installDirectory)
        {
            _location = new FmProcessLocation(pid, Path.Combine(installDirectory, "fm.exe"), installDirectory,
                new[] { "test locator" });
        }

        public FmProcessLocation Locate() => _location;
    }

    /// <summary>可控的 dump provider：记录超时、可延迟、可取消、可失败。</summary>
    private sealed class ControlledProvider : IUpstreamDumpProvider
    {
        private readonly string? _json;
        private readonly TimeSpan _delay;
        private readonly TaskCompletionSource _entered = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public ControlledProvider(string? json = "{}", TimeSpan delay = default)
        {
            _json = json;
            _delay = delay;
        }

        public TimeSpan? ObservedTimeout { get; private set; }

        public bool Block { get; init; }

        public string? WorkingDirectory { get; private set; }

        public Task Entered => _entered.Task;

        public void Release() => _release.TrySetResult();

        public async Task<UpstreamDump> ReadAsync(string workingDirectory, TimeSpan timeout, CancellationToken cancellationToken)
        {
            ObservedTimeout = timeout;
            WorkingDirectory = workingDirectory;
            Directory.CreateDirectory(workingDirectory);
            _entered.TrySetResult();

            if (Block)
            {
                await _release.Task.WaitAsync(cancellationToken);
            }
            else if (_delay > TimeSpan.Zero)
            {
                await Task.Delay(_delay, cancellationToken);
            }

            var path = Path.Combine(workingDirectory, "dump.json");
            await File.WriteAllTextAsync(path, _json ?? "{}", cancellationToken);
            return new UpstreamDump(path, _json ?? "{}", new[] { "controlled dump" });
        }
    }

    private static readonly BuildEntry VerifiedEntry = new(
        "FM27_1", "4530370", "26620374", "27.1.0+2505117", BuildStatus.Verified, "测试用", Array.Empty<string>());

    private static string InstallDirectory()
    {
        var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm006");
        var install = Path.Combine(root, "Football Manager 27");
        Directory.CreateDirectory(Path.Combine(install, "fm_Data", "Plugins", "x86_64"));
        var plugin = Path.Combine(install, "fm_Data", "Plugins", "x86_64", "game_plugin.dll");
        File.WriteAllText(plugin, "stub");
        File.WriteAllText(Path.Combine(install, "steam_appid.txt"), "4530370");
        return install;
    }

    private static string MinimalDump() => System.Text.Json.JsonSerializer.Serialize(new
    {
        meta = new { game = "FM27", gameVersion = "27.1", gameDate = "2026-07-14", versionOk = false, myClub = (string?)null },
        players = new object[]
        {
            new
            {
                id = 1001, name = "Test Player", birthYear = 2000, birthDoy = 32, club = "Test FC",
                ca = 120, pa = 150, value = 1_000_000, wage = 10_000, expires = "2028-06-30",
                nat = new[] { "England" }, pos = "ST", foot = "Rechts", height = 180, teamType = 0,
                attrs = new Dictionary<string, int> { ["Finishing"] = 15, ["InjuryPronation"] = 7 },
            },
        },
    });

    /// <summary>已验证注册表 + 已验证布局 + 通过探测的假内存环境。</summary>
    private static FMSuperScoutMemoryEngine Engine(IUpstreamDumpProvider provider, TimeSpan? timeout, string workRoot)
    {
        var layout = new ScoutMind.FMReader.Layouts.FM27_1_Layout();
        var registration = new BuildRegistration(
            "26620374", "FM27_1", BuildStatus.Verified, "27.1.0+2505117",
            layout.Offsets.Keys.ToList(), new[] { "测试用界面核对" }, "测试用", Array.Empty<string>());
        var registry = new CompatibilityRegistry(new[] { registration });
        var gate = new VersionGate(new[] { VerifiedEntry });
        return new FMSuperScoutMemoryEngine(
            locator: new FixedLocator(4242, InstallDirectory()),
            gate: gate,
            registry: registry,
            dumpProvider: provider,
            mapper: new Integration.UpstreamDumpMapper(),
            workingRoot: workRoot,
            buildResolver: _ => "26620374",
            probeEnvironment: new FakeEnvironment(),
            scanTimeout: timeout);
    }

    public static void Run(TestHarness harness)
    {
        harness.Run("资源：超时参数真正传给读取器", () =>
        {
            var provider = new ControlledProvider(MinimalDump());
            var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm006-work-a");
            var engine = Engine(provider, TimeSpan.FromSeconds(7), root);
            _ = engine.ScanAsync(CancellationToken.None).GetAwaiter().GetResult();
            TestHarness.True(provider.ObservedTimeout is not null && Math.Abs(provider.ObservedTimeout!.Value.TotalSeconds - 7) < 0.5,
                $"实际超时 {provider.ObservedTimeout}");
        });

        harness.Run("资源：读取超时返回失败并清理临时目录", () =>
        {
            var provider = new ControlledProvider(MinimalDump(), TimeSpan.FromSeconds(30));
            var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm006-work-b");
            var engine = Engine(provider, TimeSpan.FromMilliseconds(300), root);
            using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(300));
            var result = engine.ScanAsync(cts.Token).GetAwaiter().GetResult();
            TestHarness.True(result.PayloadJson is null, "超时不能返回数据");
            TestHarness.True(result.FailureReason is not null && result.FailureReason.Contains("取消"),
                result.FailureReason ?? "(null)");
        });

        harness.Run("资源：并发扫描被拒绝且不抢 dump 目录", () =>
        {
            var provider = new ControlledProvider(MinimalDump()) { Block = true };
            var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm006-work-c");
            var engine = Engine(provider, TimeSpan.FromMinutes(1), root);

            var first = Task.Run(() => engine.ScanAsync(CancellationToken.None));
            provider.Entered.Wait(TimeSpan.FromSeconds(5));
            var second = engine.ScanAsync(CancellationToken.None).GetAwaiter().GetResult();
            TestHarness.True(second.FailureReason is not null && second.FailureReason.Contains("已有扫描"),
                second.FailureReason ?? "(null)");
            provider.Release();
            var firstResult = first.GetAwaiter().GetResult();
            TestHarness.True(firstResult.FailureReason is null, firstResult.FailureReason ?? "(null)");
        });

        harness.Run("资源：扫描失败后临时目录被删除", () =>
        {
            var provider = new ControlledProvider(MinimalDump(), TimeSpan.FromSeconds(30));
            var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm006-work-d");
            var engine = Engine(provider, TimeSpan.FromMilliseconds(200), root);
            using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(200));
            _ = engine.ScanAsync(cts.Token).GetAwaiter().GetResult();
            var leftovers = Directory.Exists(root) ? Directory.GetDirectories(root) : Array.Empty<string>();
            TestHarness.True(leftovers.Length == 0, "临时目录应被清理：" + string.Join(",", leftovers.Select(Path.GetFileName)));
        });
    }
}
