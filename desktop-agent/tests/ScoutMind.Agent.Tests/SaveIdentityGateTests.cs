using ScoutMind.Agent;
using Xunit;

namespace ScoutMind.Agent.Tests;

/// <summary>存档身份安全门：只有 verified + 强证据 + snapshot_eligible + 自动快照开启才放行。</summary>
public sealed class SaveIdentityGateTests
{
    private const string VerifiedJson = """
    {
      "status": "verified",
      "identity": {
        "fingerprint": "si:v1:file:abc123",
        "kind": "save_file",
        "version": 1,
        "confidence": "verified"
      },
      "save_id": null,
      "session": {
        "session_key": "4242:2026-11-24T10:00:00Z:26577676",
        "status": "verified",
        "game_build": "26577676",
        "plugin_version": "27.1.0"
      },
      "evidence": [
        { "type": "SAVE_FILE_METADATA", "source": "file", "hash": "vol:serial:fileid", "confidence": "high" }
      ],
      "missing_evidence": [],
      "conflicts": [],
      "explanation": "唯一存档文件且元数据稳定。",
      "ambiguous": false,
      "snapshot_eligible": true,
      "automatic_snapshot_enabled": true,
      "verify_requested": false,
      "verify_applied": false,
      "diagnostics": []
    }
    """;

    [Fact]
    public void Parse_FullyVerified_Allows()
    {
        var gate = ReaderSaveIdentityGate.Parse(VerifiedJson);

        Assert.True(gate.Allowed);
        Assert.Equal("verified", gate.Status);
        Assert.Equal("si:v1:file:abc123", gate.Fingerprint);
        Assert.Equal("26577676", gate.GameBuild);
        Assert.Equal("si:v1:file:abc123@4242:2026-11-24T10:00:00Z:26577676", gate.ChangeKey);
    }

    [Fact]
    public void Parse_SnapshotIneligible_Blocks()
    {
        var gate = ReaderSaveIdentityGate.Parse(VerifiedJson.Replace("\"snapshot_eligible\": true", "\"snapshot_eligible\": false"));

        Assert.False(gate.Allowed);
        Assert.Contains("snapshot_eligible", string.Join("；", gate.Reasons));
    }

    [Fact]
    public void Parse_AutomaticSnapshotDisabled_Blocks()
    {
        var gate = ReaderSaveIdentityGate.Parse(
            VerifiedJson.Replace("\"automatic_snapshot_enabled\": true", "\"automatic_snapshot_enabled\": false"));

        Assert.False(gate.Allowed);
        Assert.Contains("automatic_snapshot_enabled", string.Join("；", gate.Reasons));
    }

    [Fact]
    public void Parse_Candidate_BlocksWithStatus()
    {
        const string json = """
        {
          "status": "candidate",
          "identity": { "fingerprint": "si:v1:file:abc123", "kind": "save_file", "confidence": "medium" },
          "session": { "session_key": "4242:start:26577676", "game_build": "26577676" },
          "evidence": [{ "type": "SAVE_FILE_METADATA", "source": "file" }],
          "missing_evidence": ["GAME_INTERNAL_SAVE_ID"],
          "conflicts": [],
          "snapshot_eligible": false,
          "automatic_snapshot_enabled": false
        }
        """;

        var gate = ReaderSaveIdentityGate.Parse(json);

        Assert.False(gate.Allowed);
        Assert.Equal("candidate", gate.Status);
        Assert.Contains("GAME_INTERNAL_SAVE_ID", string.Join("；", gate.Reasons));
    }

    [Fact]
    public void Parse_VerifiedWithoutStrongEvidence_Blocks()
    {
        const string json = """
        {
          "status": "verified",
          "identity": { "fingerprint": "si:v1:file:abc123", "kind": "career", "confidence": "verified" },
          "session": { "session_key": "4242:start:26577676", "game_build": "26577676" },
          "evidence": [{ "type": "CAREER_METADATA", "source": "memory" }],
          "missing_evidence": [],
          "conflicts": [],
          "snapshot_eligible": true,
          "automatic_snapshot_enabled": true
        }
        """;

        var gate = ReaderSaveIdentityGate.Parse(json);

        Assert.False(gate.Allowed);
        Assert.Contains("强证据", string.Join("；", gate.Reasons));
    }

    [Fact]
    public void Parse_VerifiedWithoutSessionKey_Blocks()
    {
        const string json = """
        {
          "status": "verified",
          "identity": { "fingerprint": "si:v1:file:abc123", "kind": "save_file", "confidence": "verified" },
          "session": { "session_key": null, "game_build": "26577676" },
          "evidence": [{ "type": "SAVE_FILE_METADATA", "source": "file" }],
          "snapshot_eligible": true,
          "automatic_snapshot_enabled": true
        }
        """;

        var gate = ReaderSaveIdentityGate.Parse(json);

        Assert.False(gate.Allowed);
        Assert.Null(gate.ChangeKey);
    }

    [Fact]
    public void Parse_MalformedJson_Blocks()
    {
        var gate = ReaderSaveIdentityGate.Parse("{ not json");

        Assert.False(gate.Allowed);
        Assert.Equal("BLOCKED", gate.Status);
    }

    [Fact]
    public void Parse_EmptyOutput_Blocks()
    {
        var gate = ReaderSaveIdentityGate.Parse(string.Empty);

        Assert.False(gate.Allowed);
        Assert.NotEmpty(gate.Reasons);
    }
}
