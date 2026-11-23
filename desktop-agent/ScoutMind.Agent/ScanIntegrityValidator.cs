using System.Security.Cryptography;
using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>Result of validating a scan envelope/meta pair before import.</summary>
public sealed record ScanIntegrityResult(
    bool Valid,
    string Code,
    string Message,
    string? ActualSha256,
    long? ActualSize,
    string? ScanId);

/// <summary>
/// Validates envelope bytes against the SHA-256/size written into the meta sidecar. A failure must
/// quarantine the pair; it must never fall through to the importer or sent archive.
/// </summary>
public static class ScanIntegrityValidator
{
    public static async Task<ScanIntegrityResult> ValidateAsync(
        string envelopePath,
        string metaPath,
        CancellationToken cancellationToken) =>
        await ValidateAsync(envelopePath, metaPath, ScanManifest.PathFor(envelopePath), cancellationToken)
            .ConfigureAwait(false);

    /// <summary>
    /// Validates envelope, meta and (when present) the manifest: payload and metadata digests must match the
    /// bytes about to be uploaded, and the manifest scan id must agree with the envelope.
    /// </summary>
    public static async Task<ScanIntegrityResult> ValidateAsync(
        string envelopePath,
        string metaPath,
        string manifestPath,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(envelopePath))
            return Fail("envelope_missing", $"信封不存在：{envelopePath}");
        if (!File.Exists(metaPath))
            return Fail("meta_missing", $"meta 不存在：{metaPath}");

        var bytes = await File.ReadAllBytesAsync(envelopePath, cancellationToken).ConfigureAwait(false);
        var metaBytes = await File.ReadAllBytesAsync(metaPath, cancellationToken).ConfigureAwait(false);
        var actualSize = bytes.LongLength;
        var actualHash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        JsonDocument meta;
        try
        {
            meta = JsonDocument.Parse(metaBytes);
        }
        catch (JsonException ex)
        {
            return Fail("meta_invalid_json", ex.Message, actualHash, actualSize);
        }

        using (meta)
        {
            var root = meta.RootElement;
            var expectedHash = ReadString(root, "envelopeSha256") ?? ReadString(root, "EnvelopeSha256");
            var expectedSize = ReadLong(root, "envelopeSize") ?? ReadLong(root, "EnvelopeSize");
            var metaScanId = ReadString(root, "scanId") ?? ReadString(root, "ScanId");
            if (string.IsNullOrWhiteSpace(expectedHash))
                return Fail("meta_missing_sha256", "meta 没有 envelopeSha256", actualHash, actualSize, metaScanId);
            if (expectedSize is null)
                return Fail("meta_missing_size", "meta 没有 envelopeSize", actualHash, actualSize, metaScanId);
            if (expectedSize != actualSize)
                return Fail("size_mismatch", $"文件大小 {actualSize} 与 meta {expectedSize} 不一致", actualHash, actualSize, metaScanId);
            if (!string.Equals(expectedHash, actualHash, StringComparison.OrdinalIgnoreCase))
                return Fail("sha256_mismatch", "SHA-256 与 meta 不一致", actualHash, actualSize, metaScanId);

            JsonDocument envelope;
            try
            {
                envelope = JsonDocument.Parse(bytes);
            }
            catch (JsonException ex)
            {
                return Fail("envelope_invalid_json", ex.Message, actualHash, actualSize, metaScanId);
            }

            using (envelope)
            {
                if (!envelope.RootElement.TryGetProperty("scan", out var scan) || scan.ValueKind != JsonValueKind.Object)
                    return Fail("envelope_missing_scan", "信封缺少 scan 对象", actualHash, actualSize, metaScanId);
                var envelopeScanId = ReadString(scan, "scanId") ?? ReadString(scan, "scan_id");
                if (string.IsNullOrWhiteSpace(envelopeScanId))
                    return Fail("envelope_missing_scan_id", "信封缺少 scan_id", actualHash, actualSize, metaScanId);
                if (!string.IsNullOrWhiteSpace(metaScanId)
                    && !string.Equals(metaScanId, envelopeScanId, StringComparison.Ordinal))
                    return Fail("scan_id_mismatch", $"meta scanId {metaScanId} 与信封 {envelopeScanId} 不一致", actualHash, actualSize, metaScanId);

                if (File.Exists(manifestPath))
                {
                    var manifest = ScanManifest.TryRead(manifestPath);
                    if (manifest is null)
                        return Fail("manifest_invalid", "manifest 无法解析", actualHash, actualSize, envelopeScanId);
                    if (!manifest.MatchesPayload(bytes))
                        return Fail("payload_sha256_mismatch", "信封与 manifest 的 payload_sha256 不一致", actualHash, actualSize, envelopeScanId);
                    if (!manifest.MatchesMetadata(metaBytes))
                        return Fail("metadata_sha256_mismatch", "meta 与 manifest 的 metadata_sha256 不一致", actualHash, actualSize, envelopeScanId);
                    if (!string.IsNullOrWhiteSpace(manifest.ScanId)
                        && !string.Equals(manifest.ScanId, envelopeScanId, StringComparison.Ordinal))
                        return Fail("manifest_scan_id_mismatch", $"manifest scan_id {manifest.ScanId} 与信封 {envelopeScanId} 不一致", actualHash, actualSize, envelopeScanId);
                }

                return new ScanIntegrityResult(true, "ok", "完整性与基本结构校验通过", actualHash, actualSize, envelopeScanId);
            }
        }
    }

    private static string? ReadString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static long? ReadLong(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt64(out var number) ? number : null;

    private static ScanIntegrityResult Fail(
        string code, string message, string? hash = null, long? size = null, string? scanId = null) =>
        new(false, code, message, hash, size, scanId);
}
