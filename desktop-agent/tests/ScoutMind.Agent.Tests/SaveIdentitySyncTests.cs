using System.Net;
using System.Text;
using ScoutMind.Agent;
using Xunit;

namespace ScoutMind.Agent.Tests;

/// <summary>V3.2.7.2：Agent 必须把身份登记到后端并持有 verified 会话，才允许写数据。</summary>
public sealed class SaveIdentitySyncTests
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
      "session": {
        "session_key": "4242:2026-11-24T10:00:00Z:26577676",
        "status": "verified",
        "game_build": "26577676",
        "plugin_version": "27.1.0"
      },
      "evidence": [
        { "type": "SAVE_FILE_METADATA", "source": "file", "hash": "vol:serial:fileid", "confidence": "high" },
        { "type": "USER_CONFIRMED", "source": "user", "hash": "si:v1:file:abc123", "confidence": "high" }
      ],
      "missing_evidence": [],
      "conflicts": [],
      "explanation": "唯一存档文件且用户已确认。",
      "ambiguous": false,
      "snapshot_eligible": true,
      "automatic_snapshot_enabled": true
    }
    """;

    private static SaveIdentityGate Gate(string json = VerifiedJson) => ReaderSaveIdentityGate.Parse(json);

    private static SaveIdentitySync Sync(StubHandler handler) =>
        new(new BackendClient("http://127.0.0.1:9/api/v1", null, TimeSpan.FromSeconds(5), handler), "agent-test");

    [Fact]
    public void Parse_ExposesSnapshotForUpload()
    {
        var gate = Gate();

        Assert.NotNull(gate.Snapshot);
        Assert.Equal("si:v1:file:abc123", gate.Snapshot!.Fingerprint);
        Assert.Equal(1, gate.Snapshot.FingerprintVersion);
        Assert.Equal("27.1.0", gate.Snapshot.PluginVersion);
        Assert.Equal(2, gate.Snapshot.Evidence.Count);
        Assert.Equal("SAVE_FILE_METADATA", gate.Snapshot.Evidence[0].Type);
        Assert.Equal("vol:serial:fileid", gate.Snapshot.Evidence[0].Hash);
    }

    [Fact]
    public async Task Ensure_ResolvesSaveRegistersStartsAndHeartbeats()
    {
        // V3.2.7.5 D-01：EnsureAsync 第一步是 /saves/resolve，之后全部调用携带 save_id。
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 3, "identity_status": "verified"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "verified"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "verified"}""");
        var sync = Sync(handler);

        var first = await sync.EnsureAsync(Gate(), CancellationToken.None);
        Assert.True(first.Ok);
        Assert.Equal(3, first.IdentityId);
        Assert.Equal(7, first.SessionId);
        Assert.Equal(1, first.SaveId);
        Assert.Equal(new SaveContextQuery(3, 7, SaveId: 1), sync.Context);
        Assert.Contains("save_id=1", handler.Requests[1].Url);
        Assert.Contains("save_id=1", handler.Requests[2].Url);

        var second = await sync.EnsureAsync(Gate(), CancellationToken.None);
        Assert.True(second.Ok);
        Assert.Equal(4, handler.Requests.Count);
        Assert.Contains("/saves/resolve", handler.Requests[0].Url);
        Assert.Contains("/save-identities/register", handler.Requests[1].Url);
        Assert.Contains("/save-sessions/start", handler.Requests[2].Url);
        Assert.Contains("/save-sessions/7/heartbeat", handler.Requests[3].Url);
    }

    [Fact]
    public async Task Ensure_BackendRejectsRegistration_DoesNotWrite()
    {
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.Conflict, """{"error": {"code": "save_context_mismatch", "message": "存档身份不属于当前存档"}}""");
        var sync = Sync(handler);

        var result = await sync.EnsureAsync(Gate(), CancellationToken.None);

        Assert.False(result.Ok);
        Assert.Null(sync.Context);
        Assert.Equal(1, result.SaveId);
        Assert.Contains("409", result.Error);
    }

    [Fact]
    public async Task Ensure_UnverifiedSession_Blocks()
    {
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 3, "identity_status": "candidate"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "created"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "invalidated"}""");
        var sync = Sync(handler);

        var result = await sync.EnsureAsync(Gate(), CancellationToken.None);

        Assert.False(result.Ok);
        Assert.Contains("created", result.Error);
        Assert.Null(sync.Context);
    }

    [Fact]
    public async Task Ensure_HeartbeatFailure_RestartsSession()
    {
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 3}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "verified"}""")
            .Enqueue(HttpStatusCode.Conflict, """{"error": {"code": "save_session_invalidated"}}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 8, "status": "verified"}""");
        var sync = Sync(handler);

        Assert.True((await sync.EnsureAsync(Gate(), CancellationToken.None)).Ok);
        var failed = await sync.EnsureAsync(Gate(), CancellationToken.None);
        Assert.False(failed.Ok);
        Assert.Null(sync.Context);

        var restarted = await sync.EnsureAsync(Gate(), CancellationToken.None);
        Assert.True(restarted.Ok);
        Assert.Equal(8, restarted.SessionId);
        Assert.Equal(5, handler.Requests.Count);
        Assert.Contains("/save-sessions/start", handler.Requests[4].Url);
    }

    [Fact]
    public async Task Ensure_FingerprintChange_InvalidatesOldSession()
    {
        var changed = VerifiedJson.Replace("si:v1:file:abc123", "si:v1:file:def456");
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 3}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "verified"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "invalidated"}""")
            .Enqueue(HttpStatusCode.OK, """{"save_id": 2, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 4}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 9, "status": "verified"}""");
        var sync = Sync(handler);

        Assert.True((await sync.EnsureAsync(Gate(), CancellationToken.None)).Ok);
        var switched = await sync.EnsureAsync(Gate(changed), CancellationToken.None);

        Assert.True(switched.Ok);
        Assert.Equal(4, switched.IdentityId);
        Assert.Equal(9, switched.SessionId);
        Assert.Equal(2, switched.SaveId);
        Assert.Contains("/save-sessions/7/invalidate", handler.Requests[3].Url);
        Assert.Contains("\"save_switched\"", handler.Requests[3].Body);
        Assert.Contains("/saves/resolve", handler.Requests[4].Url);
        Assert.Equal(new SaveContextQuery(4, 9, SaveId: 2), sync.Context);
    }

    [Fact]
    public async Task Invalidate_ClosesSessionAndClearsContext()
    {
        var handler = new StubHandler()
            .Enqueue(HttpStatusCode.OK, """{"save_id": 1, "created": true}""")
            .Enqueue(HttpStatusCode.OK, """{"identity_id": 3}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "verified"}""")
            .Enqueue(HttpStatusCode.OK, """{"session_id": 7, "status": "invalidated"}""");
        var sync = Sync(handler);
        await sync.EnsureAsync(Gate(), CancellationToken.None);

        await sync.InvalidateAsync("agent_stopped", CancellationToken.None);

        Assert.Null(sync.Context);
        Assert.Contains("/save-sessions/7/invalidate", handler.Requests[3].Url);
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly Queue<(HttpStatusCode Status, string Body)> _responses = new();

        public List<(string Method, string Url, string Body)> Requests { get; } = new();

        public StubHandler Enqueue(HttpStatusCode status, string body)
        {
            _responses.Enqueue((status, body));
            return this;
        }

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            Requests.Add((request.Method.Method, request.RequestUri!.ToString(), body));

            if (_responses.Count == 0)
            {
                return new HttpResponseMessage(HttpStatusCode.InternalServerError)
                {
                    Content = new StringContent("{\"error\": {\"code\": \"unexpected_call\"}}", Encoding.UTF8, "application/json"),
                };
            }

            var (status, json) = _responses.Dequeue();
            return new HttpResponseMessage(status)
            {
                Content = new StringContent(json, Encoding.UTF8, "application/json"),
            };
        }
    }
}
