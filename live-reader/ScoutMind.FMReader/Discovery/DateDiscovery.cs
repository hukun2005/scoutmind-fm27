using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一个日期候选：在某段可读内存里出现了与期望日期相同的 FM 编码。</summary>
/// <param name="Index">候选序号（从 1 开始）。</param>
/// <param name="Address">候选地址；只允许出现在本地诊断里。</param>
/// <param name="RegionStart">所属可读区域起始地址。</param>
/// <param name="RawValue">原始 u32。</param>
public sealed record DateCandidate(int Index, ulong Address, ulong RegionStart, uint RawValue);

/// <summary>
/// 一次日期候选发现的结果。注意：命中只能证明"内存里存在这个编码"，不能证明它就是当前游戏日期；
/// 必须跨多个独立游戏日期比对同一地址才能升级为 Verified。
/// </summary>
/// <param name="ExpectedDate">人工提供的游戏内日期。</param>
/// <param name="EncodedValue">FM 日期编码（年 &lt;&lt; 16 | 年内序日）。</param>
/// <param name="Candidates">命中的候选。</param>
/// <param name="RegionsExamined">实际扫描的可读区域数。</param>
/// <param name="BytesScanned">实际扫描字节数。</param>
/// <param name="Truncated">是否因预算/候选上限提前停止。</param>
/// <param name="Diagnostics">诊断说明。</param>
public sealed record DateDiscoveryResult(
    string ExpectedDate,
    uint EncodedValue,
    IReadOnlyList<DateCandidate> Candidates,
    int RegionsExamined,
    long BytesScanned,
    bool Truncated,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 只读日期候选发现：在有限预算内扫描可读内存，寻找与人工提供的游戏内日期一致的 FM 日期编码。
///
/// 它不假设任何偏移，不读取"看起来像日期"的任意整数：只有与期望日期逐位相等的 u32 才会成为候选，
/// 候选地址只用于本地多日期比对，不会进入上传报文。
/// </summary>
public static class DateDiscovery
{
    /// <summary>单次最多保留的候选数。</summary>
    public const int MaxCandidates = 64;

    /// <summary>每次读取的区块大小。</summary>
    public const int BlockSize = 1 << 20;

    /// <summary>默认最大扫描字节数（512 MiB）。</summary>
    public const long DefaultMaxBytes = 512L * 1024 * 1024;

    /// <summary>默认时间预算。</summary>
    public static readonly TimeSpan DefaultBudget = TimeSpan.FromSeconds(20);

    /// <summary>把日期编码为 FM 格式：高 16 位年、低 9 位年内序日。</summary>
    /// <param name="date">日期。</param>
    /// <returns>u32 编码。</returns>
    public static uint Encode(DateOnly date) => ((uint)date.Year << 16) | (uint)date.DayOfYear;

    /// <summary>解码 FM 日期；非法时为 <c>null</c>。</summary>
    /// <param name="raw">原始 u32。</param>
    /// <returns>日期或 <c>null</c>。</returns>
    public static DateOnly? Decode(uint raw)
    {
        var year = (int)(raw >> 16);
        var dayOfYear = (int)(raw & 0x1FF);
        if (year is < 1990 or > 2100 || dayOfYear < 1 || dayOfYear > 366)
        {
            return null;
        }

        var candidate = new DateOnly(year, 1, 1).AddDays(dayOfYear - 1);
        return candidate.Year == year ? candidate : null;
    }

    /// <summary>在可读内存里寻找与期望日期一致的编码。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="expected">人工确认的游戏内日期。</param>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>发现结果。</returns>
    public static DateDiscoveryResult Discover(
        IMemorySource memory,
        DateOnly expected,
        long maxBytes = DefaultMaxBytes,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);

        var diagnostics = new List<string>();
        var candidates = new List<DateCandidate>();
        var encoded = Encode(expected);
        var limit = maxBytes <= 0 ? DefaultMaxBytes : maxBytes;
        var deadline = DateTime.UtcNow + (budget ?? DefaultBudget);
        var regions = memory.Regions ?? Array.Empty<MemoryRegion>();
        if (regions.Count == 0)
        {
            diagnostics.Add("内存源没有提供可读区域：无法执行候选发现。");
            return new DateDiscoveryResult(
                expected.ToString("yyyy-MM-dd"), encoded, candidates, 0, 0, true, diagnostics);
        }

        var buffer = new byte[BlockSize];
        long scanned = 0;
        var examined = 0;
        var truncated = false;
        foreach (var region in regions)
        {
            if (truncated || scanned >= limit)
            {
                truncated = true;
                break;
            }

            if (region.Size == 0)
            {
                continue;
            }

            examined++;
            ulong offset = 0;
            while (offset < region.Size)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    diagnostics.Add("候选发现被取消。");
                    truncated = true;
                    break;
                }

                if (DateTime.UtcNow > deadline || scanned >= limit)
                {
                    diagnostics.Add("达到扫描预算，候选发现提前停止。");
                    truncated = true;
                    break;
                }

                var remaining = Math.Min(region.Size - offset, (ulong)BlockSize);
                var want = (int)Math.Min(remaining, (ulong)Math.Max(0, limit - scanned));
                if (want < 4)
                {
                    truncated = true;
                    break;
                }

                var address = region.Start + offset;
                if (!memory.TryReadBlock(address, buffer, want))
                {
                    diagnostics.Add($"区域 0x{address:X} 不可读，已跳过。");
                    offset += (ulong)want;
                    scanned += want;
                    continue;
                }

                // 结构体字段通常按 4 字节对齐；扫描对齐位置可在同样预算下覆盖更多区域。
                for (var index = 0; index + 4 <= want; index += 4)
                {
                    if (BitConverter.ToUInt32(buffer, index) != encoded)
                    {
                        continue;
                    }

                    if (candidates.Count >= MaxCandidates)
                    {
                        truncated = true;
                        diagnostics.Add($"候选数量超过 {MaxCandidates}，已截断。");
                        break;
                    }

                    candidates.Add(new DateCandidate(
                        candidates.Count + 1,
                        address + (ulong)index,
                        region.Start,
                        encoded));
                }

                offset += (ulong)want;
                scanned += want;
                if (truncated)
                {
                    break;
                }
            }
        }

        if (candidates.Count == 0 && !truncated)
        {
            diagnostics.Add("扫描预算内没有找到与期望日期一致的编码。");
        }

        return new DateDiscoveryResult(
            expected.ToString("yyyy-MM-dd"), encoded, candidates, examined, scanned, truncated, diagnostics);
    }
}
