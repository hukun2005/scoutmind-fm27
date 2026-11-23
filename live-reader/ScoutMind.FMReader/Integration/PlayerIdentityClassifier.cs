using System.Globalization;

namespace ScoutMind.FMReader.Integration;

/// <summary>上游 <c>id</c> 字段的身份判定结果。</summary>
public enum IdentityStatus
{
    /// <summary>可写入 <c>save_local_uid</c> 的合法 UID。</summary>
    ValidUid,

    /// <summary><c>0xFFFFFFFF</c>（4294967295）或等价的 <c>-1</c>：上游表示“没有身份”。</summary>
    SentinelUid,

    /// <summary>上游没有提供 id。</summary>
    MissingUid,

    /// <summary>存在但不可能作为身份（0、非数字文本、超出范围）。</summary>
    InvalidUid,
}

/// <summary>一次身份判定的原始值与原因，便于写入证据。</summary>
/// <param name="Status">判定结果。</param>
/// <param name="Raw">上游原始 ID 文本（缺失时为 <c>null</c>）。</param>
/// <param name="Reason">稳定的原因码，例如 <c>sentinel_uid</c>。</param>
public readonly record struct IdentityAssessment(IdentityStatus Status, string? Raw, string? Reason)
{
    /// <summary>是否可以当作合法 UID 使用。</summary>
    public bool IsValid => Status == IdentityStatus.ValidUid;

    /// <summary>协议中的身份状态文本。</summary>
    public string StatusText => Status switch
    {
        IdentityStatus.SentinelUid => "sentinel",
        IdentityStatus.MissingUid => "missing",
        _ => "invalid",
    };
}

/// <summary>
/// 上游球员 ID 判定。规则与后端 <c>app.ingestion.uid_status</c> 一致：
/// <c>4294967295</c> 与 <c>-1</c> 是哨兵，不能写进 <c>save_local_uid</c>；<c>0</c> 与非法文本不是身份。
/// </summary>
public static class PlayerIdentityClassifier
{
    /// <summary>上游“没有身份”的哨兵值。</summary>
    public const long SentinelUid = 4294967295L;

    /// <summary>32 位有符号句柄去掉哨兵后的最大合法值。</summary>
    public const long MaxValidUid = 4294967294L;

    /// <summary>按整数判定。</summary>
    /// <param name="raw">上游 ID；缺失为 <c>null</c>。</param>
    /// <returns>判定结果。</returns>
    public static IdentityAssessment Classify(long? raw)
    {
        if (raw is null)
        {
            return new IdentityAssessment(IdentityStatus.MissingUid, null, "missing_uid");
        }

        var value = raw.Value;
        if (value == SentinelUid || value == -1)
        {
            return new IdentityAssessment(IdentityStatus.SentinelUid, Text(value), "sentinel_uid");
        }

        if (value == 0)
        {
            return new IdentityAssessment(IdentityStatus.InvalidUid, Text(value), "zero_uid");
        }

        if (value < 0)
        {
            return new IdentityAssessment(IdentityStatus.SentinelUid, Text(value), "sentinel_uid");
        }

        if (value > MaxValidUid)
        {
            return new IdentityAssessment(IdentityStatus.SentinelUid, Text(value), "sentinel_uid");
        }

        return new IdentityAssessment(IdentityStatus.ValidUid, Text(value), null);
    }

    /// <summary>按文本判定；只接受十进制或 <c>0xFFFFFFFF</c> 形式，其它文本视为非法。</summary>
    /// <param name="raw">上游 ID 文本。</param>
    /// <returns>判定结果。</returns>
    public static IdentityAssessment ClassifyText(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return new IdentityAssessment(IdentityStatus.MissingUid, null, "missing_uid");
        }

        var text = raw.Trim();
        if (string.Equals(text, "0xffffffff", StringComparison.OrdinalIgnoreCase)
            || string.Equals(text, "0xffffffffffffffff", StringComparison.OrdinalIgnoreCase))
        {
            return new IdentityAssessment(IdentityStatus.SentinelUid, text, "sentinel_uid");
        }

        if (long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
        {
            return Classify(value);
        }

        return new IdentityAssessment(IdentityStatus.InvalidUid, text, "non_numeric_uid");
    }

    private static string Text(long value) => value.ToString(CultureInfo.InvariantCulture);
}
