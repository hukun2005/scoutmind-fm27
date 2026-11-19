using System.Text.Json;

namespace ScoutMind.FMReader.Integration;

/// <summary>
/// 属性键 → <c>PLAO_ATTRS</c> 内偏移。数据来自嵌入的 <c>upstream-attributes.json</c>（由后端
/// <c>ATTRIBUTE_MAP</c> 生成），保证读取器与后端不出现两套映射。
/// </summary>
public static class AttributeMap
{
    private static readonly Lazy<IReadOnlyDictionary<string, int>> Cache = new(Load);

    /// <summary>全部属性。</summary>
    public static IReadOnlyDictionary<string, int> All => Cache.Value;

    /// <summary>取某个属性的偏移；不存在时返回 <c>false</c>。</summary>
    /// <param name="key">属性键，例如 <c>Finishing</c>。</param>
    /// <param name="offset">偏移。</param>
    /// <returns>存在时为 <c>true</c>。</returns>
    public static bool TryGet(string key, out int offset)
    {
        if (Cache.Value.TryGetValue(key, out var found))
        {
            offset = found;
            return true;
        }

        offset = -1;
        return false;
    }

    private static IReadOnlyDictionary<string, int> Load()
    {
        var assembly = typeof(AttributeMap).Assembly;
        var name = assembly.GetManifestResourceNames()
            .FirstOrDefault(item => item.EndsWith("upstream-attributes.json", StringComparison.Ordinal));
        if (name is null)
        {
            return new Dictionary<string, int>(StringComparer.Ordinal);
        }

        using var stream = assembly.GetManifestResourceStream(name);
        if (stream is null)
        {
            return new Dictionary<string, int>(StringComparer.Ordinal);
        }

        using var document = JsonDocument.Parse(stream);
        var allowed = new HashSet<string>(StringComparer.Ordinal);
        if (document.RootElement.TryGetProperty("attributes", out var attributes)
            && attributes.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in attributes.EnumerateObject())
            {
                allowed.Add(property.Name);
            }
        }

        // 偏移来源是上游 Fields.PlayerAttrs（属性块内的字节偏移），JSON 只用来限定"哪些键被映射"。
        var result = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var (key, offset) in FMSuperScout.Fields.PlayerAttrs)
        {
            if (allowed.Count == 0 || allowed.Contains(key))
            {
                result[key] = offset;
            }
        }

        return result;
    }
}
