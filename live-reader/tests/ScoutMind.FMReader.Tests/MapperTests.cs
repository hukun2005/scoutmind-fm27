using System.Text.Json;
using ScoutMind.FMReader.Integration;

namespace ScoutMind.FMReader.Tests;

/// <summary>上游 dump → ScoutMind 协议映射。用真实导出样本（300 名球员）做回归。</summary>
internal static class MapperTests
{
    private static string FixturePath => Path.Combine(AppContext.BaseDirectory, "fixtures", "real_sample_01.json");

    private static readonly GameIdentity Game = new("27.1", "26620374", "4530370");

    public static void Run(TestHarness harness)
    {
        var mapper = new UpstreamDumpMapper();
        var dump = File.ReadAllText(FixturePath);
        var mapped = mapper.Map(dump, Game, "0.1.0");

        using var payload = JsonDocument.Parse(mapped.Payload);
        var root = payload.RootElement;
        var players = root.GetProperty("players").EnumerateArray().ToList();
        var clubs = root.GetProperty("clubs").EnumerateArray().ToList();

        harness.Run("协议：包含 schema_version / source / players / clubs / transfers", () =>
        {
            TestHarness.Equal("1.1", root.GetProperty("schema_version").GetString(), "协议版本");
            TestHarness.Equal("fm27_live_reader", root.GetProperty("source").GetString(), "来源标记");
            TestHarness.True(players.Count > 0, "应映射出球员");
            TestHarness.True(root.GetProperty("transfers").ValueKind == JsonValueKind.Array, "transfers 必须是数组");
            TestHarness.Equal(0, root.GetProperty("transfers").GetArrayLength(), "上游没有转会，必须是空数组");
        });

        harness.Run("协议：game.build 与插件版本来自读取器检测，不编造", () =>
        {
            var game = root.GetProperty("game");
            TestHarness.Equal("26620374", game.GetProperty("build").GetString(), "构建号应原样写入");
            TestHarness.Equal("4530370", game.GetProperty("app_id").GetString(), "AppId 应原样写入");
        });

        harness.Run("球员：稳定 ID、姓名、CA/PA 与上游一致", () =>
        {
            using var source = JsonDocument.Parse(dump);
            var first = source.RootElement.GetProperty("players")[0];
            var mappedFirst = players[0];
            TestHarness.Equal(
                first.GetProperty("id").GetInt64().ToString(System.Globalization.CultureInfo.InvariantCulture),
                mappedFirst.GetProperty("save_local_uid").GetString(),
                "save_local_uid 必须是上游球员 id");
            TestHarness.Equal(first.GetProperty("name").GetString(), mappedFirst.GetProperty("name").GetString(), "姓名");
            if (first.TryGetProperty("ca", out var ca) && ca.GetInt32() > 0)
            {
                TestHarness.Equal(ca.GetInt32(), mappedFirst.GetProperty("ca").GetInt32(), "CA 必须与上游一致");
            }
        });

        harness.Run("身份：真实样本每行都带 identity 块，且只有合法 UID 写 save_local_uid", () =>
        {
            foreach (var item in players)
            {
                var identity = item.GetProperty("identity");
                var kind = identity.GetProperty("kind").GetString();
                if (kind == "save_local_uid")
                {
                    TestHarness.Equal(kind, "save_local_uid", "合法身份类型");
                    TestHarness.True(item.TryGetProperty("save_local_uid", out var uid)
                        && uid.GetString() == identity.GetProperty("value").GetString(), "identity.value 必须与 save_local_uid 一致");
                }
                else
                {
                    TestHarness.Equal("unresolved", kind, "无身份行必须是 unresolved");
                    TestHarness.True(!item.TryGetProperty("save_local_uid", out _), "无身份行不得带 save_local_uid");
                }
            }

            TestHarness.Equal(players.Count, players.Count(item => item.TryGetProperty("save_local_uid", out _)),
                "真实样本 300 名球员都有合法 id");
        });

        harness.Run("球员：出生日期由 birthYear + birthDoy 还原", () =>
        {
            var withBirth = players.FirstOrDefault(item =>
                item.TryGetProperty("birth_date", out var value) && value.ValueKind == JsonValueKind.String);
            TestHarness.True(withBirth.ValueKind == JsonValueKind.Object, "应至少有一名球员有出生日期");
            var text = withBirth.GetProperty("birth_date").GetString()!;
            TestHarness.True(DateOnly.TryParse(text, out _), $"出生日期必须是 yyyy-MM-dd，实际 {text}");
        });

        harness.Run("球员：没有俱乐部的球员不带 club_uid（不得默认归入本队）", () =>
        {
            var withoutClub = players.Where(item => !item.TryGetProperty("club_uid", out _)).ToList();
            TestHarness.True(withoutClub.Count > 0, "样本中应存在没有俱乐部的球员");
            foreach (var item in withoutClub.Take(50))
            {
                TestHarness.True(!item.TryGetProperty("club_uid", out _), "没有俱乐部名称时不应写 club_uid");
            }
        });

        harness.Run("俱乐部：从球员行派生，uid 与后端归一化算法一致", () =>
        {
            TestHarness.True(clubs.Count > 0, "应派生俱乐部");
            foreach (var club in clubs)
            {
                var uid = club.GetProperty("uid").GetString()!;
                var name = club.GetProperty("name").GetString()!;
                TestHarness.True(uid.StartsWith("name:", StringComparison.Ordinal), $"俱乐部 uid 必须稳定（实际 {uid}）");
                TestHarness.Equal(UpstreamDumpMapper.ClubUid(name), uid, "uid 必须由名称规范化得到");
            }
        });

        harness.Run("俱乐部：同一名称只出现一次", () =>
        {
            var uids = clubs.Select(item => item.GetProperty("uid").GetString()).ToList();
            TestHarness.Equal(uids.Count, uids.Distinct(StringComparer.Ordinal).Count(), "俱乐部 uid 必须唯一");
        });

        harness.Run("覆盖度：转会/租借/所有权/梯队为 false，球员与俱乐部为 true", () =>
        {
            var coverage = root.GetProperty("coverage");
            TestHarness.True(coverage.GetProperty("players").GetBoolean(), "players 应覆盖");
            TestHarness.True(coverage.GetProperty("clubs").GetBoolean(), "clubs 应覆盖");
            TestHarness.True(!coverage.GetProperty("transfers").GetBoolean(), "transfers 必须为 false");
            TestHarness.True(!coverage.GetProperty("loans").GetBoolean(), "loans 必须为 false");
            TestHarness.True(!coverage.GetProperty("ownership").GetBoolean(), "ownership 必须为 false");
            TestHarness.True(!coverage.GetProperty("team_tiers").GetBoolean(), "team_tiers 必须为 false");
        });

        harness.Run("告警：明确写出转会/租借/梯队缺失与未验证的 teamType", () =>
        {
            var warnings = string.Join("\n", mapped.Warnings);
            TestHarness.Contains(warnings, "转会历史", "应说明没有转会历史");
            TestHarness.Contains(warnings, "parentClub", "应说明没有租借/所有权字段");
            TestHarness.Contains(warnings, "梯队", "应说明没有梯队");
            TestHarness.Contains(warnings, "teamType", "应说明 teamType 未验证且未映射");
        });

        harness.Run("梯队：不写任何梯队字段（teamType 语义未验证）", () =>
        {
            foreach (var item in players.Take(200))
            {
                TestHarness.True(!item.TryGetProperty("team_type", out _), "不得把未验证的 teamType 写成梯队");
                TestHarness.True(!item.TryGetProperty("squad_type", out _), "不得伪造阵容类别");
            }
        });

        harness.Run("租借：不写 ownership/agreed_transfer（上游没有这些字段）", () =>
        {
            foreach (var item in players.Take(200))
            {
                TestHarness.True(!item.TryGetProperty("ownership", out _), "不得伪造所有权");
                TestHarness.True(!item.TryGetProperty("agreed_transfer", out _), "不得伪造待生效转会");
            }
        });

        harness.Run("合同：到期日可解析，未提供时为 null 而不是空字符串", () =>
        {
            var withContract = players
                .Where(item => item.TryGetProperty("contract_end", out var value) && value.ValueKind == JsonValueKind.String)
                .Take(20)
                .ToList();
            TestHarness.True(withContract.Count > 0, "样本中应有带合同到期日的球员");
            foreach (var item in withContract)
            {
                TestHarness.True(DateOnly.TryParse(item.GetProperty("contract_end").GetString(), out _),
                    "contract_end 必须是 yyyy-MM-dd");
            }

            foreach (var item in players)
            {
                if (item.TryGetProperty("contract_end", out var value))
                {
                    TestHarness.True(value.ValueKind != JsonValueKind.String || !string.IsNullOrWhiteSpace(value.GetString()),
                        "contract_end 不得是空字符串");
                }
            }
        });

        harness.Run("属性：映射为协议键，未知属性只进告警", () =>
        {
            var withAttributes = players.First(item => item.TryGetProperty("attributes", out var attributes)
                && attributes.EnumerateObject().Any());
            var attributesNode = withAttributes.GetProperty("attributes");
            TestHarness.True(attributesNode.TryGetProperty("finishing", out _)
                || attributesNode.TryGetProperty("passing", out _)
                || attributesNode.TryGetProperty("tackling", out _),
                "应存在协议键（snake_case）属性");
            foreach (var property in attributesNode.EnumerateObject())
            {
                TestHarness.True(property.Name == property.Name.ToLowerInvariant(), $"属性键必须小写（{property.Name}）");
            }
        });

        harness.Run("惯用脚：多语言标签映射到协议枚举", () =>
        {
            TestHarness.Equal<string?>("right", UpstreamDumpMapper.MapFoot("Rechts"), "Rechts → right");
            TestHarness.Equal<string?>("left", UpstreamDumpMapper.MapFoot("Links"), "Links → left");
            TestHarness.Equal<string?>("both", UpstreamDumpMapper.MapFoot("Beide"), "Beide → both");
            TestHarness.Equal<string?>("right", UpstreamDumpMapper.MapFoot("right"), "right → right");
            TestHarness.Equal<string?>(null, UpstreamDumpMapper.MapFoot("Onbekend"), "未知标签必须是 null");
        });

        harness.Run("本队：样本没有 meta.myClub，user_club_uid 为 null 且给出告警", () =>
        {
            var scan = root.GetProperty("scan");
            TestHarness.Equal(JsonValueKind.Null, scan.GetProperty("user_club_uid").ValueKind, "不能编造本队");
            TestHarness.True(mapped.Warnings.Any(text => text.Contains("主执教俱乐部", StringComparison.Ordinal)),
                "应提示需要手动指定本队");
        });

        harness.Run("规范化：俱乐部名称去重音、大小写与标点", () =>
        {
            TestHarness.Equal("fc naples", UpstreamDumpMapper.NormalizeClubName("FC  Naples"), "大小写与空格");
            TestHarness.Equal("atletico madrid", UpstreamDumpMapper.NormalizeClubName("Atlético Madrid"), "去重音");
            TestHarness.Equal<string?>(UpstreamDumpMapper.ClubUid("A.B.C."), UpstreamDumpMapper.ClubUid("A B C"), "标点差异应一致");
        });

        harness.Run("空输入：没有球员时 players 为空数组且给出告警", () =>
        {
            var empty = mapper.Map("{\"meta\":{},\"players\":[]}", Game, "0.1.0");
            using var doc = JsonDocument.Parse(empty.Payload);
            TestHarness.Equal(0, doc.RootElement.GetProperty("players").GetArrayLength(), "players 应为空");
            TestHarness.True(empty.Warnings.Any(text => text.Contains("没有读到任何球员", StringComparison.Ordinal)),
                "应提示没有读到球员");
        });

        harness.Run("非法 JSON：抛出 JsonException 而不是返回半份数据", () =>
        {
            TestHarness.Throws<JsonException>(() => mapper.Map("{not json", Game, "0.1.0"), "非法输入必须抛异常");
        });
    }
}
