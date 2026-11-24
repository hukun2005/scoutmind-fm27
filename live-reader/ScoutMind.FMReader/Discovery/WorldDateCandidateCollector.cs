using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一次候选采集结果。</summary>
/// <param name="Observations">结构签名命中的候选（含会被后续淘汰的）。</param>
/// <param name="TotalMatches">签名命中总数。</param>
/// <param name="BytesScanned">扫描字节数。</param>
/// <param name="Truncated">是否因预算/上限提前停止。</param>
/// <param name="Evidences">采集阶段的证据/诊断。</param>
public sealed record WorldDateCandidateCollection(
    IReadOnlyList<DateCandidateObservation> Observations,
    int TotalMatches,
    long BytesScanned,
    bool Truncated,
    IReadOnlyList<string> Evidences);

/// <summary>
/// 采集世界日期候选：复用 <see cref="WorldDateLocator"/> 的结构签名扫描，为每个命中补充
/// 逻辑身份（模块 + 结构指纹）、原始字节、对象类型提示与稳定性复读。
///
/// 采集阶段不做淘汰：所有命中都会进入诊断报告，由 <see cref="DateCandidateTracker"/> 明确分类或排除。
/// </summary>
public static class WorldDateCandidateCollector
{
    /// <summary>每个候选的稳定性复读次数。</summary>
    public const int StabilityReads = 3;

    /// <summary>结构签名文本：日期 + 参考日期 + 哨兵 + 两个零字段。</summary>
    public const string Signature =
        "date@+0x44|reference@+0x48|guard=0xFFFFFFFF@+0x4C|zero@+0x50,0x54";

    /// <summary>采集候选。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="maxBytes">扫描预算。</param>
    /// <param name="hints">对象类型提示；为空表示没有可用的对象分类信息。</param>
    /// <param name="budget">时间预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>采集结果。</returns>
    public static WorldDateCandidateCollection Collect(
        IMemorySource memory,
        long maxBytes = WorldDateLocator.DefaultMaxBytes,
        IReadOnlyList<DateObjectHint>? hints = null,
        TimeSpan? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);

        var scan = WorldDateLocator.Scan(memory, maxBytes, budget, cancellationToken);
        var evidences = new List<string>(scan.Diagnostics);
        var observations = new List<DateCandidateObservation>(scan.Matches.Count);

        foreach (var match in scan.Matches)
        {
            var module = CandidateIdentity.ModuleOf(memory, match.DateAddress);
            var fingerprint = CandidateIdentity.ComputeFingerprint(memory, match.DateAddress, module);
            var hint = FindHint(hints, match.DateAddress, match.BaseAddress);
            var rawBytes = ReadRawBytes(memory, match.DateAddress, match.RawDate, match.RawReference);
            var consistent = CountStableReads(memory, match.DateAddress, match.RawDate);

            observations.Add(new DateCandidateObservation(
                Address: match.DateAddress,
                BaseAddress: match.BaseAddress,
                RegionStart: RegionStartOf(memory, match.DateAddress),
                Module: module,
                RawValue: match.RawDate,
                RawReference: match.RawReference,
                Signature: Signature,
                Source: "world_date_signature_scan",
                StructureFingerprint: fingerprint,
                LogicalSignature: CandidateIdentity.ComputeLogicalSignature(module, fingerprint),
                RelativeAddress: match.DateAddress - match.BaseAddress,
                RelatedObject: hint?.Description,
                StructureEvidence: hint is null
                    ? "结构满足“日期 + 参考日期 + 哨兵 + 两个零字段”；没有可用的对象类型证据。"
                    : $"结构满足日期签名，且被对象分类器标记为 {hint.Kind}（{hint.Description}）。",
                KindHint: hint?.Kind ?? DateCandidateKind.UnknownDate,
                ConsecutiveConsistentReads: consistent,
                RawBytes: rawBytes));
        }

        evidences.Add(
            $"签名命中 {scan.Matches.Count} 条，全部进入候选/淘汰诊断；扫描 {scan.BytesScanned} 字节，截断={scan.Truncated}。");

        return new WorldDateCandidateCollection(
            observations, scan.Matches.Count, scan.BytesScanned, scan.Truncated, evidences);
    }

    private static DateObjectHint? FindHint(
        IReadOnlyList<DateObjectHint>? hints,
        ulong dateAddress,
        ulong baseAddress)
    {
        if (hints is null || hints.Count == 0)
        {
            return null;
        }

        foreach (var hint in hints)
        {
            var window = (ulong)Math.Max(1, hint.Window);
            if (baseAddress >= hint.ObjectAddress && baseAddress < hint.ObjectAddress + window)
            {
                return hint;
            }

            if (dateAddress >= hint.ObjectAddress && dateAddress < hint.ObjectAddress + window)
            {
                return hint;
            }
        }

        return null;
    }

    private static string ReadRawBytes(IMemorySource memory, ulong address, uint raw, uint reference)
    {
        var buffer = new byte[12];
        if (memory.TryReadBlock(address, buffer, buffer.Length))
        {
            return $"0x{BitConverter.ToUInt32(buffer, 0):X8} 0x{BitConverter.ToUInt32(buffer, 4):X8} 0x{BitConverter.ToUInt32(buffer, 8):X8}";
        }

        return $"0x{raw:X8} 0x{reference:X8} 0x{WorldDateLocator.GuardValue:X8}";
    }

    private static int CountStableReads(IMemorySource memory, ulong address, uint expected)
    {
        var consistent = 0;
        for (var attempt = 0; attempt < StabilityReads; attempt++)
        {
            try
            {
                if (memory.UInt32(address) != expected)
                {
                    break;
                }

                consistent++;
            }
            catch (MemoryUnreadableException)
            {
                break;
            }
        }

        return consistent;
    }

    private static ulong RegionStartOf(IMemorySource memory, ulong address)
    {
        var regions = memory.Regions;
        if (regions is null)
        {
            return 0;
        }

        foreach (var region in regions)
        {
            if (address >= region.Start && address < region.Start + region.Size)
            {
                return region.Start;
            }
        }

        return 0;
    }
}
