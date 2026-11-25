using System.Net;
using System.Text;
using ScoutMind.Agent;
using Xunit;

namespace ScoutMind.Agent.Tests;

/// <summary>V3.2.7.4：任务上下文固定、重启隔离、诊断命令与任务查询。</summary>
public sealed class V3274AgentTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "scoutmind-v3274-tests-" + Guid.NewGuid().ToString("N"));

    public V3274AgentTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, true);
        }
        catch (IOException)
        {
        }
    }

    [Fact]
    public void DiagnosticsAndJobsCommandsParse()
    {
        var diagnostics = AgentCommandLine.Parse(new[] { "diagnostics", "--json" });
        Assert.True(diagnostics.Ok);
        Assert.Equal(AgentCommand.Diagnostics, diagnostics.Options!.Command);
        Assert.True(diagnostics.Options.Json);

        var list = AgentCommandLine.Parse(new[] { "jobs", "list", "--json" });
        Assert.True(list.Ok);
        Assert.Equal(AgentCommand.Jobs, list.Options!.Command);
        Assert.Equal("list", list.Options.AutoControl);

        var inspect = AgentCommandLine.Parse(new[] { "jobs", "inspect", "scan-9" });
        Assert.True(inspect.Ok);
        Assert.Equal("inspect", inspect.Options!.AutoControl);
        Assert.Equal("scan-9", inspect.Options.ScanId);

        var network = AgentCommandLine.Parse(new[] { "network", "status" });
        Assert.True(network.Ok);
        Assert.Equal(AgentCommand.Network, network.Options!.Command);

        Assert.False(AgentCommandLine.Parse(new[] { "jobs" }).Ok);
        Assert.False(AgentCommandLine.Parse(new[] { "jobs", "inspect" }).Ok);
        Assert.False(AgentCommandLine.Parse(new[] { "network" }).Ok);
    }

    [Fact]
    public void ScanTaskContextRoundTripsAndDetectsFingerprint()
    {
        var path = Path.Combine(_root, "a.context.json");
        var context = new ScanTaskContext(3, 11, 21, "fp-save-a", "op-fixed", "sha256-abc", "2026-11-25T00:00:00Z");
        context.Save(path);

        var loaded = ScanTaskContext.TryLoad(path);
        Assert.NotNull(loaded);
        Assert.Equal(context, loaded);
        Assert.True(loaded!.BelongsTo("fp-save-a"));
        Assert.False(loaded.BelongsTo("fp-save-b"));
        Assert.False(loaded.BelongsTo(null));

        // 重启后重新验证到新会话，但 operation_id 与指纹判定保持不变。
        var resumed = loaded.WithSession(99);
        Assert.Equal(99, resumed.SessionId);
        Assert.Equal("op-fixed", resumed.OperationId);
        Assert.Equal("fp-save-a", resumed.Fingerprint);
    }

    [Fact]
    public void ScanTaskContextMissingOrCorruptReturnsNull()
    {
        Assert.Null(ScanTaskContext.TryLoad(Path.Combine(_root, "missing.context.json")));

        var corrupt = Path.Combine(_root, "corrupt.context.json");
        File.WriteAllText(corrupt, "{not-json");
        Assert.Null(ScanTaskContext.TryLoad(corrupt));

        var incomplete = Path.Combine(_root, "incomplete.context.json");
        File.WriteAllText(incomplete, "{\"SaveId\":1,\"Fingerprint\":\"fp\"}");
        Assert.Null(ScanTaskContext.TryLoad(incomplete));
    }

    [Fact]
    public void QueueMovesContextSidecarWithTask()
    {
        var queue = new ScanQueue(Path.Combine(_root, "queue"));
        queue.EnsureCreated();

        var envelope = Path.Combine(queue.ScanDirectory, "scan-a.json");
        File.WriteAllText(envelope, "{}");
        var contextPath = ScanQueue.ContextPathFor(envelope);
        new ScanTaskContext(3, 11, 21, "fp-save-a", "op-fixed", "sha256-abc", "2026-11-25T00:00:00Z").Save(contextPath);

        // .context.json 不是信封，不能出现在待同步列表里。
        var outstanding = queue.ListOutstanding();
        Assert.Single(outstanding);
        Assert.Equal(envelope, outstanding[0]);

        var claimed = queue.Claim(envelope);
        Assert.NotNull(claimed);
        Assert.True(File.Exists(ScanQueue.ContextPathFor(claimed!)), "claim 必须把上下文一起移入 processing");

        var pending = queue.EnqueuePending(claimed!);
        Assert.NotNull(pending);
        Assert.True(File.Exists(ScanQueue.ContextPathFor(pending!)), "重试必须保留固定上下文");

        var folder = queue.QuarantineAll(pending!, new { code = "context_mismatch" });
        Assert.NotNull(folder);
        Assert.True(File.Exists(Path.Combine(folder!, "scan-a.context.json")), "隔离必须保留上下文证据");
    }

    [Fact]
    public async Task RecentJobsParseAttemptsAndRejection()
    {
        var handler = new StubHandler(
            "{\"items\":[" +
            "{\"id\":1,\"scan_id\":\"scan-1\",\"status\":\"queued\",\"attempt_count\":2}," +
            "{\"id\":2,\"scan_id\":\"scan-2\",\"status\":\"rejected\",\"attempt_count\":1,\"rejected_reason\":\"write_session_epoch_stale\"}" +
            "],\"total\":2}");

        using var client = new BackendClient("http://127.0.0.1:8000/api/v1", null, TimeSpan.FromSeconds(5), handler);
        var jobs = await client.GetRecentJobsAsync(10, CancellationToken.None);

        Assert.Equal(2, jobs.Count);
        Assert.Equal(2, jobs[0].AttemptCount);
        Assert.Null(jobs[0].RejectedReason);
        Assert.Equal("rejected", jobs[1].Status);
        Assert.True(jobs[1].IsTerminal);
        Assert.False(jobs[1].IsComplete);
        Assert.Equal("write_session_epoch_stale", jobs[1].RejectedReason);
        Assert.Contains("limit=10", handler.LastRequestUri, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ProbeReportsStatusCodeWithoutBody()
    {
        var handler = new StubHandler("{\"items\":[],\"total\":0}");
        using var client = new BackendClient("http://127.0.0.1:8000/api/v1", "token", TimeSpan.FromSeconds(5), handler);

        var status = await client.ProbeAsync(CancellationToken.None);

        Assert.Equal(200, status);
        Assert.Contains("/imports?limit=1", handler.LastRequestUri, StringComparison.Ordinal);
        Assert.Equal("token", handler.LastRequestToken);
    }

    [Fact]
    public async Task TransportFailureIsRetriedOnceWithBoundedBackoff()
    {
        var handler = new ThrowingHandler();
        using var client = new BackendClient("http://127.0.0.1:8000/api/v1", null, TimeSpan.FromSeconds(5), handler);
        var watch = System.Diagnostics.Stopwatch.StartNew();

        var result = await client.PostScanAsync("{\"schema_version\":\"1.0\"}"u8.ToArray(), CancellationToken.None);

        watch.Stop();
        Assert.False(result.Ok);
        Assert.Equal(2, result.Attempts);
        Assert.Equal(2, handler.Attempts);
        Assert.True(watch.Elapsed >= TimeSpan.FromMilliseconds(450), $"退避时间不足：{watch.ElapsedMilliseconds}ms");
        Assert.True(watch.Elapsed < TimeSpan.FromSeconds(5), $"退避时间异常：{watch.ElapsedMilliseconds}ms");
    }

    private sealed class ThrowingHandler : HttpMessageHandler
    {
        public int Attempts { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Attempts++;
            throw new HttpRequestException("simulated network outage");
        }
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly string _body;

        public StubHandler(string body) => _body = body;

        public string LastRequestUri { get; private set; } = string.Empty;

        public string? LastRequestToken { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastRequestUri = request.RequestUri?.ToString() ?? string.Empty;
            LastRequestToken = request.Headers.TryGetValues("X-ScoutMind-Token", out var values)
                ? values.FirstOrDefault()
                : null;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(_body, Encoding.UTF8, "application/json"),
            });
        }
    }
}
