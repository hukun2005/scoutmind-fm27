using System.Text.Json;
using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>无 UID 对象的枚举与合并：只输出观察，不把对象地址写进报文。</summary>
public static class UnresolvedObjectCollectorTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        // FakeLocator 无构造函数参数：显式填充 Players。
        static FakeLocator Locator(IEnumerable<LocatedObject> players)
        {
            var locator = new FakeLocator();
            locator.Players.AddRange(players);
            return locator;
        }

        harness.Run("对象枚举：哨兵与零 UID 被输出，合法 UID 交给 dump", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = Enumerable.Range(0, 3)
                .Select(index => FakeSave.WritePlayer(memory, layout, index, name: $"Object {index}"))
                .ToList();
            memory.WriteUInt32(players[0].Db + layout["OBJ_DUNI"], 0xFFFFFFFF);
            memory.WriteUInt32(players[1].Db + layout["OBJ_DUNI"], 0);

            var rows = UnresolvedObjectCollector.Collect(
                Locator(players), memory, layout, 10, TimeSpan.FromSeconds(5), out var readable, out var note);

            TestHarness.Equal(3, readable, "三个对象都应能读到 UID");
            TestHarness.Equal(2, rows.Count, "只有哨兵与零 UID 需要输出");
            TestHarness.Equal("sentinel", rows[0].UidStatus, "第一个是哨兵");
            TestHarness.Equal("4294967295", rows[0].RawUid, "原始哨兵值必须保留");
            TestHarness.Equal("invalid", rows[1].UidStatus, "零 UID 归为非法");
            TestHarness.Equal("zero_uid", rows[1].Reason, "原因码可解释");
            TestHarness.True(note is null, "全部命名时可读，无额外告警");
            TestHarness.True(rows[0].SourceRecordId.StartsWith("reader_object:player:", StringComparison.Ordinal),
                "来源标识不能包含地址");
            TestHarness.True(!rows[0].SourceRecordId.Contains("0x", StringComparison.OrdinalIgnoreCase),
                "来源标识不能包含地址");
        });

        harness.Run("对象枚举：没有姓名的无 UID 对象不生成行，只计数告警", () =>
        {
            var layout = new FM27_1_Layout();
            var memory = new FakeMemory();
            var players = new List<LocatedObject> { FakeSave.WritePlayer(memory, layout, 0, name: "") };
            memory.WriteUInt32(players[0].Db + layout["OBJ_DUNI"], 0xFFFFFFFF);

            var rows = UnresolvedObjectCollector.Collect(
                Locator(players), memory, layout, 10, TimeSpan.FromSeconds(5), out var readable, out var note);

            TestHarness.Equal(1, readable, "UID 仍可读");
            TestHarness.Equal(0, rows.Count, "没有姓名就不编造观察");
            TestHarness.True(note is not null && note.Contains("没有可读姓名"), note!);
        });

        harness.Run("合并：unresolved 行进报文且不带对象地址", () =>
        {
            const string payload = """
                {"schema_version":"1.1","source":"fm27_live_reader","scan":{"scanId":"s1"},
                 "players":[],"clubs":[],"transfers":[],"warnings":[],"coverage":{}}
                """;
            var rows = new[]
            {
                new UnresolvedObjectRow("Free Agent", 120, 140, "2003-07-01", "sentinel", "4294967295",
                    "sentinel_uid", "reader_object:player:7"),
            };

            var merged = UnresolvedObjectCollector.Merge(payload, rows, "0.1.0");
            using var document = JsonDocument.Parse(merged);
            var players = document.RootElement.GetProperty("players");
            TestHarness.Equal(1, players.GetArrayLength(), "应追加一行");
            var identity = players[0].GetProperty("identity");
            TestHarness.Equal("unresolved", identity.GetProperty("kind").GetString(), "身份类型");
            TestHarness.Equal("sentinel", identity.GetProperty("uid_status").GetString(), "UID 状态");
            TestHarness.Equal("4294967295", identity.GetProperty("raw_uid").GetString(), "原始值保留");
            TestHarness.True(!merged.Contains("0x", StringComparison.OrdinalIgnoreCase), "报文不得包含内存地址");
            TestHarness.Equal("reader_object_enumeration",
                identity.GetProperty("evidence").GetProperty("source").GetString(), "证据来源");
        });

        harness.Run("合并：没有新行时原样返回", () =>
        {
            const string payload = """{"schema_version":"1.1","players":[]}""";
            var merged = UnresolvedObjectCollector.Merge(payload, Array.Empty<UnresolvedObjectRow>(), "0.1.0");
            TestHarness.Equal(payload, merged, "不应改写报文");
        });
    }
}


