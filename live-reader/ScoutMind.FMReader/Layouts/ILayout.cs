namespace ScoutMind.FMReader.Layouts;

/// <summary>
/// 一份 FM 内存布局。ScoutMind 自己持有布局表，不与上游 <c>Fields</c> 混用：
/// 27.0 与 27.1 各自是独立对象，修改其中之一不会影响另一个。
/// </summary>
public interface ILayout
{
    /// <summary>布局名，例如 <c>FM27_0</c>。</summary>
    string Name { get; }

    /// <summary>适配的 FM 主版本。</summary>
    int Major { get; }

    /// <summary>适配的 FM 次版本。</summary>
    int Minor { get; }

    /// <summary>该布局整体状态（各字段状态的最弱值）。</summary>
    FieldStatus Status { get; }

    /// <summary>字段偏移（字段名 → 偏移）。</summary>
    IReadOnlyDictionary<string, uint> Offsets { get; }

    /// <summary>字段验证记录。</summary>
    IReadOnlyDictionary<string, FieldVerification> Fields { get; }

    /// <summary>取偏移；未定义时抛 <see cref="KeyNotFoundException"/>，避免使用 0 当合法偏移。</summary>
    /// <param name="field">字段名。</param>
    /// <returns>偏移。</returns>
    uint this[string field] { get; }

    /// <summary>查询字段状态；未定义字段为 <see cref="FieldStatus.NotSupported"/>。</summary>
    /// <param name="field">字段名。</param>
    /// <returns>验证记录。</returns>
    FieldVerification Verification(string field);

    /// <summary>扫描前必须具备 <see cref="FieldStatus.Verified"/> 的字段。</summary>
    IReadOnlyList<string> RequiredFields { get; }
}
