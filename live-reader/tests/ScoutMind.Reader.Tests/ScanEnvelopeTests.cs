using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Reader.Tests;

/// <summary>扫描信封序列化用例：本地 camelCase、线上 snake_case、时间戳为 Z 形式。</summary>
public static class ScanEnvelopeTests
{
    private static readonly string[] CamelCaseFields =
    {
        "schemaVersion", "source", "readerVersion", "game", "scan", "coverage", "warnings", "clubs", "players", "transfers",
    };

    /// <summary>注册并执行序列化用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Case("ScanEnvelope 以 camelCase 序列化并包含全部必需字段", () =>
        {
            var envelope = CreateEnvelope();
            var json = JsonSerializer.Serialize(envelope, ScoutMindJson.Options);
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;

            Assert.Equal(JsonValueKind.Object, root.ValueKind, "信封应是 JSON 对象");
            foreach (var field in CamelCaseFields)
            {
                Assert.True(root.TryGetProperty(field, out _), $"缺少字段 {field}");
            }

            Assert.False(root.TryGetProperty("schema_version", out _), "本地信封不应使用 snake_case");
            var scan = root.GetProperty("scan");
            Assert.True(scan.TryGetProperty("scanId", out var scanId), "scan 应包含 scanId");
            Assert.Equal("8b1d2c2a-0e6e-4b0b-9a5a-0b1f5d7a3c11", scanId.GetString(), "scanId 值应原样保留");
            Assert.Equal(1, root.GetProperty("players").GetArrayLength(), "players 应保留原始记录");
            Assert.Equal(0, root.GetProperty("transfers").GetArrayLength(), "transfers 应保留原始记录");
            Assert.True(root.GetProperty("coverage").GetProperty("players").GetBoolean(), "coverage 应保留布尔值");
        });

        harness.Case("ScanEnvelope 可往返反序列化", () =>
        {
            var envelope = CreateEnvelope();
            var json = JsonSerializer.Serialize(envelope, ScoutMindJson.Options);
            var round = JsonSerializer.Deserialize<ScanEnvelope>(json, ScoutMindJson.Options);

            Assert.True(round is not null, "应能反序列化回信封");
            Assert.Equal("1.0", round!.SchemaVersion, "schemaVersion 应一致");
            Assert.Equal("4530370", round.Game.AppId, "appId 应一致");
            Assert.Equal(1, round.Players.Count, "players 数量应一致");
            Assert.Equal(1, round.Warnings.Count, "warnings 数量应一致");
        });

        harness.Case("协议序列化输出 snake_case 且结构符合 DATA_PROTOCOL", () =>
        {
            var bytes = ScanProtocolSerializer.ToProtocolJson(CreateEnvelope());
            using var document = JsonDocument.Parse(bytes);
            var root = document.RootElement;

            Assert.Equal("1.0", root.GetProperty("schema_version").GetString(), "schema_version 应为 1.0");
            Assert.Equal("fm27_live_reader", root.GetProperty("source").GetString(), "source 应为 fm27_live_reader");
            Assert.Equal("0.1.0", root.GetProperty("reader_version").GetString(), "reader_version 应存在");
            Assert.Equal("4530370", root.GetProperty("game").GetProperty("app_id").GetString(), "game.app_id 应存在");
            Assert.Equal(
                "8b1d2c2a-0e6e-4b0b-9a5a-0b1f5d7a3c11",
                root.GetProperty("scan").GetProperty("scan_id").GetString(),
                "scan.scan_id 应存在");
            Assert.Equal("2026-11-18T03:00:00Z", root.GetProperty("scan").GetProperty("observed_at").GetString(), "observed_at 应存在");
            Assert.Equal(1, root.GetProperty("players").GetArrayLength(), "players 数组应保留");
        });

        harness.Case("协议形态检测能区分 snake_case 与 camelCase", () =>
        {
            using var protocol = JsonDocument.Parse("{\"schema_version\":\"1.0\",\"scan\":{}}");
            Assert.True(ScanProtocolSerializer.LooksLikeProtocolPayload(protocol.RootElement), "snake_case 应判定为协议形态");

            using var camel = JsonDocument.Parse("{\"schemaVersion\":\"1.0\",\"scan\":{}}");
            Assert.False(ScanProtocolSerializer.LooksLikeProtocolPayload(camel.RootElement), "camelCase 不应判定为协议形态");
        });

        harness.Case("ReaderStatus 的时间戳序列化为 Z 形式", () =>
        {
            var status = new ReaderStatus(
                ReaderState.NotFound,
                "未找到",
                new DateTimeOffset(2026, 11, 18, 3, 0, 0, TimeSpan.Zero),
                null,
                null,
                null,
                null,
                new List<string>(),
                "0.1.0");

            var json = JsonSerializer.Serialize(status, ScoutMindJson.Options);
            Assert.Contains(json, "\"detectedAt\": \"2026-11-18T03:00:00Z\"", "时间戳应为 UTC Z 形式");
            Assert.Contains(json, "\"state\": \"NotFound\"", "状态应为枚举名原样");
        });
    }

    private static ScanEnvelope CreateEnvelope()
    {
        using var playerDocument = JsonDocument.Parse("{\"record_id\":\"p-1\",\"name\":\"Test Player\"}");
        return new ScanEnvelope(
            SchemaVersion: "1.0",
            Source: "fm27_live_reader",
            ReaderVersion: "0.1.0",
            Game: new ScanGame("27.1.0", "26620374", "4530370"),
            Scan: new ScanMetadata(
                "8b1d2c2a-0e6e-4b0b-9a5a-0b1f5d7a3c11",
                "2026-11-18T03:00:00Z",
                "2027-03-01",
                "1001"),
            Coverage: new Dictionary<string, bool> { ["players"] = true, ["transfers"] = false },
            Warnings: new List<string> { "扫描器未提供伤病字段" },
            Clubs: new List<JsonElement>(),
            Players: new List<JsonElement> { playerDocument.RootElement.Clone() },
            Transfers: new List<JsonElement>());
    }
}
