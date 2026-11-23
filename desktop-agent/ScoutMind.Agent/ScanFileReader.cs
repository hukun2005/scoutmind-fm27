using System.Text;
using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Agent;

/// <summary>
/// 待上传的扫描报文：已转换为协议形态的 UTF-8 字节，以及用于日志的扫描 ID。
/// </summary>
/// <param name="Json">UTF-8 编码的协议 JSON。</param>
/// <param name="ScanId">扫描 ID（后端幂等键）。</param>
/// <param name="AlreadyProtocol">文件本身是否已经是协议形态（无需转换）。</param>
public sealed record ScanFilePayload(byte[] Json, string ScanId, bool AlreadyProtocol);

/// <summary>读自扫描文件的日期/存档提示；缺失就是缺失，不推断。</summary>
public sealed record ScanFileInfo(string ScanId, string? GameDate);

/// <summary>
/// 读取扫描文件并转换为 <c>docs/DATA_PROTOCOL.md</c> 定义的线上形态。
/// 本地信封是 camelCase（<c>scan-*.json</c>），上传前必须转换键名，字段值不做任何改写。
/// </summary>
public static class ScanFileReader
{
    /// <summary>读取并转换一个扫描文件。</summary>
    /// <param name="path">扫描文件绝对路径。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>待上传的报文。</returns>
    /// <exception cref="FileNotFoundException">文件不存在。</exception>
    /// <exception cref="InvalidDataException">文件为空、不是 JSON 对象或结构无法识别。</exception>
    public static async Task<ScanFilePayload> LoadAsync(string path, CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            throw new FileNotFoundException($"扫描文件不存在：{path}", path);
        }

        var text = await File.ReadAllTextAsync(path, cancellationToken).ConfigureAwait(false);
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new InvalidDataException($"扫描文件为空：{path}");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(text, new JsonDocumentOptions
            {
                AllowTrailingCommas = true,
                CommentHandling = JsonCommentHandling.Skip,
            });
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException($"扫描文件不是合法 JSON（{path}）：{ex.Message}", ex);
        }

        using (document)
        {
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException($"扫描文件根节点必须是对象：{path}");
            }

            if (ScanProtocolSerializer.LooksLikeProtocolPayload(root))
            {
                return new ScanFilePayload(Encoding.UTF8.GetBytes(text), ReadProtocolScanId(root), true);
            }

            ScanEnvelope? envelope;
            try
            {
                envelope = JsonSerializer.Deserialize<ScanEnvelope>(text, ScoutMindJson.Options);
            }
            catch (JsonException ex)
            {
                throw new InvalidDataException($"无法按读取器信封结构解析 {path}：{ex.Message}", ex);
            }

            if (envelope is null)
            {
                throw new InvalidDataException($"无法按读取器信封结构解析 {path}。");
            }

            return new ScanFilePayload(
                ScanProtocolSerializer.ToProtocolJson(envelope),
                envelope.Scan.ScanId,
                false);
        }
    }

    /// <summary>读取扫描文件的日期信息，不转换、不上传。</summary>
    public static async Task<ScanFileInfo> ReadInfoAsync(string path, CancellationToken cancellationToken)
    {
        var text = await File.ReadAllTextAsync(path, cancellationToken).ConfigureAwait(false);
        using var document = JsonDocument.Parse(text);
        var root = document.RootElement;
        if (!root.TryGetProperty("scan", out var scan) || scan.ValueKind != JsonValueKind.Object)
        {
            return new ScanFileInfo(string.Empty, null);
        }

        var scanId = scan.TryGetProperty("scan_id", out var protocolId) && protocolId.ValueKind == JsonValueKind.String
            ? protocolId.GetString() ?? string.Empty
            : scan.TryGetProperty("scanId", out var localId) && localId.ValueKind == JsonValueKind.String
                ? localId.GetString() ?? string.Empty
                : string.Empty;
        var gameDate = scan.TryGetProperty("game_date", out var snakeDate) && snakeDate.ValueKind == JsonValueKind.String
            ? snakeDate.GetString()
            : scan.TryGetProperty("gameDate", out var camelDate) && camelDate.ValueKind == JsonValueKind.String
                ? camelDate.GetString()
                : null;
        return new ScanFileInfo(scanId, gameDate);
    }

    private static string ReadProtocolScanId(JsonElement root)
    {
        if (root.TryGetProperty("scan", out var scan)
            && scan.ValueKind == JsonValueKind.Object
            && scan.TryGetProperty("scan_id", out var scanId)
            && scanId.ValueKind == JsonValueKind.String)
        {
            return scanId.GetString() ?? string.Empty;
        }

        return string.Empty;
    }
}
