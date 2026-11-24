using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>
/// 自动快照安全门判定。只有读取器明确给出 <c>snapshot.allowed=true</c> 且状态为 <c>ENABLED</c> 时才允许导入。
/// 解析失败、字段缺失、日期为空、状态不是 ENABLED 一律视为 BLOCKED。
/// </summary>
/// <param name="Allowed">是否允许。</param>
/// <param name="Status"><c>ENABLED</c> 或 <c>BLOCKED</c>。</param>
/// <param name="Reasons">原因。</param>
/// <param name="Date">读取器给出的日期。</param>
public sealed record SnapshotGate(
    bool Allowed,
    string Status,
    IReadOnlyList<string> Reasons,
    string? Date)
{
    /// <summary>构造 BLOCKED 判定。</summary>
    /// <param name="reasons">原因。</param>
    /// <returns>判定。</returns>
    public static SnapshotGate Blocked(params string[] reasons) =>
        new(false, "BLOCKED", reasons, null);
}

/// <summary>
/// 解析读取器 <c>world-date --diagnostics --json</c> 的安全门结果。
/// 这里不重新判断日期，只信任读取器给出的 <c>snapshot</c> 结论，避免代理层自行放宽条件。
/// </summary>
public static class ReaderSnapshotGate
{
    /// <summary>解析读取器输出。</summary>
    /// <param name="json">读取器 stdout。</param>
    /// <returns>判定。</returns>
    public static SnapshotGate Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return SnapshotGate.Blocked("读取器没有输出日期诊断。");
        }

        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("snapshot", out var snapshot)
                || snapshot.ValueKind != JsonValueKind.Object)
            {
                return SnapshotGate.Blocked("读取器输出缺少 snapshot 判定。");
            }

            var status = snapshot.TryGetProperty("status", out var statusElement)
                ? statusElement.GetString()
                : null;
            var allowed = snapshot.TryGetProperty("allowed", out var allowedElement)
                && allowedElement.ValueKind == JsonValueKind.True;

            var reasons = new List<string>();
            if (snapshot.TryGetProperty("reasons", out var reasonsElement)
                && reasonsElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in reasonsElement.EnumerateArray())
                {
                    var text = item.GetString();
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        reasons.Add(text);
                    }
                }
            }

            var date = root.TryGetProperty("date_summary", out var summary)
                && summary.ValueKind == JsonValueKind.Object
                && summary.TryGetProperty("selected_date", out var dateElement)
                && dateElement.ValueKind == JsonValueKind.String
                    ? dateElement.GetString()
                    : null;

            if (!allowed || !string.Equals(status, "ENABLED", StringComparison.Ordinal))
            {
                return new SnapshotGate(false, "BLOCKED", reasons.Count > 0 ? reasons : new[] { "日期未达到安全门要求。" }, date);
            }

            if (string.IsNullOrWhiteSpace(date))
            {
                return SnapshotGate.Blocked("安全门声称允许，但没有给出日期：按 BLOCKED 处理。");
            }

            return new SnapshotGate(true, "ENABLED", Array.Empty<string>(), date);
        }
        catch (JsonException)
        {
            return SnapshotGate.Blocked("读取器日期诊断不是可解析的 JSON。");
        }
    }
}
