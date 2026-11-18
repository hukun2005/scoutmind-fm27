using System.Globalization;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ScoutMind.Contracts;

/// <summary>
/// 进程内统一的 JSON 设置：camelCase 属性名、UTC 时间戳（<c>yyyy-MM-ddTHH:mm:ssZ</c>）、
/// 枚举以字符串输出、中文不转义。所有写出与读入都必须使用同一套设置，避免同一字段出现两种拼写。
/// </summary>
public static class ScoutMindJson
{
    /// <summary>带缩进的设置，用于落盘文件与面向人的输出。</summary>
    public static JsonSerializerOptions Options { get; } = Create(writeIndented: true);

    /// <summary>紧凑设置，用于日志与网络请求体。</summary>
    public static JsonSerializerOptions Compact { get; } = Create(writeIndented: false);

    /// <summary>把 UTC 时间格式化为协议要求的形式，例如 <c>2026-11-18T03:00:00Z</c>。</summary>
    /// <param name="value">待格式化的时间。</param>
    /// <returns>ISO-8601 字符串，小数点后为 0 时省略小数部分。</returns>
    public static string FormatTimestamp(DateTimeOffset value) =>
        value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.FFFFFFF'Z'", CultureInfo.InvariantCulture);

    private static JsonSerializerOptions Create(bool writeIndented)
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web)
        {
            WriteIndented = writeIndented,
            DefaultIgnoreCondition = JsonIgnoreCondition.Never,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };
        options.Converters.Add(new JsonStringEnumConverter());
        options.Converters.Add(new UtcDateTimeOffsetConverter());
        return options;
    }
}

/// <summary>
/// 把 <see cref="DateTimeOffset"/> 读写为 UTC 的 <c>Z</c> 形式。
/// System.Text.Json 默认写出 <c>+00:00</c>，而协议示例使用 <c>Z</c>，两者都合法但需要统一。
/// </summary>
internal sealed class UtcDateTimeOffsetConverter : JsonConverter<DateTimeOffset>
{
    public override DateTimeOffset Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType != JsonTokenType.String)
        {
            throw new JsonException($"时间字段必须是字符串，实际为 {reader.TokenType}。");
        }

        var text = reader.GetString();
        if (string.IsNullOrWhiteSpace(text))
        {
            throw new JsonException("时间字段不能为空字符串。");
        }

        if (!DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var parsed))
        {
            throw new JsonException($"无法解析时间 \"{text}\"，期望 ISO-8601（例如 2026-11-18T03:00:00Z）。");
        }

        return parsed.ToUniversalTime();
    }

    public override void Write(Utf8JsonWriter writer, DateTimeOffset value, JsonSerializerOptions options) =>
        writer.WriteStringValue(ScoutMindJson.FormatTimestamp(value));
}
