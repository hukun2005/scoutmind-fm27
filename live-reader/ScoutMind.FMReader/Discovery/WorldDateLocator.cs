using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一处“世界日期”结构命中。</summary>
/// <param name="DateAddress">当前日期字段地址。</param>
/// <param name="BaseAddress">结构基址（日期字段减去固定偏移）。</param>
/// <param name="RawDate">当前日期原始值。</param>
/// <param name="Date">解码后的当前日期。</param>
/// <param name="RawReference">相邻参考日期原始值。</param>
/// <param name="Reference">解码后的参考日期。</param>
public sealed record WorldDateMatch(
    ulong DateAddress,
    ulong BaseAddress,
    uint RawDate,
    string Date,
    uint RawReference,
    string Reference);

/// <summary>一次世界日期定位结果。</summary>
/// <param name="Matches">命中。</param>
/// <param name="BytesScanned">扫描字节数。</param>
/// <param name="Truncated">是否因预算/上限提前停止。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record WorldDateScanResult(
    IReadOnlyList<WorldDateMatch> Matches,
    long BytesScanned,
    bool Truncated,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 按结构签名定位“世界日期”，不依赖绝对地址或指针链。
///
/// 已核实的结构（FM27.1 / build 26620374）在日期字段之后依次是：
/// <c>[当前日期][参考日期][0xFFFFFFFF]</c>，日期字段相对结构基址为 +0x44。
/// 这里要求三个字同时成立：两个合法 FM 日期 + 一个固定哨兵，因此误命中率远低于“任意日期值”。
/// 它仍然只是定位，不是验证：读到的日期必须与游戏内显示一致才算证据。
/// </summary>
public static class WorldDateLocator
{
    /// <summary>日期字段相对结构基址的偏移（已核实）。</summary>
    public const int DateFieldOffset = 0x44;

    /// <summary>参考日期相对日期字段的偏移。</summary>
    public const int ReferenceOffset = 0x4;

    /// <summary>哨兵相对日期字段的偏移。</summary>
    public const int GuardOffset = 0x8;

    /// <summary>哨兵值。</summary>
    public const uint GuardValue = 0xFFFFFFFF;

    /// <summary>紧随哨兵的两个零字段（相对日期字段 +0xC）。</summary>
    public const int ZeroFieldOffset = 0xC;

    /// <summary>最多保留的命中数。</summary>
    public const int MaxMatches = 32;

    /// <summary>每次读取的区块大小。</summary>
    public const int BlockSize = 1 << 20;

    /// <summary>默认最大扫描字节数（2 GiB）。</summary>
    public const long DefaultMaxBytes = 2048L * 1024 * 1024;

    /// <summary>默认时间预算。</summary>
    public static readonly TimeSpan DefaultBudget = TimeSpan.FromSeconds(30);

    /// <summary>扫描世界日期结构。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="maxBytes">最大扫描字节数。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>定位结果。</returns>
    public static WorldDateScanResult Scan(
        IMemorySource memory,
        long maxBytes = DefaultMaxBytes,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);

        var diagnostics = new List<string>();
        var matches = new List<WorldDateMatch>();
        var limit = maxBytes <= 0 ? DefaultMaxBytes : maxBytes;
        var deadline = DateTime.UtcNow + (budget ?? DefaultBudget);
        var regions = memory.Regions ?? Array.Empty<MemoryRegion>();
        if (regions.Count == 0)
        {
            diagnostics.Add("内存源没有提供可读区域：无法定位世界日期。");
            return new WorldDateScanResult(matches, 0, true, diagnostics);
        }

        var buffer = new byte[BlockSize];
        long scanned = 0;
        var truncated = false;
        foreach (var region in regions)
        {
            if (truncated || scanned >= limit)
            {
                truncated = true;
                break;
            }

            if (region.Size < (ulong)(ZeroFieldOffset + 8 + 4))
            {
                continue;
            }

            ulong offset = 0;
            while (offset + (ulong)(GuardOffset + 4) <= region.Size)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    diagnostics.Add("世界日期定位被取消。");
                    truncated = true;
                    break;
                }

                if (DateTime.UtcNow > deadline || scanned >= limit)
                {
                    diagnostics.Add("达到扫描预算，定位提前停止。");
                    truncated = true;
                    break;
                }

                var want = (int)Math.Min(
                    Math.Min(region.Size - offset, (ulong)BlockSize),
                    (ulong)Math.Max(0, limit - scanned));
                if (want < ZeroFieldOffset + 8)
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

                for (var index = 0; index + ZeroFieldOffset + 8 <= want; index += 4)
                {
                    if (BitConverter.ToUInt32(buffer, index + GuardOffset) != GuardValue)
                    {
                        continue;
                    }

                    var raw = BitConverter.ToUInt32(buffer, index);
                    var date = DateDiscovery.Decode(raw);
                    if (date is null || date.Value.Year is < 2000 or > 2060)
                    {
                        continue;
                    }

                    if (BitConverter.ToUInt32(buffer, index + ZeroFieldOffset) != 0
                        || BitConverter.ToUInt32(buffer, index + ZeroFieldOffset + 4) != 0)
                    {
                        continue;
                    }

                    var rawReference = BitConverter.ToUInt32(buffer, index + ReferenceOffset);
                    var reference = DateDiscovery.Decode(rawReference);
                    if (reference is null || reference.Value.Year is < 2000 or > 2060)
                    {
                        continue;
                    }

                    if (matches.Count >= MaxMatches)
                    {
                        truncated = true;
                        diagnostics.Add($"世界日期命中超过 {MaxMatches}，已截断。");
                        break;
                    }

                    var dateAddress = address + (ulong)index;
                    matches.Add(new WorldDateMatch(
                        dateAddress,
                        dateAddress - (ulong)DateFieldOffset,
                        raw,
                        date.Value.ToString("yyyy-MM-dd"),
                        rawReference,
                        reference.Value.ToString("yyyy-MM-dd")));
                }

                offset += (ulong)want;
                scanned += want;
                if (truncated)
                {
                    break;
                }
            }
        }

        if (matches.Count == 0 && !truncated)
        {
            diagnostics.Add("扫描预算内没有找到符合签名的世界日期结构。");
        }

        return new WorldDateScanResult(matches, scanned, truncated, diagnostics);
    }
}

