using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ScoutMind.Agent;
using Xunit;

namespace ScoutMind.Agent.Tests;

public sealed class AgentCoreTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "scoutmind-agent-tests-" + Guid.NewGuid().ToString("N"));

    public AgentCoreTests() => Directory.CreateDirectory(_root);
    public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } }

    [Fact]
    public void ParseAutoControlFlags()
    {
        var pause = AgentCommandLine.Parse(new[] { "auto", "--pause" });
        Assert.True(pause.Ok);
        Assert.Equal(AgentCommand.Auto, pause.Options!.Command);
        Assert.Equal("pause", pause.Options.AutoControl);

        var missing = AgentCommandLine.Parse(new[] { "auto" });
        Assert.False(missing.Ok);
    }

    [Fact]
    public void StateStoreRoundTripsAtomically()
    {
        var store = new CaptureStateStore(_root);
        store.Save(new CaptureState("save-a", "2026-07-14", "scan-1", "completed", 0, null));
        var loaded = store.Load();
        Assert.Equal("save-a", loaded.SaveName);
        Assert.Equal("2026-07-14", loaded.LastGameDate);
        Assert.Equal("completed", loaded.Status);
        Assert.False(File.Exists(store.Path + ".tmp"));
    }

    [Fact]
    public void ControlPauseAndResume()
    {
        Assert.False(CaptureControl.IsPaused(_root));
        CaptureControl.Set(_root, "paused");
        Assert.True(CaptureControl.IsPaused(_root));
        CaptureControl.Set(_root, "running");
        Assert.False(CaptureControl.IsPaused(_root));
    }

    [Fact]
    public void LockRejectsSecondOwnerAndReleases()
    {
        var first = CaptureLock.TryAcquire(_root, out _);
        Assert.NotNull(first);
        var second = CaptureLock.TryAcquire(_root, out var message);
        Assert.Null(second);
        Assert.Contains("另一个 Agent", message);
        first!.Dispose();
        var third = CaptureLock.TryAcquire(_root, out _);
        Assert.NotNull(third);
        third!.Dispose();
    }

    [Fact]
    public async Task IntegrityAcceptsValidPairAndRejectsTamper()
    {
        var envelopePath = Path.Combine(_root, "scan-1.json");
        var metaPath = Path.Combine(_root, "scan-1.meta.json");
        var envelope = "{\"scan\":{\"scanId\":\"1\"},\"players\":[],\"transfers\":[]}";
        var bytes = Encoding.UTF8.GetBytes(envelope);
        var hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        File.WriteAllBytes(envelopePath, bytes);
        File.WriteAllText(metaPath, JsonSerializer.Serialize(new
        {
            scanId = "1",
            envelopeSha256 = hash,
            envelopeSize = bytes.LongLength,
            readerVersion = "test",
        }));
        var valid = await ScanIntegrityValidator.ValidateAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.True(valid.Valid, valid.Message);

        File.AppendAllText(envelopePath, " ");
        var invalid = await ScanIntegrityValidator.ValidateAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.False(invalid.Valid);
        Assert.Equal("size_mismatch", invalid.Code);

        var missing = await ScanIntegrityValidator.ValidateAsync(
            Path.Combine(_root, "nope.json"), metaPath, CancellationToken.None);
        Assert.Equal("envelope_missing", missing.Code);
    }

    [Fact]
    public async Task ManifestBindsEnvelopeMetaAndScanId()
    {
        var (envelopePath, metaPath) = WritePair("scan-manifest", "manifest-scan");
        var manifest = await ScanManifest.EnsureAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.Equal("manifest-scan", manifest.ScanId);
        Assert.True(File.Exists(ScanManifest.PathFor(envelopePath)), "manifest 应落盘");

        var valid = await ScanIntegrityValidator.ValidateAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.True(valid.Valid, valid.Message);

        // Tamper the metadata after the manifest was written: the manifest must catch it.
        File.WriteAllText(metaPath, JsonSerializer.Serialize(new
        {
            scanId = "manifest-scan",
            envelopeSha256 = "0".PadLeft(64, '0'),
            envelopeSize = new FileInfo(envelopePath).Length,
        }));
        var tampered = await ScanIntegrityValidator.ValidateAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.False(tampered.Valid);
        Assert.Equal("sha256_mismatch", tampered.Code);
    }

    [Fact]
    public async Task ManifestRejectsReplacedPayload()
    {
        var (envelopePath, metaPath) = WritePair("scan-replaced", "replaced-scan");
        await ScanManifest.EnsureAsync(envelopePath, metaPath, CancellationToken.None);

        var bytes = Encoding.UTF8.GetBytes("{\"scan\":{\"scanId\":\"replaced-scan\"},\"players\":[{}],\"transfers\":[]}");
        File.WriteAllBytes(envelopePath, bytes);
        var meta = JsonSerializer.Serialize(new
        {
            scanId = "replaced-scan",
            envelopeSha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            envelopeSize = bytes.LongLength,
        });
        File.WriteAllText(metaPath, meta);

        var result = await ScanIntegrityValidator.ValidateAsync(envelopePath, metaPath, CancellationToken.None);
        Assert.False(result.Valid);
        Assert.Equal("payload_sha256_mismatch", result.Code);
    }

    [Fact]
    public async Task QueueMovesWholeTaskAndCarriesSidecarsOnRetry()
    {
        var queue = new ScanQueue(Path.Combine(_root, "queue"));
        queue.EnsureCreated();
        var (envelopePath, metaPath) = WritePair("scan-queue", "queue-scan", queue.ScanDirectory);
        await ScanManifest.EnsureAsync(envelopePath, metaPath, CancellationToken.None);

        var claimed = queue.Claim(envelopePath);
        Assert.NotNull(claimed);
        Assert.StartsWith(queue.ProcessingDirectory, claimed, StringComparison.OrdinalIgnoreCase);
        Assert.True(File.Exists(ClaimedMeta(claimed!)), "meta 必须跟着信封进入 processing");
        Assert.True(File.Exists(ScanManifest.PathFor(claimed!)), "manifest 必须跟着信封进入 processing");

        // The historical bug: retry copied only the envelope and the next validation quarantined the task.
        var pending = queue.EnqueuePending(claimed!);
        Assert.NotNull(pending);
        Assert.True(File.Exists(pending!), "信封应进入 pending");
        Assert.True(File.Exists(ScanQueue.MetaPathFor(pending!)), "meta 必须一起进入 pending");
        Assert.True(File.Exists(ScanManifest.PathFor(pending!)), "manifest 必须一起进入 pending");

        var archived = queue.ArchiveAll(pending!);
        Assert.True(File.Exists(archived), "归档的信封应存在");
        Assert.True(File.Exists(ScanQueue.MetaPathFor(archived)), "meta 应一起归档");
        Assert.True(File.Exists(ScanManifest.PathFor(archived)), "manifest 应一起归档");
    }

    [Fact]
    public async Task QuarantineKeepsAllThreeFiles()
    {
        var queue = new ScanQueue(Path.Combine(_root, "queue-quarantine"));
        queue.EnsureCreated();
        var (envelopePath, metaPath) = WritePair("scan-bad", "bad-scan", queue.ScanDirectory);
        await ScanManifest.EnsureAsync(envelopePath, metaPath, CancellationToken.None);

        var folder = queue.QuarantineAll(envelopePath, new { code = "sha256_mismatch" });
        Assert.NotNull(folder);
        Assert.True(File.Exists(Path.Combine(folder!, "scan-bad.json")), "信封应保留");
        Assert.True(File.Exists(Path.Combine(folder!, "scan-bad.meta.json")), "meta 应保留");
        Assert.True(File.Exists(Path.Combine(folder!, "scan-bad.manifest.json")), "manifest 应保留");
        Assert.True(File.Exists(Path.Combine(folder!, "quarantine.json")), "隔离原因应保留");
    }

    [Fact]
    public async Task BackendJobLookupUsesScanId()
    {
        var handler = new StubHandler(
            "{\"items\":[{\"id\":7,\"scan_id\":\"scan-42\",\"status\":\"succeeded\",\"player_count\":44084,\"transfer_count\":0}],\"total\":1}");
        using var client = new BackendClient("http://127.0.0.1:8000/api/v1", null, TimeSpan.FromSeconds(5), handler);
        var job = await client.GetJobAsync("scan-42", CancellationToken.None);
        Assert.NotNull(job);
        Assert.Equal(7, job!.Id);
        Assert.Equal("succeeded", job.Status);
        Assert.Equal(44084, job.PlayerCount);
        Assert.True(job.IsComplete);
        Assert.Contains("scan_id=scan-42", handler.LastRequestUri, StringComparison.Ordinal);
    }

    [Fact]
    public async Task BackendJobLookupReportsRunningAndFailure()
    {
        var running = new StubHandler("{\"items\":[{\"id\":2,\"status\":\"running\"}],\"total\":1}");
        using var runningClient = new BackendClient("http://127.0.0.1:8000/api/v1", null, TimeSpan.FromSeconds(5), running);
        var job = await runningClient.GetJobAsync("scan-1", CancellationToken.None);
        Assert.NotNull(job);
        Assert.False(job!.IsTerminal);
        Assert.False(job.IsComplete);

        var missing = new StubHandler("{\"items\":[],\"total\":0}");
        using var missingClient = new BackendClient("http://127.0.0.1:8000/api/v1", null, TimeSpan.FromSeconds(5), missing);
        Assert.Null(await missingClient.GetJobAsync("scan-x", CancellationToken.None));
    }

    private (string Envelope, string Meta) WritePair(string stem, string scanId, string? directory = null)
    {
        directory ??= _root;
        Directory.CreateDirectory(directory);
        var envelopePath = Path.Combine(directory, stem + ".json");
        var metaPath = Path.Combine(directory, stem + ".meta.json");
        var bytes = Encoding.UTF8.GetBytes(
            "{\"schemaVersion\":\"1.1\",\"scan\":{\"scanId\":\"" + scanId + "\"},\"players\":[],\"transfers\":[]}");
        File.WriteAllBytes(envelopePath, bytes);
        File.WriteAllText(metaPath, JsonSerializer.Serialize(new
        {
            scanId,
            envelopeSha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(),
            envelopeSize = bytes.LongLength,
            readerVersion = "0.1.0",
        }));
        return (envelopePath, metaPath);
    }

    private static string ClaimedMeta(string claimedEnvelope) => ScanQueue.MetaPathFor(claimedEnvelope);

    private sealed class StubHandler : HttpMessageHandler
    {
        private readonly string _body;

        public StubHandler(string body) => _body = body;

        public string LastRequestUri { get; private set; } = string.Empty;

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastRequestUri = request.RequestUri?.ToString() ?? string.Empty;
            return Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent(_body, Encoding.UTF8, "application/json"),
            });
        }
    }
}
