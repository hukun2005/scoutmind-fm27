using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>一行的匹配结果（用于诊断 33 条未匹配记录）。</summary>
public enum MatchOutcome
{
    /// <summary>按「姓名 + 出生年」配对成功。</summary>
    Matched,

    /// <summary>同一出生年存在，但姓名不同（可能是改名/译名/姓名偏移读错）。</summary>
    NameMismatch,

    /// <summary>同名存在，但出生年不同（重名或出生日期偏移读错）。</summary>
    BirthMismatch,

    /// <summary>读到的出生年为 0（无法作为键）。</summary>
    MissingBirth,

    /// <summary>导出里同名同出生年的记录不止一条（身份冲突）。</summary>
    Duplicate,

    /// <summary>两边都没有可配对的线索（姓名与出生年都对不上）。</summary>
    OnlyOneSide,

    /// <summary>其他原因（姓名不可读、导出记录缺字段等）。</summary>
    Other,
}

/// <summary>一条未匹配记录的诊断细节。</summary>
/// <param name="Outcome">分类。</param>
/// <param name="Name">读取到的姓名。</param>
/// <param name="BirthYear">读取到的出生年。</param>
/// <param name="Detail">证据。</param>
public sealed record MatchDiagnostic(MatchOutcome Outcome, string? Name, int BirthYear, string Detail);

/// <summary>匹配诊断汇总。</summary>
/// <param name="Sampled">抽样数。</param>
/// <param name="Matched">配对成功数。</param>
/// <param name="Unmatched">未配对明细。</param>
/// <param name="ReferenceSize">参照数据规模（按姓名+出生年的唯一键数）。</param>
public sealed record MatchReport(
    int Sampled,
    int Matched,
    IReadOnlyList<MatchDiagnostic> Unmatched,
    int ReferenceSize)
{
    /// <summary>按分类计数。</summary>
    /// <returns>分类 → 数量。</returns>
    public IReadOnlyDictionary<MatchOutcome, int> Counts =>
        Unmatched.GroupBy(item => item.Outcome).ToDictionary(group => group.Key, group => group.Count());
}

/// <summary>
/// 未匹配记录的分类器。规则是"只分类、不猜测"：不删除记录、不强行配对。
/// </summary>
public static class MatchDiagnostics
{
    /// <summary>一条读取到的球员。</summary>
    /// <param name="Name">姓名。</param>
    /// <param name="BirthYear">出生年（0 = 读不到）。</param>
    /// <param name="Female">是否女子数据库的球员（<c>PERO_GENDER</c> 的 0x10 位）。</param>
    public sealed record ReaderRow(string? Name, int BirthYear, bool Female = false);

    /// <summary>参照数据（FMSuperScout 导出）。</summary>
    public sealed class Reference
    {
        private readonly Dictionary<string, List<int>> _byName = new(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<int, List<string>> _byBirth = new();
        private readonly HashSet<string> _keys = new(StringComparer.Ordinal);

        /// <summary>唯一键数量。</summary>
        public int Size => _keys.Count;

        /// <summary>加入一条参照记录。</summary>
        /// <param name="name">姓名。</param>
        /// <param name="birthYear">出生年。</param>
        public void Add(string name, int birthYear)
        {
            if (string.IsNullOrWhiteSpace(name))
            {
                return;
            }

            var key = $"{name}|{birthYear}";
            if (_keys.Add(key))
            {
                if (!_byName.TryGetValue(name, out var years))
                {
                    years = new List<int>();
                    _byName[name] = years;
                }

                years.Add(birthYear);
            }

            if (birthYear > 0)
            {
                if (!_byBirth.TryGetValue(birthYear, out var names))
                {
                    names = new List<string>();
                    _byBirth[birthYear] = names;
                }

                names.Add(name);
            }
        }

        /// <summary>是否存在「姓名 + 出生年」这一条。</summary>
        /// <param name="name">姓名。</param>
        /// <param name="birthYear">出生年。</param>
        /// <returns>存在时为 <c>true</c>。</returns>
        public bool Has(string name, int birthYear) => _keys.Contains($"{name}|{birthYear}");

        /// <summary>同名记录的出生年。</summary>
        /// <param name="name">姓名。</param>
        /// <returns>出生年列表。</returns>
        public IReadOnlyList<int> YearsFor(string name) =>
            _byName.TryGetValue(name, out var years) ? years : Array.Empty<int>();

        /// <summary>同一出生年的姓名。</summary>
        /// <param name="birthYear">出生年。</param>
        /// <returns>姓名列表。</returns>
        public IReadOnlyList<string> NamesFor(int birthYear) =>
            _byBirth.TryGetValue(birthYear, out var names) ? names : Array.Empty<string>();
    }

    /// <summary>对一条读取记录分类。</summary>
    /// <param name="row">读取到的球员。</param>
    /// <param name="reference">参照数据。</param>
    /// <returns>诊断。</returns>
    public static MatchDiagnostic Classify(ReaderRow row, Reference reference)
    {
        ArgumentNullException.ThrowIfNull(reference);

        if (string.IsNullOrWhiteSpace(row.Name))
        {
            return new MatchDiagnostic(MatchOutcome.Other, row.Name, row.BirthYear,
                "姓名读取为空：可能是姓名偏移不匹配，或该对象不是球员");
        }

        if (row.BirthYear == 0)
        {
            return new MatchDiagnostic(MatchOutcome.MissingBirth, row.Name, 0,
                "出生年解码为 0：无法用「姓名+出生年」配对（不是删除，也不是强行匹配）");
        }

        if (reference.Has(row.Name, row.BirthYear))
        {
            return new MatchDiagnostic(MatchOutcome.Matched, row.Name, row.BirthYear, string.Empty);
        }

        // 参照导出只含一个性别的数据库（上游按“数据库选择”跳过另一半），
        // 因此女球员在导出里根本不存在——这是"一侧不存在"，不是姓名读错。
        if (row.Female)
        {
            return new MatchDiagnostic(MatchOutcome.OnlyOneSide, row.Name, row.BirthYear,
                "女球员（女子数据库）：参照导出只包含男子数据库（上游按性别过滤），所以导出里没有这条记录");
        }

        var sameName = reference.YearsFor(row.Name);
        if (sameName.Count > 1)
        {
            return new MatchDiagnostic(MatchOutcome.Duplicate, row.Name, row.BirthYear,
                $"导出中同名球员有 {sameName.Count} 条（出生年 {string.Join("/", sameName)}），身份无法唯一确定");
        }

        if (sameName.Count == 1)
        {
            return new MatchDiagnostic(MatchOutcome.BirthMismatch, row.Name, row.BirthYear,
                $"同名球员在导出中的出生年是 {sameName[0]}，读取值是 {row.BirthYear}");
        }

        var sameBirth = reference.NamesFor(row.BirthYear);
        if (sameBirth.Count > 0)
        {
            return new MatchDiagnostic(MatchOutcome.NameMismatch, row.Name, row.BirthYear,
                $"同出生年（{row.BirthYear}）在导出中有 {sameBirth.Count} 人，但姓名都不匹配（示例：{string.Join("、", sameBirth.Take(3))}）");
        }

        return new MatchDiagnostic(MatchOutcome.OnlyOneSide, row.Name, row.BirthYear,
            "导出中既没有同名记录，也没有同出生年记录：可能该球员不在导出范围内（青年队/自由身/新建球员）");
    }

    /// <summary>生成汇总。</summary>
    /// <param name="rows">读取到的球员。</param>
    /// <param name="reference">参照数据。</param>
    /// <returns>报告。</returns>
    public static MatchReport Summarize(IEnumerable<ReaderRow> rows, Reference reference)
    {
        ArgumentNullException.ThrowIfNull(rows);
        ArgumentNullException.ThrowIfNull(reference);

        var all = rows.ToList();
        var diagnostics = all.Select(row => Classify(row, reference)).ToList();
        return new MatchReport(
            Sampled: all.Count,
            Matched: diagnostics.Count(item => item.Outcome == MatchOutcome.Matched),
            Unmatched: diagnostics.Where(item => item.Outcome != MatchOutcome.Matched).ToList(),
            ReferenceSize: reference.Size);
    }
}
