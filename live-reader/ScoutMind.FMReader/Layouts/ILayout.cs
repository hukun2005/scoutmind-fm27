namespace ScoutMind.FMReader.Layouts;

/// <summary>一个偏移字段的验证状态。只有在真实存档上核对过才允许 <see cref="Verified"/>。</summary>
public enum FieldStatus
{
    /// <summary>不知道是否正确（未核对）。</summary>
    Unknown,

    /// <summary>结构上自洽，但没有真实值锚定。</summary>
    Candidate,

    /// <summary>与游戏内界面核对一致。</summary>
    Verified,

    /// <summary>核对不上，必须拒绝。</summary>
    Rejected,

    /// <summary>当前布局没有对应字段（例如租借关系）。</summary>
    NotSupported,
}

/// <summary>单个字段的验证记录。</summary>
/// <param name="Field">字段名（与布局属性同名，例如 <c>PLAO_CA</c>）。</param>
/// <param name="Status">状态。</param>
/// <param name="Evidence">证据（谁、怎么核对的）。</param>
/// <param name="Note">补充说明。</param>
public sealed record FieldVerification(string Field, FieldStatus Status, string? Evidence = null, string? Note = null);

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
