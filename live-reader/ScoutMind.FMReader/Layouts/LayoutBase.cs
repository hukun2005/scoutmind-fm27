namespace ScoutMind.FMReader.Layouts;

/// <summary>布局表基类：字段偏移 + 每字段验证状态，提供一致的查询与状态汇总。</summary>
public abstract class LayoutBase : ILayout
{
    private readonly Dictionary<string, uint> _offsets;
    private readonly Dictionary<string, FieldVerification> _fields;
    private readonly List<string> _required = new();

    /// <summary>创建布局。</summary>
    /// <param name="name">布局名。</param>
    /// <param name="major">FM 主版本。</param>
    /// <param name="minor">FM 次版本。</param>
    /// <param name="offsets">字段偏移。</param>
    /// <param name="defaultStatus">未显式标注字段的默认状态。</param>
    /// <param name="defaultNote">默认说明。</param>
    protected LayoutBase(
        string name,
        int major,
        int minor,
        IReadOnlyDictionary<string, uint> offsets,
        FieldStatus defaultStatus,
        string defaultNote,
        EvidenceKind defaultKind = EvidenceKind.None)
    {
        Name = name;
        Major = major;
        Minor = minor;
        _offsets = new Dictionary<string, uint>(offsets, StringComparer.Ordinal);
        _fields = new Dictionary<string, FieldVerification>(StringComparer.Ordinal);
        foreach (var field in _offsets.Keys)
        {
            _fields[field] = new FieldVerification(field, defaultStatus, defaultKind, null, defaultNote);
        }
    }

    /// <inheritdoc />
    public string Name { get; }

    /// <inheritdoc />
    public int Major { get; }

    /// <inheritdoc />
    public int Minor { get; }

    /// <inheritdoc />
    public IReadOnlyDictionary<string, uint> Offsets => _offsets;

    /// <inheritdoc />
    public IReadOnlyDictionary<string, FieldVerification> Fields => _fields;

    /// <inheritdoc />
    public IReadOnlyList<string> RequiredFields => _required;

    /// <inheritdoc />
    public uint this[string field] =>
        _offsets.TryGetValue(field, out var offset)
            ? offset
            : throw new KeyNotFoundException($"布局 {Name} 没有字段 {field}；拒绝用 0 作为偏移继续读取。");

    /// <inheritdoc />
    public FieldVerification Verification(string field) =>
        _fields.TryGetValue(field, out var verification)
            ? verification
            : new FieldVerification(field, FieldStatus.NotSupported, EvidenceKind.None, null, $"布局 {Name} 没有该字段");

    /// <summary>各字段状态的最弱值：任一 Rejected → Rejected；全部 Verified → Verified；否则 Candidate/Unknown。</summary>
    public FieldStatus Status
    {
        get
        {
            var statuses = _fields.Values.Select(item => item.Status).ToList();
            if (statuses.Count == 0)
            {
                return FieldStatus.Pending;
            }

            if (statuses.Contains(FieldStatus.Failed))
            {
                return FieldStatus.Failed;
            }

            var supported = statuses.Where(item => item != FieldStatus.NotSupported).ToList();
            if (supported.Count == 0)
            {
                return FieldStatus.NotSupported;
            }

            if (supported.All(item => item == FieldStatus.Verified))
            {
                return FieldStatus.Verified;
            }

            if (supported.All(item => item is FieldStatus.Verified or FieldStatus.Candidate)
                && supported.Any(item => item == FieldStatus.Candidate))
            {
                return FieldStatus.Candidate;
            }

            return FieldStatus.Pending;
        }
    }

    /// <summary>标记字段状态（供验证流程与测试使用；不会写回磁盘文件）。</summary>
    /// <param name="field">字段名。</param>
    /// <param name="status">状态。</param>
    /// <param name="evidence">证据。</param>
    /// <param name="note">说明。</param>
    public void Mark(string field, FieldStatus status, EvidenceKind kind = EvidenceKind.None, string? evidence = null, string? note = null)
    {
        if (!_offsets.ContainsKey(field))
        {
            throw new ArgumentException($"布局 {Name} 没有字段 {field}", nameof(field));
        }

        _fields[field] = new FieldVerification(field, status, kind, evidence, note);
    }

    /// <summary>声明扫描前必须 Verified 的字段。</summary>
    /// <param name="fields">字段名。</param>
    protected void Require(params string[] fields)
    {
        foreach (var field in fields)
        {
            if (!_offsets.ContainsKey(field))
            {
                throw new ArgumentException($"布局 {Name} 没有字段 {field}", nameof(fields));
            }

            _required.Add(field);
        }
    }
}
