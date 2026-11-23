using System.Globalization;
using System.Text;
using System.Text.Json;
using ScoutMind.FMReader.Integration;

namespace ScoutMind.FMReader.Tests;

/// <summary>SM-113：上游哨兵 UID（4294967295 / -1）不得写成合法身份。</summary>
internal static class MapperSentinelUidTests
{
    private static readonly GameIdentity Game = new("27.1", "26620374", "4530370");

    private static string DumpWithSentinelRows()
    {
        var builder = new StringBuilder();
        builder.Append("{\"meta\":{\"gameDate\":\"2026-11-01\",\"generated\":\"2026-11-23T10:00:00\"},\"players\":[");
        builder.Append("{\"id\":12,\"name\":\"Valid One\",\"ca\":150,\"pa\":170,\"club\":\"Club A\"},");
        builder.Append("{\"id\":4294967295,\"name\":\"Free Agent A\",\"ca\":120,\"pa\":140},");
        builder.Append("{\"id\":4294967295,\"name\":\"Free Agent B\",\"ca\":121,\"pa\":141},");
        builder.Append("{\"id\":-1,\"name\":\"Free Agent C\",\"ca\":122,\"pa\":142},");
        builder.Append("{\"id\":0,\"name\":\"Zero Id\",\"ca\":123,\"pa\":143},");
        builder.Append("{\"name\":\"No Id\",\"ca\":124,\"pa\":144},");
        builder.Append("{\"id\":\"abc\",\"name\":\"Text Id\",\"ca\":125,\"pa\":145},");
        builder.Append("{\"id\":\"98765\",\"name\":\"Numeric Text Id\",\"ca\":126,\"pa\":146}");
        builder.Append("]}");
        return builder.ToString();
    }

    public static void Run(TestHarness harness)
    {
        var mapper = new UpstreamDumpMapper();

        harness.Run("身份判定：4294967295 与 -1 是哨兵，0 与非法文本不是身份", () =>
        {
            TestHarness.Equal(IdentityStatus.SentinelUid, PlayerIdentityClassifier.Classify(4294967295L).Status, "0xFFFFFFFF 是哨兵");
            TestHarness.Equal(IdentityStatus.SentinelUid, PlayerIdentityClassifier.Classify(-1L).Status, "-1 是哨兵");
            TestHarness.Equal(IdentityStatus.InvalidUid, PlayerIdentityClassifier.Classify(0L).Status, "0 不是身份");
            TestHarness.Equal(IdentityStatus.MissingUid, PlayerIdentityClassifier.Classify((long?)null).Status, "缺失是 missing");
            TestHarness.Equal(IdentityStatus.InvalidUid, PlayerIdentityClassifier.ClassifyText("abc").Status, "非数字文本是非法");
            TestHarness.Equal(IdentityStatus.SentinelUid, PlayerIdentityClassifier.ClassifyText("0xFFFFFFFF").Status, "十六进制哨兵");
            TestHarness.Equal(IdentityStatus.ValidUid, PlayerIdentityClassifier.ClassifyText("98765").Status, "数字文本是合法 UID");
            TestHarness.Equal(IdentityStatus.ValidUid, PlayerIdentityClassifier.Classify(12L).Status, "普通 id 是合法 UID");
        });

        var mapped = mapper.Map(DumpWithSentinelRows(), Game, "0.1.0");
        using var payload = JsonDocument.Parse(mapped.Payload);
        var root = payload.RootElement;
        var players = root.GetProperty("players").EnumerateArray().ToList();

        harness.Run("协议：含身份块时 schema_version 为 1.1 且仍是 1.x 兼容", () =>
        {
            TestHarness.Equal("1.1", root.GetProperty("schema_version").GetString(), "协议版本");
        });

        harness.Run("计数：8 名球员中 2 名合法 UID、6 名无身份", () =>
        {
            TestHarness.Equal(8, players.Count, "球员总数");
            TestHarness.Equal(2, mapped.PlayersWithValidUid, "合法 UID 数");
            TestHarness.Equal(6, mapped.PlayersUnresolved, "无身份数");
        });

        harness.Run("合法 UID：写 save_local_uid 与 identity.save_local_uid", () =>
        {
            var valid = players.Where(item => item.TryGetProperty("save_local_uid", out _)).ToList();
            TestHarness.Equal(2, valid.Count, "只有合法 UID 行才有 save_local_uid");
            foreach (var item in valid)
            {
                var uid = item.GetProperty("save_local_uid").GetString();
                TestHarness.True(uid != "4294967295" && uid != "-1" && uid != "0", $"哨兵/零值不得写入 save_local_uid（{uid}）");
                var identity = item.GetProperty("identity");
                TestHarness.Equal("save_local_uid", identity.GetProperty("kind").GetString(), "identity.kind");
                TestHarness.Equal(uid, identity.GetProperty("value").GetString(), "identity.value 必须等于 save_local_uid");
            }
        });

        harness.Run("哨兵 UID：不写 save_local_uid，identity 保留原始值与原因", () =>
        {
            var sentinel = players
                .Where(item => item.GetProperty("identity").GetProperty("kind").GetString() == "unresolved")
                .Where(item => item.GetProperty("identity").GetProperty("uid_status").GetString() == "sentinel")
                .ToList();
            TestHarness.Equal(3, sentinel.Count, "三名哨兵球员（两个 4294967295 + 一个 -1）");
            foreach (var item in sentinel)
            {
                TestHarness.True(!item.TryGetProperty("save_local_uid", out _), "哨兵行不得带 save_local_uid");
                var identity = item.GetProperty("identity");
                TestHarness.Equal("sentinel_uid", identity.GetProperty("reason").GetString(), "原因码");
                TestHarness.True(identity.GetProperty("raw_uid").GetString() is "4294967295" or "-1", "原始值必须保留");
                TestHarness.True(identity.TryGetProperty("evidence", out var evidence)
                    && evidence.GetProperty("source").GetString() == "fmsuperscout_dump",
                    "必须带来源证据");
            }
        });

        harness.Run("哨兵球员不会因相同 UID 合并成一个人", () =>
        {
            var names = players
                .Where(item => item.GetProperty("identity").GetProperty("kind").GetString() == "unresolved")
                .Select(item => item.GetProperty("name").GetString())
                .ToList();
            TestHarness.Equal(names.Count, names.Distinct(StringComparer.Ordinal).Count(), "每个无身份球员都保留独立行");
            TestHarness.Equal(6, names.Count, "六个无身份球员都不得被丢弃");
        });

        harness.Run("缺失/非法 UID：保留球员并给出明确状态", () =>
        {
            var byName = players.ToDictionary(item => item.GetProperty("name").GetString()!, StringComparer.Ordinal);
            var zero = byName["Zero Id"].GetProperty("identity");
            TestHarness.Equal("invalid", zero.GetProperty("uid_status").GetString(), "id=0 是非法");
            TestHarness.Equal("zero_uid", zero.GetProperty("reason").GetString(), "id=0 的原因");

            var missing = byName["No Id"].GetProperty("identity");
            TestHarness.Equal("missing", missing.GetProperty("uid_status").GetString(), "缺失 id");
            TestHarness.True(!missing.TryGetProperty("raw_uid", out _), "缺失时不得编造 raw_uid");

            var text = byName["Text Id"].GetProperty("identity");
            TestHarness.Equal("invalid", text.GetProperty("uid_status").GetString(), "非数字文本");
            TestHarness.Equal("abc", text.GetProperty("raw_uid").GetString(), "非法原文必须保留");

            var numericText = byName["Numeric Text Id"];
            TestHarness.Equal("98765", numericText.GetProperty("save_local_uid").GetString(), "数字文本仍是合法 UID");
        });

        harness.Run("覆盖度与告警：明确说明哨兵人数与处理方式", () =>
        {
            var coverage = root.GetProperty("coverage");
            TestHarness.True(coverage.GetProperty("identity").GetBoolean(), "identity 覆盖");
            var warnings = string.Join("\n", mapped.Warnings);
            TestHarness.Contains(warnings, "0xFFFFFFFF", "应说明哨兵值");
            TestHarness.Contains(warnings, "unresolved", "应说明输出为无身份观察");
        });

        harness.Run("空 id 列表：没有球员时不产生身份块", () =>
        {
            var empty = mapper.Map("{\"meta\":{},\"players\":[]}", Game, "0.1.0");
            using var document = JsonDocument.Parse(empty.Payload);
            TestHarness.Equal(0, document.RootElement.GetProperty("players").GetArrayLength(), "players 为空");
            TestHarness.Equal(0, empty.PlayersUnresolved, "无身份数为 0");
        });

        harness.Run("原始值不可作为 UID 写入：任何输出都不得把 4294967295 当身份", () =>
        {
            var text = mapped.Payload;
            TestHarness.True(!text.Contains("\"save_local_uid\":\"4294967295\"", StringComparison.Ordinal), "不得写 4294967295");
            TestHarness.True(!text.Contains("\"save_local_uid\":\"-1\"", StringComparison.Ordinal), "不得写 -1");
            TestHarness.True(!text.Contains("\"save_local_uid\":\"0\"", StringComparison.Ordinal), "不得写 0");
        });

        harness.Run("文化无关：id 文本不受区域设置影响", () =>
        {
            var original = CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture = new CultureInfo("ar-SA");
                var localized = mapper.Map("{\"meta\":{},\"players\":[{\"id\":123456,\"name\":\"A\"}]}", Game, "0.1.0");
                using var document = JsonDocument.Parse(localized.Payload);
                TestHarness.Equal(
                    "123456",
                    document.RootElement.GetProperty("players")[0].GetProperty("save_local_uid").GetString(),
                    "UID 必须使用不变文化格式");
            }
            finally
            {
                CultureInfo.CurrentCulture = original;
            }
        });
    }
}
