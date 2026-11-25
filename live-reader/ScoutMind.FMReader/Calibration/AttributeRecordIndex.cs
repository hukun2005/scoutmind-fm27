namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 属性记录关联用的只读索引（一次调用内有效）。
///
/// 只预计算姓名键与归一化俱乐部，不缓存内存指针，也不跨进程/存档复用；
/// 索引生命周期等于持有它的那一次诊断或审计调用。
/// </summary>
public sealed class AttributeRecordIndex
{
    internal sealed record Entry(
        PlayerRecordFacts Facts,
        IReadOnlySet<string> NameKeys,
        string? NormalizedClub);

    private readonly Entry[] _entries;

    private AttributeRecordIndex(Entry[] entries)
    {
        _entries = entries;
    }

    /// <summary>索引中的记录数。</summary>
    public int Count => _entries.Length;

    internal IReadOnlyList<Entry> Entries => _entries;

    /// <summary>从只读快照构建索引。</summary>
    /// <param name="records">属性记录快照。</param>
    /// <returns>可复用的只读索引。</returns>
    public static AttributeRecordIndex Build(IReadOnlyList<PlayerRecordFacts> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var entries = new Entry[records.Count];
        for (var index = 0; index < records.Count; index++)
        {
            var facts = records[index];
            entries[index] = new Entry(
                facts,
                AttributeRecordLinker.NameKeys(facts.FirstName, facts.SecondName, facts.CommonName),
                string.IsNullOrWhiteSpace(facts.ClubName)
                    ? null
                    : AttributeRecordLinker.Normalize(facts.ClubName!));
        }

        return new AttributeRecordIndex(entries);
    }
}
