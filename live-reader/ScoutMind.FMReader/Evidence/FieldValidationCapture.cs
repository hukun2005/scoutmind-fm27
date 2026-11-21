using System.Globalization;
using System.Text;
using System.Text.Json;

namespace ScoutMind.FMReader.Evidence;

/// <summary>一条字段验证采样（SM-057）；真实与模拟证据必须可区分。</summary>
public sealed record FieldValidationCapture(
    string FieldId,
    string PlayerInstanceUid,
    string ObjectType,
    string RawMemoryValue,
    string ExpectedGameValue,
    string GameBuild,
    string PluginVersion,
    string LayoutVersion,
    string GameDate,
    string ObservedAt,
    string EvidenceSource,
    string ValidationStatus,
    bool Simulated);

/// <summary>采样仓库：按 (field, player, observedAt) 去重，保留原始值并支持 JSON/CSV。</summary>
public sealed class FieldValidationCaptureStore
{
    private readonly List<FieldValidationCapture> _items = new();
    private readonly HashSet<string> _keys = new(StringComparer.Ordinal);

    /// <summary>已保存的采样数。</summary>
    public int Count => _items.Count;

    /// <summary>全部采样（只读）。</summary>
    public IReadOnlyList<FieldValidationCapture> Items => _items;

    /// <summary>添加一条采样；同一球员同一观测时间同一字段只计一次。</summary>
    public bool Add(FieldValidationCapture capture)
    {
        ArgumentNullException.ThrowIfNull(capture);
        var key = $"{capture.FieldId}|{capture.PlayerInstanceUid}|{capture.ObservedAt}";
        if (!_keys.Add(key))
        {
            return false;
        }

        _items.Add(capture);
        return true;
    }

    /// <summary>JSON 导出（保留全部字段）。</summary>
    public string ToJson() => JsonSerializer.Serialize(_items, new JsonSerializerOptions { WriteIndented = true });

    /// <summary>CSV 导出，列顺序固定，便于离线复核。</summary>
    public string ToCsv()
    {
        var builder = new StringBuilder();
        builder.AppendLine("FieldId,PlayerInstanceUID,ObjectType,RawMemoryValue,ExpectedGameValue,GameBuild,PluginVersion,LayoutVersion,GameDate,ObservedAt,EvidenceSource,ValidationStatus,Simulated");
        foreach (var item in _items)
        {
            builder.AppendLine(string.Join(',', new[]
            {
                item.FieldId, item.PlayerInstanceUid, item.ObjectType, item.RawMemoryValue, item.ExpectedGameValue,
                item.GameBuild, item.PluginVersion, item.LayoutVersion, item.GameDate, item.ObservedAt,
                item.EvidenceSource, item.ValidationStatus, item.Simulated ? "true" : "false",
            }.Select(Escape)));
        }

        return builder.ToString();
    }

    private static string Escape(string value)
    {
        if (!value.Contains(',') && !value.Contains('"') && !value.Contains('\n'))
        {
            return value;
        }

        return '"' + value.Replace("\"", "\"\"", StringComparison.Ordinal) + '"';
    }
}
