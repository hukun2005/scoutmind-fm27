using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>参与引用链扫描的模块区域。<see cref="Base"/> 是模块加载基址，RVA 相对它计算。</summary>
/// <param name="Name">模块标识（<c>gp</c> = game_plugin，<c>ga</c> = GameAssembly）。</param>
/// <param name="Base">模块基址（随 ASLR 变化）。</param>
/// <param name="Start">区域起始地址。</param>
/// <param name="Size">区域字节数。</param>
public sealed record ModuleRegion(string Name, ulong Base, ulong Start, ulong Size);

/// <summary>
/// 一条“模块静态指针 → 若干层指针 → 日期字段”的引用链。
///
/// 链只记录相对模块基址的 RVA 与固定偏移，因此游戏重启（ASLR、堆重新分配）后仍可重新解析到同一逻辑对象；
/// 它描述的是当前进程内的可达关系，本身不证明该对象就是世界日期，必须与人工界面日期比对后才算验证。
/// </summary>
/// <param name="Module">模块标识。</param>
/// <param name="Rva">模块内静态指针槽位的 RVA。</param>
/// <param name="PointerOffsets">中间各层指针相对当前对象的偏移。</param>
/// <param name="DateOffset">最终对象内日期字段的偏移。</param>
public sealed record ReferenceChain(
    string Module,
    ulong Rva,
    IReadOnlyList<int> PointerOffsets,
    int DateOffset)
{
    /// <summary>链的跳数：每层指针一次跳转，最后落到日期字段。</summary>
    public int Level => PointerOffsets.Count + 1;

    /// <summary>跨会话稳定的链签名（只含模块标识、RVA 与固定偏移）。</summary>
    public string Signature
    {
        get
        {
            var builder = new System.Text.StringBuilder();
            builder.Append("chain:").Append(Module).Append(":0x").Append(Rva.ToString("X"));
            foreach (var offset in PointerOffsets)
            {
                builder.Append(":0x").Append(offset.ToString("X"));
            }

            builder.Append(":date+0x").Append(DateOffset.ToString("X"));
            return builder.ToString();
        }
    }

    /// <summary>人类可读的偏移链，例如 <c>static+0x5CE040 → +0x30 → date+0x44</c>。</summary>
    /// <returns>文本。</returns>
    public string Describe()
    {
        var builder = new System.Text.StringBuilder();
        builder.Append("static+0x").Append(Rva.ToString("X"));
        foreach (var offset in PointerOffsets)
        {
            builder.Append(" → +0x").Append(offset.ToString("X"));
        }

        builder.Append(" → date+0x").Append(DateOffset.ToString("X"));
        return builder.ToString();
    }
}

/// <summary>引用链扫描的目标（一个日期字段地址及其原始值）。</summary>
/// <param name="DateAddress">日期字段地址。</param>
/// <param name="RawValue">该地址当前原始值。</param>
public sealed record ReferenceChainTarget(ulong DateAddress, uint RawValue);

/// <summary>一条通过复核的引用链。</summary>
/// <param name="Chain">引用链。</param>
/// <param name="DateAddress">链解析到的日期字段地址。</param>
/// <param name="RawValue">该地址的原始值。</param>
public sealed record ReferenceChainCandidate(ReferenceChain Chain, ulong DateAddress, uint RawValue);

/// <summary>一次引用链扫描结果。</summary>
/// <param name="Candidates">通过复核的引用链。</param>
/// <param name="BytesScanned">模块内扫描字节数。</param>
/// <param name="SlotsExamined">检查过的指针槽位数。</param>
/// <param name="Truncated">是否因预算/上限提前停止。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record ReferenceChainDiscovery(
    IReadOnlyList<ReferenceChainCandidate> Candidates,
    long BytesScanned,
    int SlotsExamined,
    bool Truncated,
    IReadOnlyList<string> Diagnostics);

/// <summary>引用链解析结果。</summary>
/// <param name="Resolved">是否解析成功。</param>
/// <param name="Status"><c>resolved</c> / <c>module_missing</c> / <c>slot_out_of_module</c> / <c>unreadable</c> / <c>invalid_pointer</c> / <c>structure_mismatch</c>。</param>
/// <param name="DateAddress">解析到的日期字段地址（失败时为 0 或最后已知地址）。</param>
/// <param name="RawValue">读到的原始值。</param>
/// <param name="Date">解码日期。</param>
/// <param name="Detail">说明。</param>
public sealed record ReferenceChainResolution(
    bool Resolved,
    string Status,
    ulong DateAddress,
    uint RawValue,
    string? Date,
    string Detail);

/// <summary>
/// 引用链解析：从“模块 RVA + 固定偏移”重新走一遍指针，读出日期字段。
/// 只读、不猜结构；解析结果必须通过世界日期哨兵校验才算成功。
/// </summary>
public static class ReferenceChainResolver
{
    /// <summary>解析一条引用链。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="modules">当前进程的模块区域。</param>
    /// <param name="chain">引用链。</param>
    /// <returns>解析结果。</returns>
    public static ReferenceChainResolution Resolve(
        IMemorySource memory,
        IReadOnlyList<ModuleRegion> modules,
        ReferenceChain chain)
    {
        ArgumentNullException.ThrowIfNull(memory);
        ArgumentNullException.ThrowIfNull(modules);
        ArgumentNullException.ThrowIfNull(chain);

        ModuleRegion? module = null;
        foreach (var candidate in modules)
        {
            if (string.Equals(candidate.Name, chain.Module, StringComparison.Ordinal))
            {
                module = candidate;
                break;
            }
        }

        if (module is null)
        {
            return Failed("module_missing", 0, $"引用链的模块 {chain.Module} 不在当前模块边界内。");
        }

        var slot = module.Base + chain.Rva;
        if (slot < module.Start || slot - module.Start + 8 > module.Size)
        {
            return Failed("slot_out_of_module", 0, $"静态槽位 0x{slot:X} 不在模块 0x{module.Start:X}..0x{module.Start + module.Size:X} 内。");
        }

        var buffer = new byte[8];
        if (!memory.TryReadBlock(slot, buffer, buffer.Length))
        {
            return Failed("unreadable", 0, $"静态槽位 0x{slot:X} 不可读。");
        }

        var current = BitConverter.ToUInt64(buffer, 0);
        foreach (var offset in chain.PointerOffsets)
        {
            if (offset < 0 || !PlausiblePointer(current))
            {
                return Failed("invalid_pointer", current, $"指针 0x{current:X} 或偏移 0x{offset:X} 非法。");
            }

            var next = current + (ulong)offset;
            if (!memory.TryReadBlock(next, buffer, buffer.Length))
            {
                return Failed("unreadable", next, $"指针 0x{next:X} 不可读。");
            }

            current = BitConverter.ToUInt64(buffer, 0);
        }

        if (chain.DateOffset < 0 || !PlausiblePointer(current))
        {
            return Failed("invalid_pointer", current, $"最终对象 0x{current:X} 或日期偏移 0x{chain.DateOffset:X} 非法。");
        }

        var dateAddress = current + (ulong)chain.DateOffset;
        var structure = new byte[12];
        if (!memory.TryReadBlock(dateAddress, structure, structure.Length))
        {
            return Failed("unreadable", dateAddress, $"日期字段 0x{dateAddress:X} 不可读。");
        }

        var raw = BitConverter.ToUInt32(structure, 0);
        if (BitConverter.ToUInt32(structure, WorldDateLocator.GuardOffset) != WorldDateLocator.GuardValue)
        {
            return Failed("structure_mismatch", dateAddress, $"0x{dateAddress:X} 不满足世界日期结构（哨兵不成立）。");
        }

        var decoded = DateDiscovery.Decode(raw);
        if (decoded is null)
        {
            return Failed("structure_mismatch", dateAddress, $"0x{dateAddress:X} 的原始值 0x{raw:X8} 不是合法 FM 日期。");
        }

        return new ReferenceChainResolution(
            true,
            "resolved",
            dateAddress,
            raw,
            decoded.Value.ToString("yyyy-MM-dd"),
            $"引用链 {chain.Describe()} 解析到 0x{dateAddress:X}。");
    }

    private static bool PlausiblePointer(ulong value) => value > 0x10000 && value < 0x0000_8000_0000_0000;

    private static ReferenceChainResolution Failed(string status, ulong address, string detail) =>
        new(false, status, address, 0, null, detail);
}

/// <summary>
/// 反向引用链发现：在模块区域内寻找“指向目标日期字段附近”的静态指针，并可选跟随一层堆指针。
///
/// 一次模块扫描即可覆盖全部目标；只有能重新解析并回到同一地址、且通过世界日期哨兵校验的链才会被保留。
/// </summary>
public static class ReferenceChainFinder
{
    /// <summary>目标日期字段相对所属对象的合理偏移上限。</summary>
    public const int MaxObjectOffset = 0x1000;

    /// <summary>第二跳检查的指针窗口大小。</summary>
    public const int SecondHopWindow = 0x200;

    /// <summary>单次扫描最多处理的目标数。</summary>
    public const int MaxTargets = 512;

    /// <summary>最多保留的第二跳对象数。</summary>
    public const int MaxFirstHopObjects = 8192;

    /// <summary>最多保留的引用链数。</summary>
    public const int MaxCandidates = 64;

    /// <summary>默认模块内扫描预算（1 GiB）。</summary>
    public const long DefaultMaxBytes = 1024L * 1024 * 1024;

    /// <summary>默认时间预算。</summary>
    public static readonly TimeSpan DefaultBudget = TimeSpan.FromSeconds(45);

    /// <summary>发现引用链。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="targets">目标日期字段。</param>
    /// <param name="moduleRegions">模块区域。</param>
    /// <param name="maxDepth">最大跳数（1 或 2）。</param>
    /// <param name="maxBytes">模块内扫描预算。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>发现结果。</returns>
    public static ReferenceChainDiscovery Discover(
        IMemorySource memory,
        IReadOnlyList<ReferenceChainTarget> targets,
        IReadOnlyList<ModuleRegion> moduleRegions,
        int maxDepth = 2,
        long maxBytes = DefaultMaxBytes,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);
        ArgumentNullException.ThrowIfNull(targets);
        ArgumentNullException.ThrowIfNull(moduleRegions);

        var diagnostics = new List<string>();
        var candidates = new List<ReferenceChainCandidate>();
        if (targets.Count == 0 || moduleRegions.Count == 0)
        {
            diagnostics.Add("没有目标或模块区域：跳过引用链扫描。");
            return new ReferenceChainDiscovery(candidates, 0, 0, false, diagnostics);
        }

        var byBase = BuildTargetMap(targets, diagnostics);
        var depth = Math.Clamp(maxDepth, 1, 2);
        var limit = maxBytes <= 0 ? DefaultMaxBytes : maxBytes;
        var deadline = DateTime.UtcNow + (budget ?? DefaultBudget);
        var buffer = new byte[1 << 20];
        var seenChains = new HashSet<string>(StringComparer.Ordinal);
        var parents = new Dictionary<ulong, List<(string Module, ulong Rva)>>();
        long scanned = 0;
        var slots = 0;
        var truncated = false;
        var parentsFull = false;

        foreach (var region in moduleRegions)
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

            ulong offsetInRegion = 0;
            while (offsetInRegion + 8 <= region.Size)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    diagnostics.Add("引用链扫描被取消。");
                    truncated = true;
                    break;
                }

                if (DateTime.UtcNow > deadline || scanned >= limit)
                {
                    diagnostics.Add("达到扫描预算，引用链扫描提前停止。");
                    truncated = true;
                    break;
                }

                var want = (int)Math.Min(
                    Math.Min(region.Size - offsetInRegion, (ulong)buffer.Length),
                    (ulong)Math.Max(0, limit - scanned));
                if (want < 8)
                {
                    truncated = true;
                    break;
                }

                var address = region.Start + offsetInRegion;
                if (!memory.TryReadBlock(address, buffer, want))
                {
                    offsetInRegion += (ulong)want;
                    scanned += want;
                    continue;
                }

                for (var index = 0; index + 8 <= want; index += 8)
                {
                    var value = BitConverter.ToUInt64(buffer, index);
                    if (value <= 0x10000 || memory.InModule(value))
                    {
                        continue;
                    }

                    slots++;
                    var slot = address + (ulong)index;
                    var rva = slot >= region.Base ? slot - region.Base : 0;
                    if (byBase.TryGetValue(value, out var matches))
                    {
                        foreach (var match in matches)
                        {
                            TryAccept(
                                memory,
                                moduleRegions,
                                new ReferenceChain(region.Name, rva, Array.Empty<int>(), match.DateOffset),
                                match.DateAddress,
                                match.RawValue,
                                candidates,
                                seenChains);
                        }
                    }

                    if (depth >= 2 && !parents.ContainsKey(value))
                    {
                        if (parents.Count >= MaxFirstHopObjects)
                        {
                            if (!parentsFull)
                            {
                                parentsFull = true;
                                diagnostics.Add($"第一跳对象超过 {MaxFirstHopObjects} 个，后续模块指针未参与两跳扫描。");
                            }

                            continue;
                        }

                        parents[value] = new List<(string, ulong)> { (region.Name, rva) };
                    }
                }

                offsetInRegion += (ulong)want;
                scanned += want;
                if (truncated)
                {
                    break;
                }
            }
        }

        if (depth >= 2)
        {
            foreach (var (firstHop, slotsOfObject) in parents)
            {
                if (candidates.Count >= MaxCandidates)
                {
                    truncated = true;
                    break;
                }

                var window = new byte[SecondHopWindow];
                if (!memory.TryReadBlock(firstHop, window, window.Length))
                {
                    continue;
                }

                for (var index = 0; index + 8 <= window.Length; index += 8)
                {
                    var pointer = BitConverter.ToUInt64(window, index);
                    if (pointer <= 0x10000 || memory.InModule(pointer))
                    {
                        continue;
                    }

                    if (!byBase.TryGetValue(pointer, out var matches))
                    {
                        continue;
                    }

                    foreach (var parent in slotsOfObject)
                    {
                        foreach (var match in matches)
                        {
                            TryAccept(
                                memory,
                                moduleRegions,
                                new ReferenceChain(parent.Module, parent.Rva, new[] { index }, match.DateOffset),
                                match.DateAddress,
                                match.RawValue,
                                candidates,
                                seenChains);
                        }
                    }
                }
            }
        }

        if (candidates.Count == 0 && !truncated)
        {
            diagnostics.Add("模块内没有找到能解析回目标日期的引用链。");
        }

        return new ReferenceChainDiscovery(candidates, scanned, slots, truncated, diagnostics);
    }

    private static Dictionary<ulong, List<(ulong DateAddress, uint RawValue, int DateOffset)>> BuildTargetMap(
        IReadOnlyList<ReferenceChainTarget> targets,
        List<string> diagnostics)
    {
        var byBase = new Dictionary<ulong, List<(ulong, uint, int)>>();
        var limited = 0;
        foreach (var target in targets)
        {
            if (limited >= MaxTargets)
            {
                diagnostics.Add($"引用链目标超过 {MaxTargets} 条，其余目标未参与引用链扫描。");
                break;
            }

            limited++;
            for (var offset = 0; offset <= MaxObjectOffset; offset += 4)
            {
                if (target.DateAddress < (ulong)offset)
                {
                    break;
                }

                var baseAddress = target.DateAddress - (ulong)offset;
                // 同一基址只保留“最近”的日期字段：静态指针指向的对象若有多个日期结构，
                // 第一个才是该对象自身的日期；更远的偏移会跨到相邻对象，属于伪链，直接丢弃。
                if (!byBase.TryGetValue(baseAddress, out var existing) || offset < existing[0].Item3)
                {
                    byBase[baseAddress] = new List<(ulong, uint, int)>
                    {
                        (target.DateAddress, target.RawValue, offset),
                    };
                }
            }
        }

        return byBase;
    }

    private static void TryAccept(
        IMemorySource memory,
        IReadOnlyList<ModuleRegion> modules,
        ReferenceChain chain,
        ulong dateAddress,
        uint rawValue,
        List<ReferenceChainCandidate> candidates,
        HashSet<string> seenChains)
    {
        if (candidates.Count >= MaxCandidates)
        {
            return;
        }

        var resolution = ReferenceChainResolver.Resolve(memory, modules, chain);
        if (!resolution.Resolved
            || resolution.DateAddress != dateAddress
            || resolution.RawValue != rawValue)
        {
            return;
        }

        var key = chain.Signature + "@0x" + dateAddress.ToString("X");
        if (!seenChains.Add(key))
        {
            return;
        }

        candidates.Add(new ReferenceChainCandidate(chain, dateAddress, rawValue));
    }
}
