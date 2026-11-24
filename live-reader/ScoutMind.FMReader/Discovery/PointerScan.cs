using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一条指向目标区间的指针。</summary>
/// <param name="SlotAddress">指针本身所在的地址。</param>
/// <param name="Value">指针值。</param>
/// <param name="InModule">指针是否位于游戏模块（静态/全局数据）内。</param>
public sealed record PointerHit(ulong SlotAddress, ulong Value, bool InModule);

/// <summary>一次指针扫描的结果。</summary>
/// <param name="TargetStart">目标区间起点。</param>
/// <param name="TargetEnd">目标区间终点（不含）。</param>
/// <param name="Hits">命中。</param>
/// <param name="RegionsExamined">扫描的区域数。</param>
/// <param name="BytesScanned">扫描字节数。</param>
/// <param name="Truncated">是否因预算/数量上限提前停止。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record PointerScanResult(
    ulong TargetStart,
    ulong TargetEnd,
    IReadOnlyList<PointerHit> Hits,
    int RegionsExamined,
    long BytesScanned,
    bool Truncated,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 只读指针扫描：在有限预算内寻找“值落在目标区间”的 8 字节指针。
///
/// 用途是找出谁引用了某个堆结构（例如世界状态），从而沿着引用关系向上找到模块静态数据里的根，
/// 得到跨重启稳定的“模块偏移 + 偏移链”。它不猜结构、不写内存，只报告观察到的指针。
/// </summary>
public static class PointerScan
{
    /// <summary>最多保留的命中数。</summary>
    public const int MaxHits = 256;

    /// <summary>每次读取的区块大小。</summary>
    public const int BlockSize = 1 << 20;

    /// <summary>默认最大扫描字节数（2 GiB）。</summary>
    public const long DefaultMaxBytes = 2048L * 1024 * 1024;

    /// <summary>默认时间预算。</summary>
    public static readonly TimeSpan DefaultBudget = TimeSpan.FromSeconds(30);

    /// <summary>扫描指向目标区间的指针。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="targetStart">目标区间起点。</param>
    /// <param name="targetEnd">目标区间终点（不含）。</param>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    public static PointerScanResult Scan(
        IMemorySource memory,
        ulong targetStart,
        ulong targetEnd,
        long maxBytes = DefaultMaxBytes,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);
        if (targetEnd <= targetStart)
        {
            throw new ArgumentException("目标区间终点必须大于起点。", nameof(targetEnd));
        }

        var diagnostics = new List<string>();
        var hits = new List<PointerHit>();
        var limit = maxBytes <= 0 ? DefaultMaxBytes : maxBytes;
        var deadline = DateTime.UtcNow + (budget ?? DefaultBudget);
        var regions = memory.Regions ?? Array.Empty<MemoryRegion>();
        if (regions.Count == 0)
        {
            diagnostics.Add("内存源没有提供可读区域：无法执行指针扫描。");
            return new PointerScanResult(targetStart, targetEnd, hits, 0, 0, true, diagnostics);
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

            if (region.Size < 8)
            {
                continue;
            }

            examined++;
            ulong offset = 0;
            while (offset + 8 <= region.Size)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    diagnostics.Add("指针扫描被取消。");
                    truncated = true;
                    break;
                }

                if (DateTime.UtcNow > deadline || scanned >= limit)
                {
                    diagnostics.Add("达到扫描预算，指针扫描提前停止。");
                    truncated = true;
                    break;
                }

                var want = (int)Math.Min(
                    Math.Min(region.Size - offset, (ulong)BlockSize),
                    (ulong)Math.Max(0, limit - scanned));
                if (want < 8)
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

                for (var index = 0; index + 8 <= want; index += 8)
                {
                    var value = BitConverter.ToUInt64(buffer, index);
                    if (value < targetStart || value >= targetEnd)
                    {
                        continue;
                    }

                    if (hits.Count >= MaxHits)
                    {
                        truncated = true;
                        diagnostics.Add($"指针命中超过 {MaxHits}，已截断。");
                        break;
                    }

                    var slot = address + (ulong)index;
                    hits.Add(new PointerHit(slot, value, memory.InModule(slot)));
                }

                offset += (ulong)want;
                scanned += want;
                if (truncated)
                {
                    break;
                }
            }
        }

        if (hits.Count == 0 && !truncated)
        {
            diagnostics.Add("扫描预算内没有找到指向目标区间的指针。");
        }

        return new PointerScanResult(
            targetStart, targetEnd, hits, examined, scanned, truncated, diagnostics);
    }
}
