using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>合同日期诊断（SM-012）：把"日期异常"拆成可解释的类别，而不是一个 29%。</summary>
public enum ContractDateCategory
{
    /// <summary>原始值为 0：没有合同到期日（按未知处理）。</summary>
    Unset,

    /// <summary>年份 1900（FM 的占位纪元）：没有到期日，不是读取失败。</summary>
    NoExpiry,

    /// <summary>原始值全 1：未初始化/哨兵值。</summary>
    Sentinel,

    /// <summary>能解出年份与序日，且在合理范围内。</summary>
    Decodable,

    /// <summary>能解出年份，但年份超出 1900..2100。</summary>
    OutOfRange,

    /// <summary>能解出日期，但年份不在 FM 合同应有的 2000..2060（多半是偏移读到了别的字段）。</summary>
    UnexpectedYear,

    /// <summary>低 9 位序日非法（0 或 >366）。</summary>
    BadDayOfYear,
}

/// <summary>一条合同日期样本的诊断结果。</summary>
/// <param name="RawValue">原始 u32。</param>
/// <param name="Year">解码年份（0 表示解不出）。</param>
/// <param name="DayOfYear">解码序日（0 表示非法）。</param>
/// <param name="Category">分类。</param>
/// <param name="Reason">中文说明。</param>
public sealed record ContractDateSample(uint RawValue, int Year, int DayOfYear, ContractDateCategory Category, string Reason);

/// <summary>按类别汇总的合同日期统计，用于诊断报告。</summary>
public sealed class ContractDateDiagnostics
{
    private readonly Dictionary<ContractDateCategory, int> _counts = new();
    private readonly List<ContractDateSample> _samples = new();

    /// <summary>记录一条原始值。</summary>
    /// <param name="raw">合同到期日的原始 u32。</param>
    public void Add(uint raw)
    {
        var sample = Analyze(raw);
        _counts[sample.Category] = _counts.GetValueOrDefault(sample.Category) + 1;
        if (_samples.Count < 8)
        {
            _samples.Add(sample);
        }
    }

    /// <summary>总样本数。</summary>
    public int Total => _counts.Values.Sum();

    /// <summary>某类别的计数。</summary>
    /// <param name="category">类别。</param>
    /// <returns>计数。</returns>
    public int Count(ContractDateCategory category) => _counts.GetValueOrDefault(category);

    /// <summary>可解码比例（不含未设置/哨兵）。</summary>
    public double DecodableRatio
    {
        get
        {
            var applicable = Total - Count(ContractDateCategory.Unset) - Count(ContractDateCategory.Sentinel)
                - Count(ContractDateCategory.NoExpiry);
            return applicable <= 0 ? 0 : (double)Count(ContractDateCategory.Decodable) / applicable;
        }
    }

    /// <summary>报告里的一行摘要。</summary>
    public string Summary =>
        string.Join("，", new[]
        {
            $"可解码 {Count(ContractDateCategory.Decodable)}",
            $"序日非法 {Count(ContractDateCategory.BadDayOfYear)}",
            $"年份越界 {Count(ContractDateCategory.OutOfRange)}",
            $"年份异常 {Count(ContractDateCategory.UnexpectedYear)}",
            $"无到期日(1900) {Count(ContractDateCategory.NoExpiry)}",
            $"未设置 {Count(ContractDateCategory.Unset)}",
            $"哨兵值 {Count(ContractDateCategory.Sentinel)}",
        });

    /// <summary>最多 8 条样本，便于定位具体偏移/对象。</summary>
    public IReadOnlyList<ContractDateSample> Samples => _samples;

    /// <summary>原始值与转换结果的紧凑文本，供诊断报告记录。</summary>
    public string RawSamples =>
        string.Join("；", _samples.Select(item =>
            $"0x{item.RawValue:X8} -> y{item.Year} d{item.DayOfYear} [{item.Category}]"));

    /// <summary>分析一个原始值。</summary>
    /// <param name="raw">原始 u32。</param>
    /// <returns>分类结果。</returns>
    public static ContractDateSample Analyze(uint raw)
    {
        if (raw == 0)
        {
            return new ContractDateSample(raw, 0, 0, ContractDateCategory.Unset, "原始值为 0：没有到期日");
        }

        if (raw == uint.MaxValue)
        {
            return new ContractDateSample(raw, 0, 0, ContractDateCategory.Sentinel, "原始值全 1：未初始化/哨兵");
        }

        var year = (int)(raw >> 16);
        var doy = (int)(raw & 0x1FF);
        if (year == 1900)
        {
            // FM 用 1900 纪元表示"没有到期日"：这是空合同，不是解析失败，必须排除出分母。
            return new ContractDateSample(raw, year, doy, ContractDateCategory.NoExpiry,
                "年份 1900 是 FM 的占位纪元：没有到期日（按空合同排除）");
        }

        if (doy is < 1 or > 366)
        {
            return new ContractDateSample(raw, year, doy, ContractDateCategory.BadDayOfYear, $"序日 {doy} 超出 1..366");
        }

        if (year is < 1900 or > 2100)
        {
            return new ContractDateSample(raw, year, doy, ContractDateCategory.OutOfRange, $"年份 {year} 超出 1900..2100");
        }

        if (year is < 2000 or > 2060)
        {
            return new ContractDateSample(raw, year, doy, ContractDateCategory.UnexpectedYear,
                $"日期可解码但年份 {year} 不在合同应有的 2000..2060（疑似偏移读到了别的字段）");
        }

        return new ContractDateSample(raw, year, doy, ContractDateCategory.Decodable, $"可解码：{year}-{doy}");
    }
}
