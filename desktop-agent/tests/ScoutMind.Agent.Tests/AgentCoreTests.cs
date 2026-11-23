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
}
