using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>第二轮：未匹配分类、字段规格、字段级探测、样本选择。</summary>
internal static class RoundTwoTests
{
    public static void Run(TestHarness harness)
    {
        MatchTests(harness);
        SpecTests(harness);
        FieldProbeTests(harness);
        SampleTests(harness);
    }

    private static void MatchTests(TestHarness harness)
    {
        harness.Run("匹配诊断：同名同出生年 → Matched", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Josh Mullin", 1992);
            var diagnostic = MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Josh Mullin", 1992), reference);
            TestHarness.Equal(MatchOutcome.Matched, diagnostic.Outcome, "应配对成功");
        });

        harness.Run("匹配诊断：同年不同名 → NameMismatch", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Someone Else", 1992);
            var diagnostic = MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Josh Mullin", 1992), reference);
            TestHarness.Equal(MatchOutcome.NameMismatch, diagnostic.Outcome, "应判姓名不一致");
        });

        harness.Run("匹配诊断：同名不同年 → BirthMismatch", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Josh Mullin", 1990);
            var diagnostic = MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Josh Mullin", 1992), reference);
            TestHarness.Equal(MatchOutcome.BirthMismatch, diagnostic.Outcome, "应判出生日期不一致");
            TestHarness.Contains(diagnostic.Detail, "1990", "证据里要写出参照值");
        });

        harness.Run("匹配诊断：出生年读不到 → MissingBirth（不强行配对）", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Josh Mullin", 1992);
            var diagnostic = MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Josh Mullin", 0), reference);
            TestHarness.Equal(MatchOutcome.MissingBirth, diagnostic.Outcome, "缺少出生日期必须单列");
        });

        harness.Run("匹配诊断：参照里同名多条 → Duplicate", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Pedro", 1987);
            reference.Add("Pedro", 2006);
            var diagnostic = MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Pedro", 1999), reference);
            TestHarness.Equal(MatchOutcome.Duplicate, diagnostic.Outcome, "身份冲突必须单列");
        });

        harness.Run("匹配诊断：女球员在男子导出里 → OnlyOneSide（不是姓名读错）", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Keisuke Honda", 1986);
            var diagnostic = MatchDiagnostics.Classify(
                new MatchDiagnostics.ReaderRow("Jonna Andersson", 1993, Female: true), reference);
            TestHarness.Equal(MatchOutcome.OnlyOneSide, diagnostic.Outcome, "女球员应判一侧不存在");
            TestHarness.Contains(diagnostic.Detail, "女子数据库", "证据要说明原因");
        });

        harness.Run("匹配诊断：两边都无线索 → OnlyOneSide；姓名为空 → Other", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("Keisuke Honda", 1986);
            TestHarness.Equal(MatchOutcome.OnlyOneSide,
                MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow("Nobody Here", 1970), reference).Outcome,
                "无同名同年应判一侧不存在");
            TestHarness.Equal(MatchOutcome.Other,
                MatchDiagnostics.Classify(new MatchDiagnostics.ReaderRow(null, 1990), reference).Outcome,
                "姓名为空属于其他原因");
        });

        harness.Run("匹配诊断：汇总保留全部未匹配记录（不删除、不强行配对）", () =>
        {
            var reference = new MatchDiagnostics.Reference();
            reference.Add("A Player", 1990);
            var rows = new[]
            {
                new MatchDiagnostics.ReaderRow("A Player", 1990),
                new MatchDiagnostics.ReaderRow("B Player", 1991),
                new MatchDiagnostics.ReaderRow("C Player", 0),
            };
            var report = MatchDiagnostics.Summarize(rows, reference);
            TestHarness.Equal(3, report.Sampled, "样本数应完整");
            TestHarness.Equal(1, report.Matched, "只匹配 1 条");
            TestHarness.Equal(2, report.Unmatched.Count, "未匹配记录必须全部保留");
        });
    }

    private static void SpecTests(TestHarness harness)
    {
        harness.Run("字段规格：27.1 上所有字段都是 Pending/NotSupported，没有 Verified", () =>
        {
            var layout = new FM27_1_Layout();
            var specs = FieldSpecs.Build(layout);
            TestHarness.True(specs.All(spec => spec.Status is FieldStatus.Pending or FieldStatus.NotSupported),
                "未核对前不允许出现 Verified/Candidate");
            TestHarness.True(specs.Any(spec => spec.Field == "team.parent_club" && spec.Status == FieldStatus.NotSupported),
                "母队字段必须标为不支持");
            TestHarness.True(specs.Any(spec => spec.Field == "loan.current_club" && spec.Status == FieldStatus.NotSupported),
                "租借字段必须标为不支持");
            TestHarness.True(specs.Any(spec => spec.Field.StartsWith("attr.", StringComparison.Ordinal)), "应包含属性字段");
        });

        harness.Run("字段规格：证据种类四档互相区分", () =>
        {
            var layout = new FM27_0_Layout();
            var specs = FieldSpecs.Build(layout);
            // 27.0 的字段带的是**上游**证据（UpstreamAgreement），ScoutMind 自己没在界面上核对过，
            // 所以状态必须是 Candidate，而不是 Verified。
            TestHarness.True(specs.All(spec => spec.Kind is EvidenceKind.UpstreamAgreement or EvidenceKind.None or EvidenceKind.InternalCheck),
                "27.0 的证据只能是上游/内部，不能是游戏界面");
            TestHarness.True(specs.All(spec => spec.Status is not FieldStatus.Verified),
                "27.0 没有被 ScoutMind 界面核对过，不允许出现 Verified");
            TestHarness.True(Enum.GetValues<EvidenceKind>().Contains(EvidenceKind.GameUiAgreement), "必须存在游戏界面证据档");
        });

        harness.Run("布局状态：Pending 与 Candidate 不混用", () =>
        {
            var pending = new FM27_1_Layout();
            TestHarness.Equal(FieldStatus.Pending, pending.Status, "27.1 应为 Pending");
            var upstream = new FM27_0_Layout();
            TestHarness.Equal(FieldStatus.Candidate, upstream.Status, "27.0 有上游证据但未复现 → Candidate");
            upstream.Mark("PLAO_CA", FieldStatus.Verified, EvidenceKind.GameUiAgreement, "test", "人工核对");
            TestHarness.True(upstream.Status != FieldStatus.Verified, "其余字段仍是 Candidate，整体不能变 Verified");
        });
    }

    private static void FieldProbeTests(TestHarness harness)
    {
        harness.Run("属性探测：合法值通过（round(raw/5) 不要求 5 的倍数）", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Attr {index}")).ToList();
            // 把属性块写成非 5 倍数的原始值（例如 67），上游解码为 13。
            foreach (var player in players)
            {
                foreach (var (_, offset) in FieldSpecs.Technical.Take(3).Select(key => (key, AttributeMap.TryGet(key, out var off) ? off : -1)))
                {
                    if (offset >= 0)
                    {
                        memory.Write(player.Block + layout["PLAO_ATTRS"] + (ulong)offset, new byte[] { 67 });
                    }
                }
            }

            var outcome = new ObjectProbes(memory, layout).ProbeAttributeGroup(players, "attributes.technical", FieldSpecs.Technical);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
        });

        harness.Run("属性探测：越界原始值（>100）判失败", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Bad {index}")).ToList();
            var offset = AttributeMap.TryGet("Passing", out var found) ? found : 0x07;
            foreach (var player in players)
            {
                memory.Write(player.Block + layout["PLAO_ATTRS"] + (ulong)offset, new byte[] { 200 });
            }

            var outcome = new ObjectProbes(memory, layout).ProbeAttributeGroup(players, "attributes.technical", FieldSpecs.Technical);
            TestHarness.Equal(ProbeStatus.Failed, outcome.Status, "越界必须失败");
        });

        harness.Run("位置探测：合法位置字节通过并给出分布", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Pos {index}")).ToList();
            var outcome = new ObjectProbes(memory, layout).ProbePositions(players);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
        });

        harness.Run("国籍探测：指针与名称可读时通过", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 6).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Nat {index}")).ToList();
            var outcome = new ObjectProbes(memory, layout).ProbeNationality(players);
            // FakeSave 把 PERO_NATION 写成 0：没有国家指针时只应"无法判定"，不能伪造成通过或失败。
            TestHarness.True(outcome.Status is ProbeStatus.Passed or ProbeStatus.Inconclusive,
                "无国家指针时不应误判为 Failed，实际：" + outcome.Status);
        });

        harness.Run("性别分批：按 PERO_GENDER 的 0x10 位分开", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var men = Enumerable.Range(0, 3).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"M{index}")).ToList();
            var women = Enumerable.Range(10, 3).Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"W{index}")).ToList();
            foreach (var player in women)
            {
                memory.Write(player.Person + layout["PERO_GENDER"], new byte[] { 0x10 });
            }

            var (menSplit, womenSplit) = new ObjectProbes(memory, layout).SplitByGender(men.Concat(women).ToList());
            TestHarness.Equal(3, menSplit.Count, "男子样本数");
            TestHarness.Equal(3, womenSplit.Count, "女子样本数");
        });

        harness.Run("球队关系：注册俱乐部与当前球队分开统计", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var club = FakeSave.WriteClub(memory, layout, 0, "Relation FC");
            var players = Enumerable.Range(0, 6)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Rel {index}", clubAddress: club.Address))
                .ToList();
            var outcome = new ObjectProbes(memory, layout).ProbeTeamRelations(players);
            TestHarness.Equal(ProbeStatus.Passed, outcome.Status,
                "失败项：" + string.Join("; ", outcome.Checks.Where(item => item.Status == CheckStatus.Failed).Select(item => item.Detail)));
            TestHarness.True(outcome.Checks.Any(item => item.Name == "team.tiers"), "应报告层级分布");
        });
    }

    private static void SampleTests(TestHarness harness)
    {
        harness.Run("验证样本：30 人且覆盖年龄/位置/层级", () =>
        {
            var candidates = new List<VerificationPlayer>();
            var index = 0;
            foreach (var ageGroup in new[] { "U21", "22-27", "28-33", "34+" })
            {
                foreach (var position in new[] { "GK", "DC", "MC", "ST" })
                {
                    for (var repeat = 0; repeat < 3; repeat++)
                    {
                        index++;
                        candidates.Add(new VerificationPlayer(
                            PlayerId: (uint)index,
                            Name: $"Player {index}",
                            BirthYear: 2000,
                            Nationality: "英格兰",
                            Positions: position,
                            Ca: 100,
                            Pa: 120,
                            Height: 180,
                            Attributes: new Dictionary<string, int>(),
                            ClubName: $"Club {index % 7}",
                            TeamType: repeat == 0 ? 0 : repeat == 1 ? 3 : 12,
                            ContractYear: 2027,
                            AgeGroup: ageGroup));
                    }
                }
            }

            var sample = VerificationSample.Select(candidates, 30);
            TestHarness.Equal(30, sample.Count, "应选满 30 人");
            TestHarness.Equal(30, sample.Select(item => item.PlayerId).Distinct().Count(), "不得重复");
            TestHarness.True(sample.Select(item => item.AgeGroup).Distinct().Count() >= 3, "应覆盖多个年龄组");
            TestHarness.True(sample.Select(item => item.Positions).Distinct().Count() >= 3, "应覆盖多个位置");
            TestHarness.True(sample.Select(item => item.TeamType).Distinct().Count() >= 2, "应覆盖多个球队层级");
        });

        harness.Run("验证样本：Markdown 明确写 CA/PA 不是游戏界面可核对项", () =>
        {
            var players = new[]
            {
                new VerificationPlayer(1, "Test Player", 1990, "英格兰", "ST", 100, 120, 180,
                    new Dictionary<string, int> { ["Passing"] = 12 }, "Test FC", 0, 2027, "28-33"),
            };
            var markdown = VerificationSample.ToMarkdown(players, "26620374", "27.1");
            TestHarness.Contains(markdown, "CA/PA 在游戏界面不可见", "必须声明 CA/PA 的验证限制");
            TestHarness.Contains(markdown, "Test Player", "应包含样本行");
        });
    }
}
