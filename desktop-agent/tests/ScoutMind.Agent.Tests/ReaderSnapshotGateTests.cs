using ScoutMind.Agent;
using Xunit;

namespace ScoutMind.Agent.Tests;

/// <summary>读取器安全门解析：只有明确的 ENABLED 才放行，其余一律 BLOCKED。</summary>
public sealed class ReaderSnapshotGateTests
{
    [Fact]
    public void Parse_EnabledWithDate_Allows()
    {
        const string json = """
        {
          "status": "restart_verified",
          "date_summary": { "selected_date": "2026-11-06" },
          "snapshot": { "status": "ENABLED", "allowed": true, "reasons": [] }
        }
        """;

        var gate = ReaderSnapshotGate.Parse(json);

        Assert.True(gate.Allowed);
        Assert.Equal("ENABLED", gate.Status);
        Assert.Equal("2026-11-06", gate.Date);
    }

    [Fact]
    public void Parse_Blocked_KeepsReasons()
    {
        const string json = """
        {
          "date_summary": { "selected_date": "2026-11-06" },
          "snapshot": {
            "status": "BLOCKED",
            "allowed": false,
            "reasons": ["日期可信度只有 heuristic，未达到 restart_verified。"]
          }
        }
        """;

        var gate = ReaderSnapshotGate.Parse(json);

        Assert.False(gate.Allowed);
        Assert.Single(gate.Reasons);
        Assert.Contains("restart_verified", gate.Reasons[0]);
    }

    [Fact]
    public void Parse_MissingSnapshot_Blocks()
    {
        var gate = ReaderSnapshotGate.Parse("""{ "date_summary": { "selected_date": "2026-11-06" } }""");

        Assert.False(gate.Allowed);
        Assert.Equal("BLOCKED", gate.Status);
    }

    [Fact]
    public void Parse_AllowedWithoutDate_Blocks()
    {
        const string json = """
        {
          "date_summary": { "selected_date": null },
          "snapshot": { "status": "ENABLED", "allowed": true, "reasons": [] }
        }
        """;

        var gate = ReaderSnapshotGate.Parse(json);

        Assert.False(gate.Allowed);
        Assert.Contains("没有给出日期", string.Join("；", gate.Reasons));
    }

    [Fact]
    public void Parse_MalformedJson_Blocks()
    {
        var gate = ReaderSnapshotGate.Parse("{ not json");

        Assert.False(gate.Allowed);
        Assert.Equal("BLOCKED", gate.Status);
    }
}
