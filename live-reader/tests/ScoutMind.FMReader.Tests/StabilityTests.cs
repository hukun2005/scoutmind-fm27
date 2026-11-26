using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>SM-012：字段元数据、合同日期诊断与连续扫描稳定性。</summary>
internal static class StabilityTests
{
    private sealed class FixedLocator : IFmProcessLocator
    {
        private readonly FmProcessLocation _location;

        public FixedLocator(string installDirectory)
        {
            _location = new FmProcessLocation(4242, Path.Combine(installDirectory, "fm.exe"), installDirectory,
                new[] { "stability locator" });
        }

        public FmProcessLocation Locate() => _location;
    }

    private sealed class StableProvider : IUpstreamDumpProvider
    {
        private readonly string _json;
        private readonly Exception? _failure;

        public StableProvider(string json, Exception? failure = null)
        {
            _json = json;
            _failure = failure;
        }

        public int Calls { get; private set; }

        public Task<UpstreamDump> ReadAsync(string workingDirectory, TimeSpan timeout, CancellationToken cancellationToken)
        {
            Calls++;
            Directory.CreateDirectory(workingDirectory);
            if (_failure is not null)
            {
                throw _failure;
            }

            var path = Path.Combine(workingDirectory, "dump.json");
            File.WriteAllText(path, _json);
            return Task.FromResult(new UpstreamDump(path, _json, new[] { "stable dump" }));
        }
    }

    private static readonly BuildEntry VerifiedEntry = new(
        "FM27_1", "4530370", "26620374", "27.1.0+2505117", BuildStatus.Verified, "测试用", Array.Empty<string>());

    private static string InstallDirectory()
    {
        var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm012");
        var install = Path.Combine(root, "Football Manager 27");
        Directory.CreateDirectory(Path.Combine(install, "fm_Data", "Plugins", "x86_64"));
        File.WriteAllText(Path.Combine(install, "fm_Data", "Plugins", "x86_64", "game_plugin.dll"), "stub");
        File.WriteAllText(Path.Combine(install, "steam_appid.txt"), "4530370");
        return install;
    }

    private static string Dump() => System.Text.Json.JsonSerializer.Serialize(new
    {
        meta = new { game = "FM27", gameVersion = "27.1", gameDate = "2026-07-14", versionOk = false, myClub = (string?)null },
        players = new object[]
        {
            new
            {
                id = 1001, name = "Stable Player", birthYear = 2000, birthDoy = 32, club = "Test FC",
                ca = 120, pa = 150, value = 1_000_000, wage = 10_000, expires = "2028-06-30",
                nat = new[] { "England" }, pos = "ST", foot = "Rechts", height = 180, teamType = 0,
                attrs = new Dictionary<string, int> { ["Finishing"] = 15, ["InjuryPronation"] = 7 },
            },
            new
            {
                id = 1002, name = "No Contract Player", birthYear = 1998, birthDoy = 10, club = "Test FC",
                ca = 110, pa = 130, value = 500_000, expires = (string?)null,
                nat = new[] { "England" }, pos = "CB", foot = "Links", height = 185, teamType = 0,
                attrs = new Dictionary<string, int> { ["Heading"] = 14 },
            },
        },
    });

    private static FMSuperScoutMemoryEngine Engine(IUpstreamDumpProvider provider, string workRoot)
    {
        var layout = new FM27_1_Layout();
        var registration = new BuildRegistration(
            "26620374", "FM27_1", BuildStatus.Verified, "27.1.0+2505117",
            layout.Offsets.Keys.ToList(), new[] { "测试用界面核对" }, "测试用", Array.Empty<string>());
        var registry = new CompatibilityRegistry(new[] { registration });
        return new FMSuperScoutMemoryEngine(
            locator: new FixedLocator(InstallDirectory()),
            gate: new VersionGate(new[] { VerifiedEntry }),
            registry: registry,
            dumpProvider: provider,
            mapper: new Integration.UpstreamDumpMapper(),
            workingRoot: workRoot,
            buildResolver: _ => "26620374",
            probeEnvironment: new FakeEnvironment());
    }

    public static void Run(TestHarness harness)
    {
        harness.Run("字段元数据：每个字段都有偏移、类型和证据来源", () =>
        {
            var rows = FieldMetadataCatalog.Build(new FM27_1_Layout());
            TestHarness.True(rows.Count == 50, $"字段数 {rows.Count}");
            TestHarness.True(rows.All(row => row.Name.Length > 0 && row.Offset.StartsWith("0x")), "偏移格式");
            TestHarness.True(rows.All(row => row.Evidence.Length > 0), "每个字段都要写证据来源");
            TestHarness.Equal(11, rows.Count(row => row.Status == "Verified"), "Verified 字段数");
            TestHarness.Equal(7, rows.Count(row => row.Status == "Candidate"), "Candidate 字段数");
        });

        harness.Run("字段证据：没有样本时最高只能是 Candidate", () =>
        {
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout());
            TestHarness.Equal(50, rows.Count, "字段数");
            TestHarness.Equal(0, rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Verified), "无样本不得 Verified");
            TestHarness.Equal(32, rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Pending), "Pending");
            TestHarness.True(rows.All(row => row.FieldId.Length > 0 && row.MemoryOffset.StartsWith("0x")), "标识与偏移");
            TestHarness.True(rows.All(row => row.SampleCount == 0 && row.MismatchCount == 0), "没有样本时计数为 0");
        });

        harness.Run("字段证据：原始值与界面一致才 Verified", () =>
        {
            var observations = new[]
            {
                new ScoutMind.FMReader.Evidence.FieldObservation("PERO_COMMON_NAME", "Player One", "Player One", "2026-11-21T12:00:00Z", "p1"),
                new ScoutMind.FMReader.Evidence.FieldObservation("PERO_COMMON_NAME", "Player Two", "Player Two", "2026-11-21T13:00:00Z", "p2"),
                new ScoutMind.FMReader.Evidence.FieldObservation("PLAO_HEIGHT", "180", "180", "2026-11-21T12:00:00Z", "p1"),
            };
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var ca = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal("Verified", ca.ValidationStatus.ToString(), "注册表 verified + 一致样本");
            TestHarness.Equal(2, ca.SampleCount, "有效样本数");
            var height = rows.Single(row => row.FieldId == "PLAO_HEIGHT");
            TestHarness.True(height.ValidationStatus != ScoutMind.FMReader.Evidence.FieldValidationStatus.Verified, "Candidate 字段不因样本升级");
        });

        harness.Run("字段证据：单次异常不直接 Rejected，保留异常证据", () =>
        {
            var observations = new List<ScoutMind.FMReader.Evidence.FieldObservation>
            {
                new("PERO_COMMON_NAME", "Player One", "Player Two", "2026-11-21T12:00:00Z", "p1"),
                new("PLAO_HEIGHT", "0", "0", "2026-11-21T12:00:00Z", "p1"),
            };
            for (var i = 0; i < 99; i++)
            {
                observations.Add(new ScoutMind.FMReader.Evidence.FieldObservation(
                    "PERO_COMMON_NAME", $"Player {i}", $"Player {i}", $"2026-11-22T{i % 24:00}:00:00Z", $"p{i + 10}"));
            }
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var name = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal("Candidate", name.ValidationStatus.ToString(), "1/100 在允许比例内");
            TestHarness.True(name.NeedsReview, "需要人工复核");
            TestHarness.Equal(1, name.Anomalies!.Count, "保留异常证据");
            TestHarness.Equal(99, name.MatchCount, "匹配计数");
            var height = rows.Single(row => row.FieldId == "PLAO_HEIGHT");
            TestHarness.Equal(1, height.SampleCount, "0 与 0 也是有效配对的观测");
            TestHarness.Equal(0, height.MismatchCount, "0 与 0 一致");
        });

        harness.Run("字段证据：持续异常超过阈值才 Rejected", () =>
        {
            var observations = new List<ScoutMind.FMReader.Evidence.FieldObservation>();
            for (var i = 0; i < 100; i++)
            {
                var mismatch = i < 5;
                observations.Add(new ScoutMind.FMReader.Evidence.FieldObservation(
                    "PERO_COMMON_NAME", $"Raw {i}", mismatch ? $"Expected {i}" : $"Raw {i}",
                    $"2026-11-22T{i % 24:00}:00:00Z", $"obj-{i}"));
            }
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var name = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal("Rejected", name.ValidationStatus.ToString(), "5/100 超过允许比例");
            TestHarness.Equal(5, name.MismatchCount, "异常数");
            TestHarness.Equal(0.95, name.ObservedMatchRate, "匹配率");
        });

        harness.Run("字段证据：系统性重复异常即使比例低也 Rejected", () =>
        {
            var observations = new List<ScoutMind.FMReader.Evidence.FieldObservation>();
            for (var i = 0; i < 200; i++)
            {
                var anomaly = i < 3;
                observations.Add(new ScoutMind.FMReader.Evidence.FieldObservation(
                    "PERO_COMMON_NAME", anomaly ? "same-raw" : $"ok-{i}", anomaly ? "same-expected" : $"ok-{i}",
                    $"2026-11-23T{i % 24:00}:00:00Z", $"obj-{i}"));
            }
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var name = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal("Rejected", name.ValidationStatus.ToString(), "同一异常重复 3 次");
        });

        harness.Run("字段证据：不同对象的独立异常保持 Candidate", () =>
        {
            var observations = new List<ScoutMind.FMReader.Evidence.FieldObservation>();
            for (var i = 0; i < 100; i++)
            {
                observations.Add(new ScoutMind.FMReader.Evidence.FieldObservation(
                    "PERO_COMMON_NAME", i < 2 ? $"bad-{i}" : $"ok-{i}", $"ok-{i}",
                    $"2026-11-24T{i % 24:00}:00:00Z", $"obj-{i}"));
            }
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var name = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal("Candidate", name.ValidationStatus.ToString(), "2/100 不同异常");
            TestHarness.True(name.NeedsReview, "人工复核");
        });

        harness.Run("字段证据：日期跨时区标准化与缺失样本", () =>
        {
            var observations = new[]
            {
                new ScoutMind.FMReader.Evidence.FieldObservation("CON_EXPIRY", "2026-07-01T23:00:00-05:00", "2026-07-02", "2026-11-25T12:00:00Z", "c1"),
                new ScoutMind.FMReader.Evidence.FieldObservation("CON_EXPIRY", null, "2026-07-02", "2026-11-25T12:00:00Z", "c2"),
                new ScoutMind.FMReader.Evidence.FieldObservation("CON_EXPIRY", "", null, "2026-11-25T12:00:00Z", "c3"),
            };
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            var expiry = rows.Single(row => row.FieldId == "CON_EXPIRY");
            TestHarness.Equal(1, expiry.SampleCount, "只有原始值 + 界面值配对才算样本");
            TestHarness.Equal(2, expiry.MissingSampleCount, "缺失样本单独计数");
            TestHarness.Equal("date", expiry.ComparisonKind, "日期比较器");
            TestHarness.Equal(0, expiry.MismatchCount, "跨时区同一天应一致");
        });

        harness.Run("字段证据：独立对象/观测计数与门槛", () =>
        {
            var observations = new[]
            {
                new ScoutMind.FMReader.Evidence.FieldObservation("PERO_COMMON_NAME", "A", "A", "2026-11-21T12:00:00Z", "obj-1"),
                new ScoutMind.FMReader.Evidence.FieldObservation("PERO_COMMON_NAME", "B", "B", "2026-11-21T13:00:00Z", "obj-2"),
            };
            var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(
                new FM27_1_Layout(),
                observations: observations,
                options: new ScoutMind.FMReader.Evidence.FieldEvidenceOptions(MinimumUniqueObjects: 2, MinimumSamples: 2));
            var name = rows.Single(row => row.FieldId == "PERO_COMMON_NAME");
            TestHarness.Equal(2, name.SampleCount, "样本数");
            TestHarness.Equal(2, name.UniqueObjectCount, "独立对象数");
            TestHarness.Equal(2, name.UniqueObservationCount, "独立观测时间数");
            TestHarness.Equal("Verified", name.ValidationStatus.ToString(), "达到对象门槛");
            TestHarness.True(name.Confidence is null, "未校准的 confidence 必须为 null");
        });

        harness.Run("字段证据：数值容差与日期标准化", () =>
        {
            var observations = new[]
            {
                new ScoutMind.FMReader.Evidence.FieldObservation("PLAO_CA", "150", "151", "2026-11-21T12:00:00Z", "obj-1"),
                new ScoutMind.FMReader.Evidence.FieldObservation("PLAO_HEIGHT", "180", "180", "2026-11-21T12:00:00Z", "obj-1"),
            };
            var strict = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(new FM27_1_Layout(), observations: observations);
            TestHarness.Equal("Rejected", strict.Single(row => row.FieldId == "PLAO_CA").ValidationStatus.ToString(), "严格容差");
            var tolerant = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(
                new FM27_1_Layout(),
                observations: observations,
                options: new ScoutMind.FMReader.Evidence.FieldEvidenceOptions(NumericTolerance: 1.0));
            TestHarness.True(tolerant.Single(row => row.FieldId == "PLAO_CA").MismatchCount == 0, "容差 1 内一致");
            TestHarness.Equal("numeric", tolerant.Single(row => row.FieldId == "PLAO_CA").ComparisonKind, "数值比较器");
        });

        harness.Run("字段采样：同一球员同一观测时间去重", () =>
        {
            var store = new ScoutMind.FMReader.Evidence.FieldValidationCaptureStore();
            var item = new ScoutMind.FMReader.Evidence.FieldValidationCapture(
                "CON_EXPIRY", "P-1", "contract", "0x1", "2027-06-30", "26620374",
                "27.1.0+2505117", "FM27_1", "2026-07-01", "2026-11-21T12:00:00Z", "simulated", "Pending", true);
            TestHarness.True(store.Add(item), "第一次加入");
            TestHarness.True(!store.Add(item), "重复键被拒绝");
            TestHarness.Equal(1, store.Count, "只计一次");
            var csv = store.ToCsv();
            TestHarness.True(csv.StartsWith("FieldId,PlayerInstanceUID", StringComparison.Ordinal), "CSV 表头");
            TestHarness.True(csv.Contains("CON_EXPIRY", StringComparison.Ordinal), "CSV 字段");
            TestHarness.True(store.ToJson().Contains("Simulated", StringComparison.Ordinal), "JSON 保留模拟标记");
        });

        harness.Run("字段元数据：Candidate 不会被整体升级为 Verified", () =>
        {
            var rows = FieldMetadataCatalog.Build(new FM27_1_Layout());
            var height = rows.FirstOrDefault(row => row.Name == "PLAO_HEIGHT");
            TestHarness.True(height is not null, "身高字段必须存在");
            TestHarness.Equal("Candidate", height!.Status, "身高仍是 Candidate");
            TestHarness.True(height.Evidence.Contains("upstream_agreement_fields"), height.Evidence);
        });

        harness.Run("合同日期诊断：未设置与全 1 哨兵分开统计", () =>
        {
            var diagnostics = new ContractDateDiagnostics();
            diagnostics.Add(0);
            diagnostics.Add(uint.MaxValue);
            TestHarness.Equal(1, diagnostics.Count(ContractDateCategory.Unset), "0 算未设置");
            TestHarness.Equal(1, diagnostics.Count(ContractDateCategory.Sentinel), "全 1 算哨兵");
            TestHarness.Equal(0.0, diagnostics.DecodableRatio, "没有可解码样本时比例为 0");
        });

        harness.Run("合同日期诊断：年份/序日越界能区分", () =>
        {
            var badDoy = ContractDateDiagnostics.Analyze((uint)(2028 << 16 | 0));
            TestHarness.Equal(ContractDateCategory.BadDayOfYear, badDoy.Category, "序日 0");
            var badYear = ContractDateDiagnostics.Analyze((uint)(1800 << 16 | 10));
            TestHarness.Equal(ContractDateCategory.OutOfRange, badYear.Category, "年份越界");
            var ok = ContractDateDiagnostics.Analyze((uint)(2028 << 16 | 180));
            TestHarness.Equal(ContractDateCategory.Decodable, ok.Category, "正常日期");
            TestHarness.Equal(2028, ok.Year, "年份");
        });

        harness.Run("稳定性：同一存档连续 10 次扫描结果一致", () =>
        {
            var provider = new StableProvider(Dump());
            var engine = Engine(provider, Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm012-work-a"));
            var payloads = new List<string>();
            for (var index = 0; index < 10; index++)
            {
                var result = engine.ScanAsync(CancellationToken.None).GetAwaiter().GetResult();
                TestHarness.True(result.PayloadJson is not null, $"第 {index + 1} 次扫描失败：{result.FailureReason}");
                payloads.Add(result.PayloadJson!);
            }

            TestHarness.True(payloads.Distinct(StringComparer.Ordinal).Count() == 1, "10 次扫描的报文必须完全一致");
            TestHarness.Equal(10, provider.Calls, "每次扫描都要真正读取");
        });

        harness.Run("稳定性：无合同球员不会中断扫描", () =>
        {
            var engine = Engine(new StableProvider(Dump()), Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm012-work-b"));
            var result = engine.ScanAsync(CancellationToken.None).GetAwaiter().GetResult();
            TestHarness.True(result.FailureReason is null, result.FailureReason ?? "(null)");
            TestHarness.Equal(2, result.Players, "两名球员都应被读取");
        });

        harness.Run("稳定性：读取失败（进程退出）返回失败而不是空数据", () =>
        {
            var engine = Engine(
                new StableProvider(Dump(), new UpstreamReadException("fm.exe 已退出")),
                Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm012-work-c"));
            var result = engine.ScanAsync(CancellationToken.None).GetAwaiter().GetResult();
            TestHarness.True(result.PayloadJson is null, "失败时不能返回报文");
            TestHarness.True(result.FailureReason?.Contains("退出") == true, result.FailureReason ?? "(null)");
        });

        harness.Run("稳定性：扫描前已取消则立即失败", () =>
        {
            var engine = Engine(new StableProvider(Dump()), Path.Combine(AppContext.BaseDirectory, "test-tmp", "sm012-work-d"));
            using var cts = new CancellationTokenSource();
            cts.Cancel();
            var result = engine.ScanAsync(cts.Token).GetAwaiter().GetResult();
            TestHarness.True(result.FailureReason is not null, "取消必须给出原因");
        });
    }
}
