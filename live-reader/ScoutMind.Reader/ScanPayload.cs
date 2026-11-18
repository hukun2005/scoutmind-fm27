using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 扫描器输出未通过协议校验。消息为中文，会原样出现在 <c>ScanResult.failureReason</c> 中。
/// </summary>
public sealed class ScanOutputException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="message">中文错误说明。</param>
    public ScanOutputException(string message)
        : base(message)
    {
    }

    /// <summary>创建异常并保留内部原因。</summary>
    /// <param name="message">中文错误说明。</param>
    /// <param name="innerException">导致失败的原始异常。</param>
    public ScanOutputException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>
/// 扫描器输出的结构化副本。字段名同时接受协议使用的 snake_case 与 camelCase，
/// 缺失值保持 <c>null</c>，绝不填默认值。
/// </summary>
/// <param name="SchemaVersion">扫描器声明的协议版本，必须存在。</param>
/// <param name="Source">扫描器声明的来源标记（仅记录，不覆盖读取器自身的来源标记）。</param>
/// <param name="ReaderVersion">扫描器声明的读取器版本（仅记录）。</param>
/// <param name="Game">扫描器声明的游戏信息。</param>
/// <param name="ScanId">扫描器生成的工作扫描 ID。</param>
/// <param name="ObservedAt">扫描器生成的观测时间（ISO-8601 字符串）。</param>
/// <param name="GameDate">游戏内日期。</param>
/// <param name="UserClubUid">玩家执教俱乐部 UID。</param>
/// <param name="Coverage">扫描器声明的数据覆盖情况。</param>
/// <param name="Warnings">扫描器自带的告警。</param>
/// <param name="Clubs">俱乐部记录原始 JSON。</param>
/// <param name="Players">球员记录原始 JSON。</param>
/// <param name="Transfers">转会记录原始 JSON。</param>
public sealed record ScanPayload(
    string SchemaVersion,
    string? Source,
    string? ReaderVersion,
    ScanGame Game,
    string? ScanId,
    string? ObservedAt,
    string? GameDate,
    string? UserClubUid,
    Dictionary<string, bool> Coverage,
    List<string> Warnings,
    List<JsonElement> Clubs,
    List<JsonElement> Players,
    List<JsonElement> Transfers);

/// <summary>
/// 解析并校验外部扫描器写出的 JSON。只接受「根节点是对象、含 <c>schema_version</c> 字符串、
/// 含 <c>players</c> 数组」的报文，其余一律判为协议校验失败。
/// </summary>
public static class ScanPayloadParser
{
    /// <summary>解析扫描器输出。</summary>
    /// <param name="json">扫描器写出的 JSON 文本。</param>
    /// <returns>结构化副本，其中的 JSON 元素已 <c>Clone</c>，不依赖原始文档生命周期。</returns>
    /// <exception cref="ScanOutputException">输出为空、不是 JSON 对象或缺少必需字段。</exception>
    public static ScanPayload Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            throw new ScanOutputException("扫描器输出为空，无法校验扫描协议。");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(json, new JsonDocumentOptions
            {
                AllowTrailingCommas = true,
                CommentHandling = JsonCommentHandling.Skip,
                MaxDepth = 64,
            });
        }
        catch (JsonException ex)
        {
            throw new ScanOutputException($"扫描器输出不是合法 JSON：{ex.Message}", ex);
        }

        using (document)
        {
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new ScanOutputException($"扫描器输出的根节点必须是 JSON 对象，实际为 {root.ValueKind}。");
            }

            var schemaVersion = ReadRequiredString(root, "schema_version", "schemaVersion");
            var warnings = new List<string>();

            if (!root.TryGetProperty("players", out var playersElement) || playersElement.ValueKind != JsonValueKind.Array)
            {
                throw new ScanOutputException("扫描器输出缺少 players 数组，拒绝导入。");
            }

            var game = ReadGame(root);
            var scanId = ReadScanField(root, "scan_id", "scanId");
            var observedAt = ReadScanField(root, "observed_at", "observedAt");
            var gameDate = ReadScanField(root, "game_date", "gameDate");
            var userClubUid = ReadScanField(root, "user_club_uid", "userClubUid");

            return new ScanPayload(
                SchemaVersion: schemaVersion,
                Source: ReadOptionalString(root, "source"),
                ReaderVersion: ReadOptionalString(root, "reader_version") ?? ReadOptionalString(root, "readerVersion"),
                Game: game,
                ScanId: scanId,
                ObservedAt: observedAt,
                GameDate: gameDate,
                UserClubUid: userClubUid,
                Coverage: ReadCoverage(root, warnings),
                Warnings: ReadWarnings(root, warnings),
                Clubs: ReadOptionalArray(root, "clubs", warnings),
                Players: playersElement.EnumerateArray().Select(static element => element.Clone()).ToList(),
                Transfers: ReadOptionalArray(root, "transfers", warnings));
        }
    }

    private static ScanGame ReadGame(JsonElement root)
    {
        if (!root.TryGetProperty("game", out var gameElement) || gameElement.ValueKind != JsonValueKind.Object)
        {
            return new ScanGame(null, null, null);
        }

        return new ScanGame(
            Version: ReadOptionalString(gameElement, "version"),
            Build: ReadOptionalString(gameElement, "build"),
            AppId: ReadOptionalString(gameElement, "app_id") ?? ReadOptionalString(gameElement, "appId"));
    }

    private static string? ReadScanField(JsonElement root, string snakeCaseName, string camelCaseName)
    {
        if (!root.TryGetProperty("scan", out var scanElement) || scanElement.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        return ReadOptionalString(scanElement, snakeCaseName) ?? ReadOptionalString(scanElement, camelCaseName);
    }

    private static Dictionary<string, bool> ReadCoverage(JsonElement root, List<string> warnings)
    {
        var coverage = new Dictionary<string, bool>(StringComparer.Ordinal);
        if (!root.TryGetProperty("coverage", out var coverageElement) || coverageElement.ValueKind != JsonValueKind.Object)
        {
            return coverage;
        }

        foreach (var property in coverageElement.EnumerateObject())
        {
            if (property.Value.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                coverage[property.Name] = property.Value.GetBoolean();
            }
            else
            {
                warnings.Add($"coverage.{property.Name} 不是布尔值，已忽略。");
            }
        }

        return coverage;
    }

    private static List<string> ReadWarnings(JsonElement root, List<string> warnings)
    {
        var result = new List<string>();
        if (!root.TryGetProperty("warnings", out var warningsElement) || warningsElement.ValueKind != JsonValueKind.Array)
        {
            return result;
        }

        foreach (var item in warningsElement.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String)
            {
                result.Add(item.GetString()!);
            }
            else
            {
                warnings.Add($"warnings 中的非字符串项（{item.ValueKind}）已忽略。");
            }
        }

        return result;
    }

    private static List<JsonElement> ReadOptionalArray(JsonElement root, string propertyName, List<string> warnings)
    {
        if (!root.TryGetProperty(propertyName, out var element))
        {
            return new List<JsonElement>();
        }

        if (element.ValueKind != JsonValueKind.Array)
        {
            warnings.Add($"{propertyName} 不是数组，已按空集合处理。");
            return new List<JsonElement>();
        }

        return element.EnumerateArray().Select(static item => item.Clone()).ToList();
    }

    private static string ReadRequiredString(JsonElement element, string snakeCaseName, string camelCaseName)
    {
        var value = ReadOptionalString(element, snakeCaseName) ?? ReadOptionalString(element, camelCaseName);
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ScanOutputException($"扫描器输出缺少必需的字符串字段 {snakeCaseName}。");
        }

        return value;
    }

    private static string? ReadOptionalString(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        var text = value.GetString();
        return string.IsNullOrWhiteSpace(text) ? null : text;
    }
}
