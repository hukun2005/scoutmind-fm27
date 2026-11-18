using System.Text.Json;
using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>引擎编排：闸门拒绝时不读内存；放行后读取并映射；失败时明确报告。</summary>
internal static class EngineTests
{
    private sealed class FixedLocator : IFmProcessLocator
    {
        private readonly FmProcessLocation _location;

        public FixedLocator(int? pid, string? installDirectory)
        {
            _location = new FmProcessLocation(pid, pid is null ? null : Path.Combine(installDirectory!, "fm.exe"),
                installDirectory, new[] { "test locator" });
        }

        public FmProcessLocation Locate() => _location;
    }

    private sealed class StubDumpProvider : IUpstreamDumpProvider
    {
        private readonly string? _json;
        private readonly Exception? _failure;
        private int _calls;

        public StubDumpProvider(string? json = null, Exception? failure = null)
        {
            _json = json;
            _failure = failure;
        }

        public int Calls => _calls;

        public Task<UpstreamDump> ReadAsync(string workingDirectory, TimeSpan timeout, CancellationToken cancellationToken)
        {
            _calls++;
            Directory.CreateDirectory(workingDirectory);
            if (_failure is not null)
            {
                throw _failure;
            }

            var path = Path.Combine(workingDirectory, "dump.json");
            File.WriteAllText(path, _json ?? "{}");
            return Task.FromResult(new UpstreamDump(path, _json ?? "{}", new[] { "stub dump" }));
        }
    }

    private static readonly BuildEntry VerifiedEntry = new(
        "FM27", "4530370", "26620374", "27.1.0+2505117", BuildStatus.Verified, "测试用：已验证", Array.Empty<string>());

    private static readonly BuildEntry CandidateEntry = new(
        "FM27", "4530370", "26620374", "27.1.0+2505117", BuildStatus.Candidate, "未核对 27.1", Array.Empty<string>());

    private static string InstallDirectory()
    {
        var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "engine");
        var install = Path.Combine(root, "Football Manager 27");
        Directory.CreateDirectory(Path.Combine(install, "fm_Data", "Plugins", "x86_64"));
        var plugin = Path.Combine(install, "fm_Data", "Plugins", "x86_64", "game_plugin.dll");
        if (!File.Exists(plugin))
        {
            File.WriteAllText(plugin, "stub");
        }

        File.WriteAllText(Path.Combine(install, "steam_appid.txt"), "4530370");
        return install;
    }

    private static FMSuperScoutMemoryEngine Engine(
        VersionGate gate,
        IUpstreamDumpProvider provider,
        int? pid = 4242)
    {
        return new FMSuperScoutMemoryEngine(
            locator: new FixedLocator(pid, InstallDirectory()),
            gate: gate,
            dumpProvider: provider,
            mapper: new Integration.UpstreamDumpMapper(),
            workingRoot: Path.Combine(AppContext.BaseDirectory, "test-tmp", "engine-work"),
            buildResolver: _ => "26620374");
    }

    private static string MinimalDump() => JsonSerializer.Serialize(new
    {
        meta = new { game = "FM27", gameVersion = "27.1", gameDate = "2026-07-14", myClub = (string?)null, versionOk = false },
        players = new object[]
        {
            new
            {
                id = 1001, name = "Test Player", birthYear = 2000, birthDoy = 32, club = "Test FC",
                ca = 120, pa = 150, value = 1_000_000, wage = 10_000, expires = "2028-06-30",
                nat = new[] { "England" }, pos = "ST", foot = "Rechts", height = 180, listed = true,
                teamType = 0, attrs = new Dictionary<string, int> { ["Finishing"] = 15, ["InjuryProneness"] = 7 },
            },
        },
    });

    public static async Task RunAsync(TestHarness harness)
    {
        await harness.RunAsync("引擎：candidate 构建时 probe 拒绝且不读内存", async () =>
        {
            var provider = new StubDumpProvider(MinimalDump());
            var engine = Engine(new VersionGate(new[] { CandidateEntry }), provider);
            var probe = await engine.ProbeAsync(CancellationToken.None);
            TestHarness.True(!probe.Passed, "candidate 必须 probe 失败");
            TestHarness.Contains(probe.Reason ?? string.Empty, "未验证", "应说明未验证");
            TestHarness.Equal(0, provider.Calls, "拒绝时不得读取内存");
        });

        await harness.RunAsync("引擎：candidate 构建时 scan 拒绝且不产生协议报文", async () =>
        {
            var provider = new StubDumpProvider(MinimalDump());
            var engine = Engine(new VersionGate(new[] { CandidateEntry }), provider);
            var result = await engine.ScanAsync(CancellationToken.None);
            TestHarness.Equal<string?>(null, result.PayloadJson, "拒绝时不得输出报文");
            TestHarness.Equal(0, result.Players, "拒绝时球员数为 0");
            TestHarness.True(!string.IsNullOrWhiteSpace(result.FailureReason), "必须给出失败原因");
            TestHarness.Equal(0, provider.Calls, "拒绝时不得读取内存");
        });

        await harness.RunAsync("引擎：verified 构建时读取并映射出协议报文", async () =>
        {
            var provider = new StubDumpProvider(MinimalDump());
            var engine = Engine(new VersionGate(new[] { VerifiedEntry }), provider);
            var result = await engine.ScanAsync(CancellationToken.None);
            TestHarness.True(result.PayloadJson is not null, "应输出报文");
            TestHarness.Equal(1, provider.Calls, "应读取一次内存");
            TestHarness.Equal(1, result.Players, "球员数");
            TestHarness.Equal(1, result.Clubs, "俱乐部数（从球员行派生）");
            TestHarness.True(result.Warnings.Any(text => text.Contains("版本闸门", StringComparison.Ordinal)),
                "告警里应包含版本闸门结论");

            using var document = JsonDocument.Parse(result.PayloadJson!);
            var root = document.RootElement;
            TestHarness.Equal("1.0", root.GetProperty("schema_version").GetString(), "协议版本");
            TestHarness.Equal("26620374", root.GetProperty("game").GetProperty("build").GetString(), "构建号");
            var player = root.GetProperty("players")[0];
            TestHarness.Equal("1001", player.GetProperty("save_local_uid").GetString(), "球员 ID");
            TestHarness.Equal("Test FC", root.GetProperty("clubs")[0].GetProperty("name").GetString(), "俱乐部名称");
            TestHarness.True(player.TryGetProperty("availability", out var availability)
                && availability.GetProperty("listed").GetBoolean(), "挂牌标记应写入 availability");
        });

        await harness.RunAsync("引擎：上游读取失败时返回失败而不是空数据", async () =>
        {
            var provider = new StubDumpProvider(failure: new UpstreamReadException("进程打不开"));
            var engine = Engine(new VersionGate(new[] { VerifiedEntry }), provider);
            var result = await engine.ScanAsync(CancellationToken.None);
            TestHarness.Equal<string?>(null, result.PayloadJson, "失败时不得输出报文");
            TestHarness.Contains(result.FailureReason ?? string.Empty, "进程打不开", "应冒泡上游原因");
        });

        await harness.RunAsync("引擎：没有构建号时 status 明确拒绝", async () =>
        {
            var engine = new FMSuperScoutMemoryEngine(
                locator: new FixedLocator(4242, InstallDirectory()),
                gate: new VersionGate(new[] { VerifiedEntry }),
                dumpProvider: new StubDumpProvider(MinimalDump()),
                buildResolver: _ => null);
            var status = await engine.GetStatusAsync(CancellationToken.None);
            TestHarness.True(status.Gate is not null && !status.Gate.AllowScan, "没有构建号时必须拒绝");
            TestHarness.Equal<string?>(null, status.Build, "构建号必须为 null，不得猜");
        });

        await harness.RunAsync("引擎：FM 未运行时 probe 给出明确原因", async () =>
        {
            var engine = new FMSuperScoutMemoryEngine(
                locator: new FixedLocator(null, InstallDirectory()),
                gate: new VersionGate(new[] { VerifiedEntry }),
                dumpProvider: new StubDumpProvider(MinimalDump()),
                buildResolver: _ => "26620374");
            var probe = await engine.ProbeAsync(CancellationToken.None);
            TestHarness.True(!probe.Passed, "未运行时 probe 必须失败");
            TestHarness.Contains(probe.Reason ?? string.Empty, "未运行", "应提示 FM 未运行");
        });
    }
}
