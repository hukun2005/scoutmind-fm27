using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>
/// 一次扫描任务的 manifest：把信封、meta 与两份摘要绑在一起。
///
/// Reader 只写信封和 meta；Agent 在入队时补齐 manifest，并在每次上传前用它确认“这份文件没有被替换过”。
/// 缺失 manifest 的旧任务会被补建，而不是拒绝——补建用的是当前字节，随后仍要过 meta 的 SHA-256 校验。
/// </summary>
public sealed record ScanManifest(
    string ScanId,
    string? ReaderVersion,
    string? SchemaVersion,
    string PayloadFile,
    string? MetadataFile,
    string PayloadSha256,
    string? MetadataSha256,
    long PayloadSize,
    long? MetadataSize,
    string CreatedAt)
{
    /// <summary>manifest 结构版本。</summary>
    public const string Schema = "scoutmind.scan.manifest.v1";

    /// <summary>信封对应的 manifest 路径。</summary>
    /// <param name="envelopePath">扫描信封路径。</param>
    /// <returns>同目录下的 <c>*.manifest.json</c>。</returns>
    public static string PathFor(string envelopePath)
    {
        var directory = Path.GetDirectoryName(Path.GetFullPath(envelopePath)) ?? ".";
        var stem = Path.GetFileNameWithoutExtension(envelopePath);
        return Path.Combine(directory, stem + ".manifest.json");
    }

    /// <summary>按当前字节构建 manifest（不写盘）。</summary>
    /// <param name="envelopePath">扫描信封路径。</param>
    /// <param name="metaPath">meta 边车路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>manifest。</returns>
    public static async Task<ScanManifest> BuildAsync(
        string envelopePath,
        string metaPath,
        CancellationToken cancellationToken)
    {
        var payloadBytes = await File.ReadAllBytesAsync(envelopePath, cancellationToken).ConfigureAwait(false);
        var metaBytes = File.Exists(metaPath)
            ? await File.ReadAllBytesAsync(metaPath, cancellationToken).ConfigureAwait(false)
            : null;

        var scanId = string.Empty;
        string? readerVersion = null;
        string? schemaVersion = null;
        using (var envelope = JsonDocument.Parse(payloadBytes))
        {
            var root = envelope.RootElement;
            if (root.TryGetProperty("scan", out var scan) && scan.ValueKind == JsonValueKind.Object)
            {
                scanId = ReadString(scan, "scanId") ?? ReadString(scan, "scan_id") ?? string.Empty;
            }

            readerVersion = ReadString(root, "readerVersion") ?? ReadString(root, "reader_version");
            schemaVersion = ReadString(root, "schemaVersion") ?? ReadString(root, "schema_version");
        }

        return new ScanManifest(
            ScanId: scanId,
            ReaderVersion: readerVersion,
            SchemaVersion: schemaVersion,
            PayloadFile: Path.GetFileName(envelopePath),
            MetadataFile: metaBytes is null ? null : Path.GetFileName(metaPath),
            PayloadSha256: Digest(payloadBytes),
            MetadataSha256: metaBytes is null ? null : Digest(metaBytes),
            PayloadSize: payloadBytes.LongLength,
            MetadataSize: metaBytes?.LongLength,
            CreatedAt: DateTimeOffset.UtcNow.ToString("O"));
    }

    /// <summary>读取已存在的 manifest；不存在或无法解析时为 <c>null</c>。</summary>
    /// <param name="path">manifest 路径。</param>
    /// <returns>manifest 或 <c>null</c>。</returns>
    public static ScanManifest? TryRead(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            var scanId = ReadString(root, "scanId") ?? ReadString(root, "scan_id") ?? string.Empty;
            var payloadHash = ReadString(root, "payloadSha256") ?? ReadString(root, "payload_sha256");
            var payloadSize = ReadLong(root, "payloadSize") ?? ReadLong(root, "payload_size");
            if (string.IsNullOrWhiteSpace(payloadHash) || payloadSize is null)
            {
                return null;
            }

            return new ScanManifest(
                ScanId: scanId,
                ReaderVersion: ReadString(root, "readerVersion") ?? ReadString(root, "reader_version"),
                SchemaVersion: ReadString(root, "schemaVersion") ?? ReadString(root, "schema_version"),
                PayloadFile: ReadString(root, "payloadFile") ?? ReadString(root, "payload_file") ?? string.Empty,
                MetadataFile: ReadString(root, "metadataFile") ?? ReadString(root, "metadata_file"),
                PayloadSha256: payloadHash,
                MetadataSha256: ReadString(root, "metadataSha256") ?? ReadString(root, "metadata_sha256"),
                PayloadSize: payloadSize.Value,
                MetadataSize: ReadLong(root, "metadataSize") ?? ReadLong(root, "metadata_size"),
                CreatedAt: ReadString(root, "createdAt") ?? ReadString(root, "created_at") ?? string.Empty);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>写出 manifest（先写临时文件再原子替换）。</summary>
    /// <param name="path">目标路径。</param>
    /// <param name="manifest">要写入的 manifest。</param>
    public static void Write(string path, ScanManifest manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        var json = JsonSerializer.Serialize(
            new
            {
                schema = Schema,
                scan_id = manifest.ScanId,
                reader_version = manifest.ReaderVersion,
                schema_version = manifest.SchemaVersion,
                payload_file = manifest.PayloadFile,
                metadata_file = manifest.MetadataFile,
                payload_sha256 = manifest.PayloadSha256,
                metadata_sha256 = manifest.MetadataSha256,
                payload_size = manifest.PayloadSize,
                metadata_size = manifest.MetadataSize,
                created_at = manifest.CreatedAt,
            },
            new JsonSerializerOptions { WriteIndented = true });
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        File.Move(temporary, path, overwrite: true);
    }

    /// <summary>确保 manifest 存在并返回它；缺失时按当前字节补建。</summary>
    /// <param name="envelopePath">扫描信封路径。</param>
    /// <param name="metaPath">meta 边车路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>manifest。</returns>
    public static async Task<ScanManifest> EnsureAsync(
        string envelopePath,
        string metaPath,
        CancellationToken cancellationToken)
    {
        var manifestPath = PathFor(envelopePath);
        var existing = TryRead(manifestPath);
        if (existing is not null)
        {
            return existing;
        }

        var built = await BuildAsync(envelopePath, metaPath, cancellationToken).ConfigureAwait(false);
        Write(manifestPath, built);
        return built;
    }

    /// <summary>信封字节是否与 manifest 一致。</summary>
    /// <param name="bytes">当前信封字节。</param>
    /// <returns>一致时为 <c>true</c>。</returns>
    public bool MatchesPayload(byte[] bytes)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        return bytes.LongLength == PayloadSize
               && string.Equals(Digest(bytes), PayloadSha256, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>meta 字节是否与 manifest 一致。</summary>
    /// <param name="bytes">当前 meta 字节。</param>
    /// <returns>一致时为 <c>true</c>；manifest 没记录 meta 摘要时为 <c>false</c>。</returns>
    public bool MatchesMetadata(byte[] bytes)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        return MetadataSha256 is not null
               && MetadataSize == bytes.LongLength
               && string.Equals(Digest(bytes), MetadataSha256, StringComparison.OrdinalIgnoreCase);
    }

    private static string Digest(byte[] bytes) =>
        Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static string? ReadString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

    private static long? ReadLong(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt64(out var number) ? number : null;
}
