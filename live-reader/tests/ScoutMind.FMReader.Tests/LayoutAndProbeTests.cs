using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>布局隔离、布局解析、注册表与探测逻辑。</summary>
internal static class LayoutAndProbeTests
{
    public static void Run(TestHarness harness)
    {
        LayoutTests(harness);
        ProbeTests(harness);
        ReportTests(harness);
    }

    private static void LayoutTests(TestHarness harness)
    {
        harness.Run("布局：27.0 与 27.1 是两份独立对象", () =>
        {
            var layout27 = new FM27_0_Layout();
            var layout271 = new FM27_1_Layout();
            TestHarness.True(!ReferenceEquals(layout27, layout271), "必须是不同实例");
            TestHarness.Equal("FM27_0", layout27.Name, "27.0 布局名");
            TestHarness.Equal("FM27_1", layout271.Name, "27.1 布局名");
            TestHarness.Equal(FieldStatus.Candidate, layout27.Status, "27.0 只有上游证据，未由 ScoutMind 复现");
            TestHarness.Equal(FieldStatus.Pending, layout271.Status, "27.1 的字段全部未核对");
        });

        harness.Run("布局：修改 27.1 的字段状态不影响 27.0", () =>
        {
            var layout27 = new FM27_0_Layout();
            var layout271 = new FM27_1_Layout();
            layout271.Mark("PLAO_CA", FieldStatus.Failed, EvidenceKind.InternalCheck, "test", "模拟 27.1 探测失败");
            TestHarness.Equal(FieldStatus.Candidate, layout27.Verification("PLAO_CA").Status, "27.0 不应受影响");
            TestHarness.Equal(FieldStatus.Failed, layout271.Verification("PLAO_CA").Status, "27.1 应更新");
            TestHarness.Equal(FieldStatus.Failed, layout271.Status, "27.1 整体状态应为 Rejected");
        });

        harness.Run("布局：27.1 的偏移目前与 27.0 相同（复制假设，不等于已验证）", () =>
        {
            var layout27 = new FM27_0_Layout();
            var layout271 = new FM27_1_Layout();
            foreach (var (field, offset) in layout27.Offsets)
            {
                TestHarness.Equal(offset, layout271.Offsets[field], $"字段 {field} 的偏移应一致");
            }
        });

        harness.Run("布局：未定义字段抛异常而不是返回 0", () =>
        {
            var layout = new FM27_1_Layout();
            TestHarness.Throws<KeyNotFoundException>(() => _ = layout["NOT_A_FIELD"], "未知字段必须抛异常");
            TestHarness.Equal(FieldStatus.NotSupported, layout.Verification("NOT_A_FIELD").Status, "未知字段状态为 NotSupported");
        });

        harness.Run("解析器：构建号 → 布局，未登记构建返回 null", () =>
        {
            var resolver = new LayoutResolver();
            TestHarness.Equal("FM27_1", resolver.Resolve("26620374")?.Name, "本机构建应解析到 27.1 布局");
            TestHarness.Equal("FM27_0", resolver.Resolve("26577676")?.Name, "27.0 构建应解析到 27.0 布局");
            TestHarness.Equal<string?>(null, resolver.Resolve("99999999")?.Name, "未登记构建必须返回 null");
            TestHarness.Equal<string?>(null, resolver.Resolve(null)?.Name, "没有构建号必须返回 null");
            TestHarness.True(!LayoutResolver.IsRegistered("99999999"), "未登记构建 IsRegistered 应为 false");
        });

        harness.Run("注册表：默认清单里本机构建已核对 → 允许扫描", () =>
        {
            var registry = new CompatibilityRegistry();
            var entry = registry.For("26620374");
            TestHarness.True(entry is not null, "本机构建应在注册表中");
            TestHarness.Equal(BuildStatus.Verified, entry!.Status, "2026-11-19 已核对 → verified");
            TestHarness.True(registry.AllowsScan("26620374"), "verified 允许扫描");
            TestHarness.True(!registry.AllowsScan("99999999"), "未登记构建不允许扫描");
            TestHarness.Equal("FM27_1", entry.Layout, "应指向 27.1 布局");
        });

        harness.Run("注册表：verified 条目会把握手字段标为 Verified", () =>
        {
            var registry = new CompatibilityRegistry(new[]
            {
                new BuildRegistration("1234", "FM27_1", BuildStatus.Verified, "27.1", new[] { "PLAO_CA", "PLAO_PA" },
                    new[] { "unit-test" }, "测试"),
            });
            var layout = new FM27_1_Layout();
            registry.Apply("1234", layout);
            TestHarness.Equal(FieldStatus.Verified, layout.Verification("PLAO_CA").Status, "列出的字段应 verified");
            TestHarness.Equal(FieldStatus.Pending, layout.Verification("CLUB_NAME").Status, "未列出的字段仍为 pending");
            TestHarness.True(registry.AllowsScan("1234"), "verified 构建允许扫描");
        });
    }

    private static void ProbeTests(TestHarness harness)
    {
        harness.Run("球员探测：结构自洽的假存档通过", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Player {index}"))
                .ToList();
            var outcome = new ObjectProbes(memory, layout).ProbePlayers(players);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
            TestHarness.True(outcome.Checks.Count(item => item.Status == CheckStatus.Passed) >= 8, "应有至少 8 项通过");
        });

        harness.Run("球员探测：CA 偏移错位（越界）时失败", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            // 模拟 27.1 改了偏移：CA 读到别处的数据，越界。
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, ca: 500, pa: 600, name: $"P{index}"))
                .ToList();
            var outcome = new ObjectProbes(memory, layout).ProbePlayers(players);
            TestHarness.Equal(ProbeStatus.Failed, outcome.Status, "越界必须判失败");
            TestHarness.True(outcome.Checks.Any(item => item.Name == "ca_range" && item.Status == CheckStatus.Failed),
                "ca_range 应为失败");
        });

        harness.Run("完整性探测：重复定位对象不算重复 UID", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"UID {index}"))
                .ToList();
            players.Add(players[0]);
            var outcome = new ObjectProbes(memory, layout).ProbeIntegrity(players, Array.Empty<LocatedObject>());
            TestHarness.True(outcome.ObjectIds!.DuplicateObjectAddressCount == 1, "应识别 1 个重复对象地址");
            TestHarness.True(outcome.ObjectIds.DuplicateUidCount == 0, "重复对象不能算重复 UID");
            TestHarness.True(outcome.Checks.Any(item => item.Name == "unique_uids" && item.Status == CheckStatus.Passed), "UID 唯一性应通过");
        });

        harness.Run("完整性探测：确认自由球员的哨兵 UID 不计入适用分母", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Free {index}"))
                .ToList();
            memory.WriteUInt32(players[0].Db + layout["OBJ_DUNI"], 0xFFFFFFFF);
            memory.WritePointer(players[0].Person + layout["PERO_FULL_CONTRACT"], 0);
            var outcome = new ObjectProbes(memory, layout).ProbeIntegrity(players, Array.Empty<LocatedObject>());
            TestHarness.True(outcome.ObjectIds!.FreeAgentCandidateCount == 1, "应识别 1 个自由球员候选");
            TestHarness.True(outcome.Checks.Any(item => item.Name == "uid_valid" && item.Status == CheckStatus.Passed), "适用 UID 仍应通过");
            TestHarness.Equal(1, outcome.ObjectIds.SentinelSamples.Count, "哨兵明细必须完整");
        });

        harness.Run("完整性探测：零 UID 计入无效而不是重复", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Zero {index}"))
                .ToList();
            memory.WriteUInt32(players[0].Db + layout["OBJ_DUNI"], 0);
            var outcome = new ObjectProbes(memory, layout).ProbeIntegrity(players, Array.Empty<LocatedObject>());
            TestHarness.True(outcome.ObjectIds!.ZeroUidCount == 1, "应识别 1 个零 UID");
            TestHarness.True(outcome.ObjectIds.DuplicateUidCount == 0, "零 UID 不能算重复 UID");
            TestHarness.True(outcome.Checks.Any(item => item.Name == "uid_valid" && item.Status == CheckStatus.Failed), "合法比例不足应失败");
        });

        harness.Run("合同探测：1900 占位纪元按空合同排除，不拉低到期日通过率", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 8)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Contract {index}"))
                .ToList();
            foreach (var player in players.Take(3))
            {
                var contract = memory.Pointer(player.Person + layout["PERO_FULL_CONTRACT"]);
                memory.WriteUInt32(contract + layout["CON_EXPIRY"], (1900u << 16) | 2u);
            }

            var outcome = new ObjectProbes(memory, layout).ProbeContracts(players);
            var range = outcome.Checks.First(item => item.Name == "expiry_range");
            TestHarness.Equal(CheckStatus.Passed, range.Status, "空合同不能被算成读取失败");
            TestHarness.True(range.Detail.Contains("3 人无到期日"), range.Detail);
            var afterBirth = outcome.Checks.First(item => item.Name == "expiry_after_birth");
            TestHarness.Equal(CheckStatus.Passed, afterBirth.Status, "剩余合同仍应全部满足到期日晚于出生");
        });

        harness.Run("合同日期诊断：1900 纪元归为 NoExpiry 而不是年份异常", () =>
        {
            var sample = ContractDateDiagnostics.Analyze((1900u << 16) | 2u);
            TestHarness.Equal(ContractDateCategory.NoExpiry, sample.Category, "1900 是空合同占位纪元");
            var diagnostics = new ContractDateDiagnostics();
            diagnostics.Add((1900u << 16) | 2u);
            diagnostics.Add((2028u << 16) | 180u);
            TestHarness.Equal(1.0, diagnostics.DecodableRatio, "空合同必须排除出可解码比例的分母");
        });

        harness.Run("球员探测：没有对象时候返回失败而不是通过", () =>
        {
            var layout = new FM27_1_Layout();
            var outcome = new ObjectProbes(new FakeMemory(), layout).ProbePlayers(Array.Empty<LocatedObject>());
            TestHarness.Equal(ProbeStatus.Failed, outcome.Status, "空样本必须失败（说明分类器找不到球员）");
        });

        harness.Run("俱乐部探测：名称与球队向量都合理时通过", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var clubs = Enumerable.Range(0, 4).Select(index => FakeSave.WriteClub(memory, layout, index, $"Club {index}")).ToList();
            var outcome = new ObjectProbes(memory, layout).ProbeClubs(clubs);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
        });

        harness.Run("球队探测：合同→球队→俱乐部链路与球员向量一致时通过", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var club = FakeSave.WriteClub(memory, layout, 0, "Chain FC");
            var players = Enumerable.Range(0, 6)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Chain {index}", clubAddress: club.Address))
                .ToList();
            var outcome = new ObjectProbes(memory, layout).ProbeTeams(players);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
        });

        harness.Run("球队探测：球员不在自己球队向量里时跨字段检查失败", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Ghost {index}", includeInTeam: false))
                .ToList();
            // 把球队向量的第一个指针改成别的地址，模拟关系不一致。
            foreach (var player in players)
            {
                var contract = memory.Pointer(player.Person + layout["PERO_FULL_CONTRACT"]);
                var team = memory.Pointer(contract + layout["CON_TEAM"]);
                var begin = memory.Pointer(team + layout["TEAM_PLAYERS_BEGIN"]);
                memory.WritePointer(begin, 0x1);
            }

            var outcome = new ObjectProbes(memory, layout).ProbeTeams(players);
            TestHarness.True(outcome.Checks.Any(item => item.Name == "player_in_team" && item.Status == CheckStatus.Inconclusive),
                "player_in_team 现在是信息性检查（Inconclusive）");
        });

        harness.Run("合同探测：到期日/工资/状态位合法时通过", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Contract {index}"))
                .ToList();
            var outcome = new ObjectProbes(memory, layout).ProbeContracts(players);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
        });

        harness.Run("租借探测：布局没有租借字段时明确 NotApplicable", () =>
        {
            var outcome = new ObjectProbes(new FakeMemory(), new FM27_1_Layout()).ProbeLoans();
            TestHarness.Equal(ProbeStatus.NotApplicable, outcome.Status, "没有租借字段时必须标为不适用");
            TestHarness.Contains(outcome.Note ?? string.Empty, "CSV", "应说明租借只能来自 CSV");
        });

        harness.Run("转会探测：没有记录时 Inconclusive，哨兵不符时 Failed", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var probes = new ObjectProbes(memory, layout);
            TestHarness.Equal(ProbeStatus.Inconclusive, probes.ProbeTransfers(Array.Empty<ulong>()).Status,
                "没有样本时必须 Inconclusive");

            var deals = new List<ulong>();
            for (var index = 0; index < 4; index++)
            {
                var deal = FakeSave.Base + 0x800_000 + (ulong)(index * 0x100);
                memory.Write(deal, new byte[0x100]);
                memory.WriteUInt32(deal + layout["DEAL_SENT1"], 0xFFFFFFFF);
                memory.WriteUInt32(deal + layout["DEAL_SENT2"], 0x076C0001);
                memory.Write(deal + layout["DEAL_STATUS"], new byte[] { 0x13 });
                memory.Write(FakeSave.Base, new byte[0x40]);
                memory.WritePointer(deal + layout["DEAL_TO_TEAM"], FakeSave.Base);
                memory.WritePointer(deal + layout["DEAL_FROM_TEAM"], FakeSave.Base + 0x10);
                memory.WriteUInt32(deal + layout["DEAL_DATE"], (2026u << 16) | 100u);
                deals.Add(deal);
            }

            var good = probes.ProbeTransfers(deals); TestHarness.Equal(ProbeStatus.Passed, good.Status, "形状正确的记录应通过：" + string.Join("; ", good.Checks.Where(c => c.Status != CheckStatus.Passed).Select(c => c.Detail)));

            memory.WriteUInt32(deals[0] + layout["DEAL_SENT1"], 0x12345678);
            var failed = probes.ProbeTransfers(deals);
            TestHarness.True(failed.Checks.Any(item => item.Name == "deal_sentinels" && item.Status == CheckStatus.Failed),
                "哨兵被破坏后应失败");
        });

        harness.Run("完整性：样本量不足时失败，UID 重复时失败", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var club = FakeSave.WriteClub(memory, layout, 0, "Integrity FC");
            var few = new List<LocatedObject> { FakeSave.WritePlayer(memory, layout, 0, name: "Solo") };
            var probes = new ObjectProbes(memory, layout);
            TestHarness.Equal(ProbeStatus.Failed, probes.ProbeIntegrity(few, new[] { club }).Status,
                "样本量不足 20 应失败");

            var many = Enumerable.Range(0, 24).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"U{index}")).ToList();
            TestHarness.Equal(ProbeStatus.Passed, probes.ProbeIntegrity(many, new[] { club }).Status,
                "24 名唯一球员应通过");
        });
    }

    private static void ReportTests(TestHarness harness)
    {
        harness.Run("报告：27.1 字段全 Unknown 时整体最多 Candidate，且禁止扫描", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 24).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Report {index}")).ToList();
            var clubs = new[] { FakeSave.WriteClub(memory, layout, 0, "Report FC") };
            var probes = new ObjectProbes(memory, layout);
            var outcomes = new List<ProbeOutcome>
            {
                probes.ProbePlayers(players),
                probes.ProbeClubs(clubs),
                probes.ProbeTeams(players),
                probes.ProbeContracts(players),
                probes.ProbeLoans(),
                probes.ProbeTransfers(Array.Empty<ulong>()),
                probes.ProbeIntegrity(players, clubs),
            };
            var report = ReportBuilder.Build("test", "26620374", "27.1.0+2505117", "4530370", layout, outcomes,
                Array.Empty<string>(), Array.Empty<string>());
            TestHarness.Equal(OverallStatus.Candidate, report.Overall, "结构通过但字段未核对 → Candidate。实际探测：" + string.Join(" | ", outcomes.Select(item => $"{item.Name}={item.Status}:" + string.Join(",", item.Checks.Where(c => c.Status != CheckStatus.Passed).Select(c => c.Detail)))));
            TestHarness.True(!report.ScanAllowed, "Candidate 不允许扫描");
            TestHarness.Contains(report.Summary, "禁止正式扫描", "结论要写明禁止扫描");
        });

        harness.Run("报告：字段全部 Verified 且探测通过时 Verified 且允许扫描", () =>
        {
            var layout = new FM27_1_Layout();
            foreach (var field in layout.Offsets.Keys)
            {
                layout.Mark(field, FieldStatus.Verified, EvidenceKind.GameUiAgreement, "unit-test", "测试");
            }

            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 24).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Verified {index}")).ToList();
            var clubs = new[] { FakeSave.WriteClub(memory, layout, 0, "Verified FC") };
            var probes = new ObjectProbes(memory, layout);
            var outcomes = new List<ProbeOutcome>
            {
                probes.ProbePlayers(players),
                probes.ProbeClubs(clubs),
                probes.ProbeTeams(players),
                probes.ProbeContracts(players),
                probes.ProbeLoans(),
                probes.ProbeIntegrity(players, clubs),
            };
            var report = ReportBuilder.Build("test", "26620374", "27.1", "4530370", layout, outcomes,
                Array.Empty<string>(), Array.Empty<string>());
            TestHarness.Equal(OverallStatus.Verified, report.Overall, "全部通过时应 Verified。实际探测：" + string.Join(" | ", outcomes.Select(item => $"{item.Name}={item.Status}:" + string.Join(",", item.Checks.Where(c => c.Status != CheckStatus.Passed).Select(c => c.Detail)))));
            TestHarness.True(report.ScanAllowed, "Verified 允许扫描");
        });

        harness.Run("报告：任一探测失败时整体 Rejected", () =>
        {
            var layout = new FM27_1_Layout();
            var outcomes = new List<ProbeOutcome>
            {
                new("player", ProbeStatus.Failed, 0, new[] { new FieldCheck("player_objects_found", CheckStatus.Failed, "none") }),
            };
            var report = ReportBuilder.Build("test", "26620374", "27.1", "4530370", layout, outcomes,
                Array.Empty<string>(), Array.Empty<string>());
            TestHarness.Equal(OverallStatus.Rejected, report.Overall, "探测失败必须 Rejected");
            TestHarness.True(!report.ScanAllowed, "Rejected 不允许扫描");
        });

        harness.Run("报告：布局未登记时 Unknown", () =>
        {
            var report = ReportBuilder.Build("test", "99999999", "27.2", "4530370", null,
                Array.Empty<ProbeOutcome>(), Array.Empty<string>(), Array.Empty<string>());
            TestHarness.Equal(OverallStatus.Unknown, report.Overall, "没有布局必须 Unknown");
            TestHarness.True(!report.ScanAllowed, "Unknown 不允许扫描");
        });
    }
}
