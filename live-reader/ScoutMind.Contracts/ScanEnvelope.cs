using System.Text.Encodings.Web;
using System.Text.Json;

namespace ScoutMind.Contracts;

/// <summary>
/// 扫描信封中 <c>game</c> 对象的内容。值优先取扫描器输出，缺失时回落到读取器自身的检测结果。
/// </summary>
/// <param name="Version">游戏版本，例如 <c>27.0.1</c>。</param>
/// <param name="Build">构建号，例如 <c>26577676</c>；缺失时必须为 <c>null</c>，不得猜测。</param>
/// <param name="AppId">Steam AppId，FM27 为 <c>4530370</c>。</param>
public sealed record ScanGame(
    string? Version,
    string? Build,
    string? AppId);

/// <summary>
/// 扫描信封中 <c>scan</c> 对象的内容。<see cref="ScanId"/> 是后端的幂等键。
/// </summary>
/// <param name="ScanId">扫描标识；扫描器未提供时由读取器生成并在 warnings 中说明。</param>
/// <param name="ObservedAt">观测时间，ISO-8601 UTC 字符串。</param>
/// <param name="GameDate">游戏内日期 <c>YYYY-MM-DD</c>；扫描器未提供时为 <c>null</c>。</param>
/// <param name="UserClubUid">玩家执教俱乐部的存档内 UID；未提供时为 <c>null</c>。</param>
public sealed record ScanMetadata(
    string ScanId,
    string ObservedAt,
    string? GameDate,
    string? UserClubUid);

/// <summary>
/// 读取器落盘的原始扫描信封，未经任何清洗或补值。
/// <c>clubs</c> / <c>players</c> / <c>transfers</c> 保留扫描器输出的原始 JSON 元素，
/// 读取器不解释字段语义，只负责计数与转发。
/// </summary>
/// <param name="SchemaVersion">数据协议版本；由扫描器声明，带身份块时 mapper 输出 <c>1.1</c>。</param>
/// <param name="Source">数据来源标记，读取器固定写 <c>fm27_live_reader</c>。</param>
/// <param name="ReaderVersion">读取器版本，写入导入任务便于追溯。</param>
/// <param name="Game">游戏与构建信息。</param>
/// <param name="Scan">扫描标识与观测时间。</param>
/// <param name="Coverage">本次扫描覆盖到的数据域，例如 <c>players</c> / <c>transfers</c>。</param>
/// <param name="Warnings">扫描器与读取器产生的告警，原样上报，不静默丢弃。</param>
/// <param name="Clubs">俱乐部记录原始 JSON。</param>
/// <param name="Players">球员记录原始 JSON。</param>
/// <param name="Transfers">转会记录原始 JSON。</param>
public sealed record ScanEnvelope(
    string SchemaVersion,
    string Source,
    string ReaderVersion,
    ScanGame Game,
    ScanMetadata Scan,
    Dictionary<string, bool> Coverage,
    List<string> Warnings,
    List<JsonElement> Clubs,
    List<JsonElement> Players,
    List<JsonElement> Transfers);

/// <summary>
/// 把 <see cref="ScanEnvelope"/> 转换为 <c>docs/DATA_PROTOCOL.md</c> 定义的线上形态（snake_case）。
/// 本地信封文件使用 camelCase（见 <see cref="ScoutMindJson"/>），投递到后端前必须经过本转换，
/// 字段值不做任何加工，只改键名。
/// </summary>
public static class ScanProtocolSerializer
{
    /// <summary>把信封写成协议要求的 snake_case JSON 字节。</summary>
    /// <param name="envelope">待转换的信封。</param>
    /// <returns>UTF-8 编码的协议报文。</returns>
    public static byte[] ToProtocolJson(ScanEnvelope envelope)
    {
        ArgumentNullException.ThrowIfNull(envelope);
        using var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(buffer, new JsonWriterOptions
        {
            Indented = false,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        }))
        {
            writer.WriteStartObject();
            writer.WriteString("schema_version", envelope.SchemaVersion);
            writer.WriteString("source", envelope.Source);
            writer.WriteString("reader_version", envelope.ReaderVersion);

            writer.WritePropertyName("game");
            writer.WriteStartObject();
            writer.WriteString("version", envelope.Game.Version);
            writer.WriteString("build", envelope.Game.Build);
            writer.WriteString("app_id", envelope.Game.AppId);
            writer.WriteEndObject();

            writer.WritePropertyName("scan");
            writer.WriteStartObject();
            writer.WriteString("scan_id", envelope.Scan.ScanId);
            writer.WriteString("observed_at", envelope.Scan.ObservedAt);
            writer.WriteString("game_date", envelope.Scan.GameDate);
            writer.WriteString("user_club_uid", envelope.Scan.UserClubUid);
            writer.WriteEndObject();

            writer.WritePropertyName("coverage");
            writer.WriteStartObject();
            foreach (var (key, value) in envelope.Coverage)
            {
                writer.WriteBoolean(key, value);
            }

            writer.WriteEndObject();

            writer.WritePropertyName("warnings");
            writer.WriteStartArray();
            foreach (var warning in envelope.Warnings)
            {
                writer.WriteStringValue(warning);
            }

            writer.WriteEndArray();

            WriteArray(writer, "clubs", envelope.Clubs);
            WriteArray(writer, "players", envelope.Players);
            WriteArray(writer, "transfers", envelope.Transfers);

            writer.WriteEndObject();
        }

        return buffer.ToArray();
    }

    /// <summary>
    /// 判断一个 JSON 根元素是否已经是协议形态（含 <c>schema_version</c> 与 <c>scan</c> 对象）。
    /// 代理据此避免对已经是协议形态的文件重复转换。
    /// </summary>
    /// <param name="root">待检查的 JSON 根元素。</param>
    /// <returns>已经是协议形态时返回 <c>true</c>。</returns>
    public static bool LooksLikeProtocolPayload(JsonElement root) =>
        root.ValueKind == JsonValueKind.Object
        && root.TryGetProperty("schema_version", out _)
        && root.TryGetProperty("scan", out var scan)
        && scan.ValueKind == JsonValueKind.Object;

    private static void WriteArray(Utf8JsonWriter writer, string propertyName, IReadOnlyList<JsonElement> elements)
    {
        writer.WritePropertyName(propertyName);
        writer.WriteStartArray();
        foreach (var element in elements)
        {
            element.WriteTo(writer);
        }

        writer.WriteEndArray();
    }
}
