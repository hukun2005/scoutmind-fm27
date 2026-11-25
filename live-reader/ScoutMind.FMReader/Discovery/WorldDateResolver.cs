using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一条世界日期候选。</summary>
/// <param name="DateAddress">日期字段地址。</param>
/// <param name="RawDate">原始日期值。</param>
/// <param name="Date">解码日期。</param>
/// <param name="RawReference">参考日期原始值。</param>
/// <param name="Reference">参考日期。</param>
/// <param name="ReferenceGapDays">参考日期与当前日期的间隔天数。</param>
public sealed record WorldDateCandidate(
    ulong DateAddress,
    uint RawDate,
    string Date,
    uint RawReference,
    string Reference,
    int ReferenceGapDays);

/// <summary>
/// 世界日期解析结果。`Confidence` 只表达证据等级，不会自行升级为 Verified：
/// `heuristic` 表示“签名 + 最新日期 + 稳定性”三个条件同时成立，仍必须与游戏界面或跨日期观测比对。
/// </summary>
/// <param name="Status">`ok` / `ambiguous` / `not_found` / `unstable`。</param>
/// <param name="Date">解析出的日期（仅 ok 时有值）。</param>
/// <param name="Confidence">`heuristic` 或空。</param>
/// <param name="Candidates">参与判定的候选。</param>
/// <param name="TotalMatches">签名命中总数。</param>
/// <param name="Reason">未解析成功的原因。</param>
/// <param name="Diagnostics">诊断。</param>
public sealed record WorldDateResolution(
    string Status,
    string? Date,
    string? Confidence,
    IReadOnlyList<WorldDateCandidate> Candidates,
    int TotalMatches,
    string? Reason,
    IReadOnlyList<string> Diagnostics);

/// <summary>
/// 启发式世界日期解析：
///
/// 1. 用 <see cref="WorldDateLocator"/> 找“日期 + 参考日期 + 0xFFFFFFFF + 两个 0”的结构；
/// 2. 只保留日期在 2000..2060、参考日期晚于当前日期且间隔 30..400 天的记录；
/// 3. 取日期最新的一条；若同一天存在多条，返回 ambiguous；
/// 4. 对选中字段连续读取三次，值不一致返回 unstable。
///
/// 这些条件都不是“证明”，只是把误识别压到可接受范围；真实可信度仍由跨日期/跨重启观测决定。
/// </summary>
public static class WorldDateResolver
{
    /// <summary>参考日期与当前日期的合理间隔下界（天）。</summary>
    public const int MinReferenceGapDays = 30;

    /// <summary>参考日期与当前日期的合理间隔上界（天）。</summary>
    public const int MaxReferenceGapDays = 400;

    /// <summary>稳定性复读次数。</summary>
    public const int StabilityReads = 3;

    /// <summary>解析当前世界日期。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="maxBytes">签名扫描预算。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>解析结果。</returns>
    public static WorldDateResolution Resolve(
        IMemorySource memory,
        long maxBytes = WorldDateLocator.DefaultMaxBytes,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(memory);
        var diagnostics = new List<string>();
        var scan = WorldDateLocator.Scan(memory, maxBytes, null, cancellationToken);
        diagnostics.AddRange(scan.Diagnostics);

        var candidates = new List<WorldDateCandidate>();
        foreach (var match in scan.Matches)
        {
            if (!DateOnly.TryParseExact(match.Date, "yyyy-MM-dd", out var date))
            {
                continue;
            }

            if (!DateOnly.TryParseExact(match.Reference, "yyyy-MM-dd", out var reference))
            {
                continue;
            }

            var gap = reference.DayNumber - date.DayNumber;
            if (gap is < MinReferenceGapDays or > MaxReferenceGapDays)
            {
                continue;
            }

            candidates.Add(new WorldDateCandidate(
                match.DateAddress, match.RawDate, match.Date, match.RawReference, match.Reference, gap));
        }

        if (candidates.Count == 0)
        {
            return new WorldDateResolution(
                "not_found", null, null, candidates, scan.Matches.Count,
                "没有满足“日期 + 参考日期（30..400 天）+ 哨兵 + 零字段”的候选。", diagnostics);
        }

        var latest = candidates.Max(item => item.Date);
        var top = candidates.Where(item => item.Date == latest).ToList();
        if (top.Count > 1)
        {
            diagnostics.Add($"最新日期 {latest} 同时出现在 {top.Count} 条记录中。");
            return new WorldDateResolution(
                "ambiguous", latest, "heuristic", top, scan.Matches.Count,
                "同一天存在多条结构相同的记录，无法唯一确定。", diagnostics);
        }

        var chosen = top[0];
        for (var attempt = 0; attempt < StabilityReads; attempt++)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return new WorldDateResolution(
                    "unstable", null, null, top, scan.Matches.Count, "解析被取消。", diagnostics);
            }

            if (attempt > 0)
            {
                Thread.Sleep(50);
            }

            uint raw;
            try
            {
                raw = memory.UInt32(chosen.DateAddress);
            }
            catch (MemoryUnreadableException)
            {
                return new WorldDateResolution(
                    "unstable", null, null, top, scan.Matches.Count,
                    "复读时候选地址不可读（进程可能已退出）。", diagnostics);
            }

            if (raw != chosen.RawDate)
            {
                return new WorldDateResolution(
                    "unstable", null, null, top, scan.Matches.Count,
                    $"复读值不一致：0x{chosen.RawDate:X8} → 0x{raw:X8}。", diagnostics);
            }
        }

        diagnostics.Add($"签名命中 {scan.Matches.Count} 条，通过过滤 {candidates.Count} 条，最新日期 {latest}。");
        return new WorldDateResolution(
            "ok", latest, "heuristic", top, scan.Matches.Count, null, diagnostics);
    }
}
