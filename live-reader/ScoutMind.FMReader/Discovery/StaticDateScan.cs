using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一个“模块静态指针 → 堆对象 → 日期字段”的候选路径。</summary>
/// <param name="Slot">模块内指针槽位。</param>
/// <param name="ModuleBase">槽位所在模块的基址。</param>
/// <param name="Rva">槽位相对模块基址的 RVA。</param>
/// <param name="Target">指针指向的堆对象。</param>
/// <param name="Hop">跳数（1 或 2）。</param>
/// <param name="DateOffset">日期字段相对最终对象的偏移。</param>
/// <param name="RawValue">命中的原始日期值。</param>
/// <param name="Date">解码日期。</param>
public sealed record StaticDateRoot(
    ulong Slot,
    ulong ModuleBase,
    ulong Rva,
    ulong Target,
    int Hop,
    int DateOffset,
    uint RawValue,
    string Date);

/// <summary>一次静态根扫描结果。</summary>
/// <param name="Roots">候选路径。</param>
/// <param name="BytesScanned">模块内扫描字节数。</param>
/// <param name="PointersFollowed">跟随的堆指针数。</param>
/// <param name="Truncated">是否触发预算/上限。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record StaticDateScanResult(
    IReadOnlyList<StaticDateRoot> Roots,
    long BytesScanned,
    int PointersFollowed,
    bool Truncated,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 从显式给出的模块区域出发，寻找“模块内指针 → 堆对象 → 日期字段”的路径。
///
/// 模块区域由调用方提供（<see cref="ModuleBounds"/> 解析结果），扫描器不猜基址；
/// 指针落在模块内则跳过（那不是堆引用）。命中仍只是候选，必须在另一个独立日期上复测同一槽位。
/// </summary>
public static class StaticDateScan
{
    /// <summary>每个对象内检查的窗口大小。</summary>
    public const int ObjectWindow = 0x1000;

    /// <summary>第二跳检查指针的窗口大小。</summary>
    public const int PointerWindow = 0x200;

    /// <summary>最多跟随的堆指针数量。</summary>
    public const int MaxPointers = 200_000;

    /// <summary>最多保留的候选路径数。</summary>
    public const int MaxRoots = 128;

    /// <summary>默认模块内扫描预算（512 MiB，足够覆盖 game_plugin 静态数据）。</summary>
    public const long DefaultMaxBytes = 512L * 1024 * 1024;

    /// <summary>默认时间预算。</summary>
    public static readonly TimeSpan DefaultBudget = TimeSpan.FromSeconds(60);

    /// <summary>扫描静态根。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="moduleRegions">模块区域（基址与大小由调用方解析）。</param>
    /// <param name="expected">人工确认的游戏内日期。</param>
    /// <param name="maxDepth">最大跳数（1 或 2）。</param>
    /// <param name="maxBytes">模块内扫描预算。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>扫描结果。</returns>
    public static StaticDateScanResult Scan(
        IMemorySource memory,
        IReadOnlyList<MemoryRegion> moduleRegions,
        DateOnly expected,
        int maxDepth = 2,
        long maxBytes = DefaultMaxBytes,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);
        ArgumentNullException.ThrowIfNull(moduleRegions);

        var diagnostics = new List<string>();
        var roots = new List<StaticDateRoot>();
        var encoded = DateDiscovery.Encode(expected);
        var limit = maxBytes <= 0 ? DefaultMaxBytes : maxBytes;
        var deadline = DateTime.UtcNow + (budget ?? DefaultBudget);
        var depth = Math.Clamp(maxDepth, 1, 2);

        var regions = moduleRegions.Where(item => item.Size >= 8).ToArray();
        if (regions.Length == 0)
        {
            diagnostics.Add("没有提供模块区域：无法执行静态根扫描。");
            return new StaticDateScanResult(roots, 0, 0, true, diagnostics);
        }

        var buffer = new byte[1 << 20];
        long scanned = 0;
        var followed = 0;
        var truncated = false;

        foreach (var region in regions)
        {
            if (truncated || scanned >= limit)
            {
                truncated = true;
                break;
            }

            ulong offset = 0;
            while (offset + 8 <= region.Size)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    diagnostics.Add("静态根扫描被取消。");
                    truncated = true;
                    break;
                }

                if (DateTime.UtcNow > deadline || scanned >= limit || followed >= MaxPointers)
                {
                    diagnostics.Add("达到扫描预算/指针上限，静态根扫描提前停止。");
                    truncated = true;
                    break;
                }

                var want = (int)Math.Min(
                    Math.Min(region.Size - offset, (ulong)buffer.Length),
                    (ulong)Math.Max(0, limit - scanned));
                if (want < 8)
                {
                    truncated = true;
                    break;
                }

                var address = region.Start + offset;
                if (!memory.TryReadBlock(address, buffer, want))
                {
                    offset += (ulong)want;
                    scanned += want;
                    continue;
                }

                for (var index = 0; index + 8 <= want; index += 8)
                {
                    var value = BitConverter.ToUInt64(buffer, index);
                    if (!LooksLikeHeapPointer(memory, value))
                    {
                        continue;
                    }

                    followed++;
                    var slot = address + (ulong)index;
                    if (TryFindFirstHop(slot, region.Start, value, memory, encoded, expected, roots))
                    {
                        truncated = truncated || roots.Count >= MaxRoots;
                        if (truncated)
                        {
                            break;
                        }
                    }

                    if (depth >= 2 && TryFindSecondHop(slot, region.Start, value, memory, encoded, expected, roots))
                    {
                        truncated = truncated || roots.Count >= MaxRoots;
                        if (truncated)
                        {
                            break;
                        }
                    }

                    if (followed >= MaxPointers)
                    {
                        truncated = true;
                        break;
                    }
                }

                offset += (ulong)want;
                scanned += want;
                if (truncated)
                {
                    break;
                }
            }
        }

        if (roots.Count == 0 && !truncated)
        {
            diagnostics.Add("模块内没有找到指向期望日期的指针路径。");
        }

        return new StaticDateScanResult(roots, scanned, followed, truncated, diagnostics);
    }

    private static bool LooksLikeHeapPointer(IMemorySource memory, ulong value) =>
        value > 0x10000 && value < 0x7FFF_FFFF_FFFF && !memory.InModule(value);

    private static bool TryFindFirstHop(
        ulong slot,
        ulong moduleBase,
        ulong target,
        IMemorySource memory,
        uint encoded,
        DateOnly expected,
        List<StaticDateRoot> roots)
    {
        var buffer = new byte[ObjectWindow];
        if (!memory.TryReadBlock(target, buffer, buffer.Length))
        {
            return false;
        }

        for (var index = 0; index + 4 <= buffer.Length; index += 4)
        {
            if (BitConverter.ToUInt32(buffer, index) != encoded)
            {
                continue;
            }

            if (roots.Count >= MaxRoots)
            {
                return true;
            }

            roots.Add(new StaticDateRoot(
                slot, moduleBase, slot - moduleBase, target, 1, index, encoded,
                expected.ToString("yyyy-MM-dd")));
            return true;
        }

        return false;
    }

    private static bool TryFindSecondHop(
        ulong slot,
        ulong moduleBase,
        ulong target,
        IMemorySource memory,
        uint encoded,
        DateOnly expected,
        List<StaticDateRoot> roots)
    {
        var buffer = new byte[PointerWindow];
        if (!memory.TryReadBlock(target, buffer, buffer.Length))
        {
            return false;
        }

        for (var index = 0; index + 8 <= buffer.Length; index += 8)
        {
            var value = BitConverter.ToUInt64(buffer, index);
            if (!LooksLikeHeapPointer(memory, value))
            {
                continue;
            }

            var inner = new byte[ObjectWindow];
            if (!memory.TryReadBlock(value, inner, inner.Length))
            {
                continue;
            }

            for (var position = 0; position + 4 <= inner.Length; position += 4)
            {
                if (BitConverter.ToUInt32(inner, position) != encoded)
                {
                    continue;
                }

                if (roots.Count >= MaxRoots)
                {
                    return true;
                }

                roots.Add(new StaticDateRoot(
                    slot, moduleBase, slot - moduleBase, value, 2, position, encoded,
                    expected.ToString("yyyy-MM-dd")));
                return true;
            }
        }

        return false;
    }
}
