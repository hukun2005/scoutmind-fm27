using System.Globalization;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一次追踪判定的结果。</summary>
/// <param name="Status">
/// <c>unavailable</c> / <c>ambiguous</c> / <c>unstable</c> / <c>heuristic</c> /
/// <c>verification_mismatch</c> / <c>date_rollback</c> / <c>session_verified</c> / <c>restart_verified</c>。
/// </param>
/// <param name="Confidence">可信度等级。</param>
/// <param name="SelectedDate">选中的日期。</param>
/// <param name="SelectedSignature">选中候选的逻辑签名。</param>
/// <param name="Candidates">参与判定的候选（未排除）。</param>
/// <param name="RejectedCandidates">被明确排除的候选。</param>
/// <param name="SelectionReason">选择/失败原因。</param>
/// <param name="Evidence">本轮证据。</param>
/// <param name="Limitations">限制说明。</param>
/// <param name="State">更新后的持久化状态。</param>
/// <param name="DateChanged">界面日期相对上次确认是否发生变化。</param>
/// <param name="DateRolledBack">界面日期是否倒退。</param>
public sealed record DateTrackingResult(
    string Status,
    DateConfidenceLevel Confidence,
    string? SelectedDate,
    string? SelectedSignature,
    IReadOnlyList<DateCandidateDiagnostics> Candidates,
    IReadOnlyList<DateCandidateDiagnostics> RejectedCandidates,
    string? SelectionReason,
    IReadOnlyList<string> Evidence,
    IReadOnlyList<string> Limitations,
    DateVerificationState State,
    bool DateChanged,
    bool DateRolledBack);

/// <summary>
/// 日期候选关联追踪：
///
/// 1. 以“模块 + 结构指纹”作为逻辑身份，绝对地址只作为当前会话的诊断值；
/// 2. 每次读取都累计读取次数、连续一致次数、观测日期与进程会话；
/// 3. 疑义（同签名多命中、复读不一致、界面日期不匹配）只降级，不升级；
/// 4. 只有人工提供的界面日期与该候选一致时，才允许 <c>session_verified</c>；
/// 5. 只有同一逻辑身份在足够多的独立进程会话里都通过验证，才允许 <c>restart_verified</c>。
///
/// 本类不读取系统时间当作游戏日期，也不把“最大日期”直接当成当前日期。
/// </summary>
public static class DateCandidateTracker
{
    /// <summary>升级为 <c>restart_verified</c> 所需的独立进程会话数（首次 + 至少两次重启）。</summary>
    public const int RequiredVerifiedSessionsForRestart = 3;

    /// <summary>一个候选最少需要的稳定复读次数。</summary>
    public const int RequiredConsistentReads = 3;

    /// <summary>持久化时最多保留的候选状态数。</summary>
    public const int MaxPersistedCandidates = 1024;

    /// <summary>执行一次追踪判定。</summary>
    /// <param name="session">当前进程会话。</param>
    /// <param name="saveKey">存档身份；未知为 <c>null</c>。</param>
    /// <param name="operatorVisibleDate">人工观察到的游戏界面日期；未提供为 <c>null</c>。</param>
    /// <param name="collection">采集结果。</param>
    /// <param name="previous">上一次的持久化状态。</param>
    /// <param name="now">当前时间。</param>
    /// <returns>追踪结果。</returns>
    public static DateTrackingResult Observe(
        ProcessSessionIdentity session,
        string? saveKey,
        DateOnly? operatorVisibleDate,
        WorldDateCandidateCollection collection,
        DateVerificationState previous,
        DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(collection);
        ArgumentNullException.ThrowIfNull(previous);

        var nowText = now.UtcDateTime.ToString("O");
        var evidence = new List<string>();
        var limitations = new List<string>
        {
            "候选结构只证明内存中存在该日期编码，不能单独证明它就是当前游戏日期。",
        };

        if (!string.IsNullOrEmpty(previous.LastSessionKey)
            && !string.Equals(previous.LastSessionKey, session.SessionKey, StringComparison.Ordinal))
        {
            evidence.Add($"检测到新的游戏进程会话（{previous.LastSessionKey} → {session.SessionKey}）：重新扫描，不复用旧绝对地址。");
        }

        var buildChanged = !string.IsNullOrEmpty(previous.Build)
            && !string.Equals(previous.Build, session.Build, StringComparison.Ordinal);
        if (buildChanged)
        {
            evidence.Add($"游戏构建号变化（{previous.Build} → {session.Build}）：既有验证证据不再适用于新构建。");
            limitations.Add("构建号变化后必须重新做界面日期验证，不能沿用旧构建的验证结论。");
        }

        var previousCandidates = buildChanged
            ? new Dictionary<string, TrackedCandidateState>(StringComparer.Ordinal)
            : BuildPreviousLookup(previous.Candidates);

        var visible = operatorVisibleDate?.ToString("yyyy-MM-dd");
        var rolledBack = operatorVisibleDate is not null
            && previous.LastConfirmedDate is not null
            && !buildChanged
            && DateOnly.TryParseExact(
                previous.LastConfirmedDate,
                "yyyy-MM-dd",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var lastConfirmed)
            && operatorVisibleDate.Value < lastConfirmed;
        var dateChanged = visible is not null
            && previous.LastConfirmedDate is not null
            && !string.Equals(visible, previous.LastConfirmedDate, StringComparison.Ordinal);

        var entries = new List<Entry>(collection.Observations.Count);
        foreach (var observation in collection.Observations)
        {
            var decoded = DateDiscovery.Decode(observation.RawValue);
            var reference = DateDiscovery.Decode(observation.RawReference);
            var gap = decoded is not null && reference is not null
                ? reference.Value.DayNumber - decoded.Value.DayNumber
                : int.MinValue;
            var state = UpdateState(previousCandidates, observation, decoded?.ToString("yyyy-MM-dd"), session, nowText);
            entries.Add(new Entry(observation, state, decoded, reference, gap));
        }

        // 结构层面的排除：非法值、超范围、对象类型、复读不稳定。
        foreach (var entry in entries)
        {
            var structural = DecideStructuralRejection(entry);
            if (structural is not null)
            {
                entry.Rejection = structural.Value.Reason;
                entry.Detail = structural.Value.Detail;
            }
        }

        // 同结构重复：若有且只有一条能由模块静态引用链解析，则保留它，其余按“无引用链证据”排除；
        // 否则同签名多命中无法唯一确定，全部排除（不是随便挑一个）。
        foreach (var group in entries
                     .Where(item => item.Rejection == DateRejectionReason.None)
                     .GroupBy(item => item.Observation.LogicalSignature, StringComparer.Ordinal)
                     .Where(group => group.Count() > 1))
        {
            var chained = group.Where(item => item.Observation.ReferenceChain is not null).ToList();
            if (chained.Count == 1)
            {
                foreach (var entry in group)
                {
                    if (ReferenceEquals(entry, chained[0]))
                    {
                        continue;
                    }

                    entry.Rejection = DateRejectionReason.InsufficientEvidence;
                    entry.Detail =
                        $"同结构（{group.Key}）命中 {group.Count()} 次；只有 0x{chained[0].Observation.Address:X} 能由模块静态引用链解析，其余记录没有引用链证据。";
                }

                evidence.Add(
                    $"同结构重复 {group.Count()} 条：引用链唯一定位到 0x{chained[0].Observation.Address:X}（{chained[0].Observation.ReferenceChain!.Signature}）。");
                continue;
            }

            foreach (var entry in group)
            {
                entry.Rejection = DateRejectionReason.DuplicateSignature;
                entry.Detail = $"逻辑签名 {group.Key} 命中 {group.Count()} 次，无法唯一确定。";
            }
        }

        // 与人工界面日期的关系：未来事件排除，过去的记录证据不足。
        var verificationDate = operatorVisibleDate;
        if (verificationDate is not null && !rolledBack)
        {
            foreach (var entry in entries.Where(item => item.Rejection == DateRejectionReason.None && item.Date is not null))
            {
                if (entry.Date > verificationDate)
                {
                    entry.Rejection = DateRejectionReason.FutureEvent;
                    entry.Detail = $"日期 {entry.DateText} 晚于界面确认的当前日期 {visible}。";
                }
                else if (entry.Date < verificationDate)
                {
                    entry.Rejection = DateRejectionReason.InsufficientEvidence;
                    entry.Detail = $"日期 {entry.DateText} 早于界面确认的当前日期 {visible}，缺少能证明其为当前日期的证据。";
                }
            }
        }

        var (status, selected, reason, level) = Select(entries, visible, rolledBack, previous);
        if (selected is not null && visible is not null)
        {
            if (selected.Observation.ReferenceChain is { } selectedChain)
            {
                evidence.Add(
                    $"候选身份由模块静态引用链确定：{selectedChain.Signature}（{selectedChain.Describe()}）。");
            }

            var sessions = ApplyVerification(selected, session, evidence);
            if (sessions >= RequiredVerifiedSessionsForRestart)
            {
                status = "restart_verified";
                level = DateConfidenceLevel.RestartVerified;
                evidence.Add($"同一逻辑签名已在 {sessions} 个独立进程会话中通过界面日期验证：允许标记 restart_verified。");
            }
            else
            {
                status = "session_verified";
                level = DateConfidenceLevel.SessionVerified;
                evidence.Add($"界面日期 {visible} 与候选一致（进程会话 {session.SessionKey}，已验证会话 {sessions}/{RequiredVerifiedSessionsForRestart}）。");
            }
        }

        if (visible is not null && selected is null && !rolledBack)
        {
            if (status == "verification_mismatch")
            {
                evidence.Add($"界面日期 {visible} 没有匹配到唯一候选：不写入确认日期。");
            }
            else if (status == "ambiguous")
            {
                limitations.Add("存在无法区分的候选，自动快照必须保持关闭。");
            }
        }

        // 未选中的合理候选必须写明排除原因，禁止静默丢弃。
        foreach (var entry in entries.Where(item => item.Rejection == DateRejectionReason.None))
        {
            if (ReferenceEquals(entry, selected))
            {
                continue;
            }

            entry.Rejection = DateRejectionReason.InsufficientEvidence;
            entry.Detail = visible is null
                ? $"日期 {entry.DateText} 结构合理，但缺少能证明其为当前日期的证据。"
                : $"日期 {entry.DateText} 未通过界面日期唯一匹配。";
        }

        foreach (var entry in entries)
        {
            entry.Confidence = ReferenceEquals(entry, selected)
                ? level
                : DateConfidenceLevel.Discovered;
            entry.Kind = ReferenceEquals(entry, selected) && visible is not null
                ? DateCandidateKind.CurrentWorldDate
                : entry.Observation.KindHint;
        }

        var candidates = entries
            .Where(item => item.Rejection == DateRejectionReason.None)
            .Select((item, index) => ToDiagnostic(index + 1, item))
            .ToList();
        var rejected = entries
            .Where(item => item.Rejection != DateRejectionReason.None)
            .Select((item, index) => ToDiagnostic(index + 1, item))
            .ToList();

        var tracked = entries.Select(item => item.State).ToList();
        var updatedState = BuildState(
            previous,
            session,
            saveKey,
            selected is not null ? visible : null,
            selected?.DateText ?? null,
            selected?.Observation.IdentitySignature,
            tracked,
            evidence,
            nowText);

        return new DateTrackingResult(
            status,
            level,
            selected?.DateText,
            selected?.Observation.LogicalSignature,
            candidates,
            rejected,
            reason,
            evidence,
            limitations,
            updatedState,
            dateChanged,
            rolledBack);
    }

    private static (string Status, Entry? Selected, string? Reason, DateConfidenceLevel Level) Select(
        IReadOnlyList<Entry> entries,
        string? visible,
        bool rolledBack,
        DateVerificationState previous)
    {
        if (rolledBack)
        {
            return ("date_rollback", null,
                $"界面日期早于上次确认日期 {previous.LastConfirmedDate}：视为日期倒退，拒绝升级。",
                DateConfidenceLevel.VerificationPending);
        }

        var eligible = entries.Where(item => item.Rejection == DateRejectionReason.None && item.Date is not null).ToList();
        if (eligible.Count == 0)
        {
            if (entries.Count == 0)
            {
                return ("unavailable", null, "没有满足结构签名的日期候选。", DateConfidenceLevel.Unavailable);
            }

            if (entries.Any(item => item.Rejection == DateRejectionReason.DuplicateSignature))
            {
                return ("ambiguous", null,
                    "所有合理候选的逻辑签名都重复，无法唯一确定哪一条是当前日期。",
                    DateConfidenceLevel.Discovered);
            }

            return visible is null
                ? ("unavailable", null, "所有候选都因结构、稳定性或对象类型被排除。", DateConfidenceLevel.Discovered)
                : ("verification_mismatch", null,
                    $"界面日期 {visible} 与任何候选都不一致：不得把其他日期当作当前日期。",
                    DateConfidenceLevel.VerificationPending);
        }

        if (visible is not null)
        {
            var matches = eligible.Where(item => item.DateText == visible).ToList();
            if (matches.Count == 1)
            {
                return ("session_verified", matches[0],
                    $"界面日期 {visible} 与唯一候选 {matches[0].Observation.LogicalSignature} 一致。",
                    DateConfidenceLevel.SessionVerified);
            }

            return matches.Count == 0
                ? ("verification_mismatch", null,
                    $"界面日期 {visible} 与任何候选都不一致：不得把其他日期当作当前日期。",
                    DateConfidenceLevel.VerificationPending)
                : DisambiguateByIdentity(matches, visible, previous);
        }

        var latest = eligible.Max(item => item.Date!.Value);
        var top = eligible.Where(item => item.Date == latest).ToList();
        if (top.Count > 1)
        {
            return ("ambiguous", null,
                $"最新日期 {latest:yyyy-MM-dd} 同时出现在 {top.Count} 条记录中；没有界面日期证据，不能确定哪一条是当前日期。",
                DateConfidenceLevel.Discovered);
        }

        return ("heuristic", top[0],
            $"没有界面日期证据：仅按“结构合理 + 日期最新 + 复读稳定”选择 {latest:yyyy-MM-dd}，等级只能是 heuristic。",
            DateConfidenceLevel.Heuristic);
    }

    /// <summary>
    /// 同一界面日期匹配到多个候选时的身份去重：只有此前通过验证的逻辑身份能唯一胜出，
    /// 否则维持 ambiguous（绝不在多个同日期对象里随便挑一个）。
    /// </summary>
    private static (string Status, Entry? Selected, string? Reason, DateConfidenceLevel Level) DisambiguateByIdentity(
        IReadOnlyList<Entry> matches,
        string visible,
        DateVerificationState previous)
    {
        if (!string.IsNullOrEmpty(previous.LastConfirmedIdentity))
        {
            var preferred = matches
                .Where(item => string.Equals(
                    item.Observation.IdentitySignature,
                    previous.LastConfirmedIdentity,
                    StringComparison.Ordinal))
                .ToList();
            if (preferred.Count == 1)
            {
                return ("session_verified", preferred[0],
                    $"界面日期 {visible} 匹配多个候选；按上次验证过的逻辑身份 {previous.LastConfirmedIdentity} 唯一确定。",
                    DateConfidenceLevel.SessionVerified);
            }
        }

        return ("ambiguous", null,
            $"界面日期 {visible} 同时匹配 {matches.Count} 个候选，且没有可唯一区分它们的身份证据。",
            DateConfidenceLevel.Discovered);
    }

    private static Dictionary<string, TrackedCandidateState> BuildPreviousLookup(
        IReadOnlyList<TrackedCandidateState> candidates)
    {
        var lookup = new Dictionary<string, TrackedCandidateState>(StringComparer.Ordinal);
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrEmpty(candidate.IdentitySignature))
            {
                lookup[candidate.IdentitySignature] = candidate;
                continue;
            }

            // 旧状态没有身份字段：按结构签名回退关联，避免历史证据直接作废。
            lookup[candidate.LogicalSignature] = candidate;
        }

        return lookup;
    }

    private static (DateRejectionReason Reason, string Detail)? DecideStructuralRejection(Entry entry)
    {
        var observation = entry.Observation;
        if (entry.Date is null)
        {
            return (DateRejectionReason.InvalidDate, $"原始值 0x{observation.RawValue:X8} 不是合法 FM 日期。");
        }

        if (entry.Date.Value.Year is < 2000 or > 2060)
        {
            return (DateRejectionReason.OutOfSupportedRange, $"日期 {entry.DateText} 的年份不在 2000..2060。");
        }

        if (entry.Gap is int.MinValue or < WorldDateResolver.MinReferenceGapDays or > WorldDateResolver.MaxReferenceGapDays)
        {
            return (DateRejectionReason.OutOfSupportedRange,
                $"参考日期间隔 {(entry.Gap == int.MinValue ? "未知" : entry.Gap.ToString())} 天，不在 {WorldDateResolver.MinReferenceGapDays}..{WorldDateResolver.MaxReferenceGapDays} 天。");
        }

        switch (observation.KindHint)
        {
            case DateCandidateKind.MatchDate:
                return (DateRejectionReason.MatchObject, "对象分类器把该候选标记为比赛对象。");
            case DateCandidateKind.TransferDate:
                return (DateRejectionReason.TransferObject, "对象分类器把该候选标记为转会对象。");
            case DateCandidateKind.CalendarDate:
                return (DateRejectionReason.CalendarObject, "对象分类器把该候选标记为日历/赛程对象。");
            case DateCandidateKind.NewsDate:
                return (DateRejectionReason.NewsObject, "对象分类器把该候选标记为新闻对象。");
            case DateCandidateKind.HistoryDate:
                return (DateRejectionReason.InsufficientEvidence, "对象分类器把该候选标记为历史记录对象。");
        }

        if (observation.ConsecutiveConsistentReads < RequiredConsistentReads)
        {
            return (DateRejectionReason.UnstableValue,
                $"稳定性复读只有 {observation.ConsecutiveConsistentReads}/{RequiredConsistentReads} 次一致。");
        }

        return null;
    }

    private static int ApplyVerification(
        Entry selected,
        ProcessSessionIdentity session,
        List<string> evidence)
    {
        var state = selected.State;
        var verifiedDates = state.VerifiedDates.ToList();
        if (selected.DateText is not null && !verifiedDates.Contains(selected.DateText, StringComparer.Ordinal))
        {
            verifiedDates.Add(selected.DateText);
        }

        var sessions = state.VerifiedSessionKeys.ToList();
        if (!sessions.Contains(session.SessionKey, StringComparer.Ordinal))
        {
            sessions.Add(session.SessionKey);
            evidence.Add($"候选 {state.LogicalSignature} 在进程会话 {session.SessionKey} 完成新的界面日期验证。");
        }

        var updated = state with { VerifiedDates = verifiedDates, VerifiedSessionKeys = sessions };
        selected.State = updated;
        return sessions.Count;
    }

    private static TrackedCandidateState UpdateState(
        IReadOnlyDictionary<string, TrackedCandidateState> previous,
        DateCandidateObservation observation,
        string? dateText,
        ProcessSessionIdentity session,
        string nowText)
    {
        previous.TryGetValue(observation.IdentitySignature, out var existing);
        var observedDates = existing?.ObservedDates?.ToList() ?? new List<string>();
        if (dateText is not null && !observedDates.Contains(dateText, StringComparer.Ordinal))
        {
            observedDates.Add(dateText);
        }

        return new TrackedCandidateState(
            observation.LogicalSignature,
            observation.Module,
            observation.StructureFingerprint,
            existing?.FirstSeen ?? nowText,
            nowText,
            (existing?.ReadCount ?? 0) + WorldDateCandidateCollector.StabilityReads,
            observation.ConsecutiveConsistentReads,
            $"0x{observation.RawValue:X8}",
            CandidateIdentity.Hex(observation.Address),
            session.SessionKey,
            existing?.FirstSessionKey ?? session.SessionKey,
            observedDates,
            existing?.VerifiedDates ?? Array.Empty<string>(),
            existing?.VerifiedSessionKeys ?? Array.Empty<string>(),
            observation.IdentitySignature,
            observation.ReferenceChain?.Signature,
            observation.ReferenceChain?.Describe(),
            observation.ReferenceChain?.Level ?? 0);
    }

    private static DateCandidateDiagnostics ToDiagnostic(int index, Entry entry) => new(
        Index: index,
        Address: entry.Observation.Address,
        BaseAddress: entry.Observation.BaseAddress,
        RegionStart: entry.Observation.RegionStart,
        RegionOffset: entry.Observation.RegionStart == 0 ? 0 : entry.Observation.Address - entry.Observation.RegionStart,
        Module: entry.Observation.Module,
        DataType: "u32",
        RawBytes: entry.Observation.RawBytes,
        RawValue: entry.Observation.RawValue,
        Date: entry.DateText,
        RawReference: entry.Observation.RawReference,
        Reference: entry.Reference?.ToString("yyyy-MM-dd"),
        ReferenceGapDays: entry.Gap == int.MinValue ? 0 : entry.Gap,
        Signature: entry.Observation.Signature,
        Source: entry.Observation.Source,
        StructureFingerprint: entry.Observation.StructureFingerprint,
        LogicalSignature: entry.Observation.LogicalSignature,
        RelativeAddress: entry.Observation.RelativeAddress,
        RelatedObject: entry.Observation.RelatedObject,
        StructureEvidence: entry.Observation.StructureEvidence,
        Kind: entry.Kind,
        Rejection: entry.Rejection,
        Confidence: entry.Confidence,
        FirstSeen: entry.State.FirstSeen,
        LastSeen: entry.State.LastSeen,
        ReadCount: entry.State.ReadCount,
        ConsecutiveConsistentReads: entry.Observation.ConsecutiveConsistentReads,
        SessionKey: entry.State.LastSessionKey,
        ObservedDates: entry.State.ObservedDates,
        RejectionDetail: entry.Detail,
        IdentitySignature: entry.Observation.IdentitySignature,
        ReferenceChain: entry.Observation.ReferenceChain);

    private static DateVerificationState BuildState(
        DateVerificationState previous,
        ProcessSessionIdentity session,
        string? saveKey,
        string? confirmedDate,
        string? observedDate,
        string? confirmedIdentity,
        IReadOnlyList<TrackedCandidateState> tracked,
        IReadOnlyList<string> evidence,
        string nowText)
    {
        var evidenceEntries = previous.Evidence.ToList();
        foreach (var line in evidence)
        {
            evidenceEntries.Add(new DateEvidenceEntry(
                Kind: line.Contains("界面日期", StringComparison.Ordinal) ? "operator_date_check" : "observation",
                Detail: line,
                At: nowText,
                SessionKey: session.SessionKey,
                VisibleDate: confirmedDate,
                ReaderDate: observedDate,
                LogicalSignature: null));
        }

        if (evidenceEntries.Count > DateVerificationStore.MaxEvidenceEntries)
        {
            evidenceEntries = evidenceEntries
                .Skip(evidenceEntries.Count - DateVerificationStore.MaxEvidenceEntries)
                .ToList();
        }

        var persisted = tracked
            .GroupBy(
                item => string.IsNullOrEmpty(item.IdentitySignature) ? item.LogicalSignature : item.IdentitySignature!,
                StringComparer.Ordinal)
            .Select(group => group.Last())
            .Take(MaxPersistedCandidates)
            .ToList();

        return new DateVerificationState(
            Build: session.Build ?? previous.Build,
            SaveKey: saveKey ?? previous.SaveKey,
            LastSessionKey: session.SessionKey,
            LastConfirmedDate: confirmedDate ?? previous.LastConfirmedDate,
            LastObservedDate: observedDate ?? previous.LastObservedDate,
            Candidates: persisted,
            Evidence: evidenceEntries,
            LastConfirmedIdentity: confirmedIdentity ?? previous.LastConfirmedIdentity);
    }

    /// <summary>内部候选条目（可变的判定状态）。</summary>
    private sealed class Entry
    {
        public Entry(
            DateCandidateObservation observation,
            TrackedCandidateState state,
            DateOnly? date,
            DateOnly? reference,
            int gap)
        {
            Observation = observation;
            State = state;
            Date = date;
            Reference = reference;
            Gap = gap;
        }

        public DateCandidateObservation Observation { get; }

        public TrackedCandidateState State { get; set; }

        public DateOnly? Date { get; }

        public DateOnly? Reference { get; }

        public int Gap { get; }

        public string? DateText => Date?.ToString("yyyy-MM-dd");

        public DateRejectionReason Rejection { get; set; } = DateRejectionReason.None;

        public string? Detail { get; set; }

        public DateCandidateKind Kind { get; set; } = DateCandidateKind.UnknownDate;

        public DateConfidenceLevel Confidence { get; set; } = DateConfidenceLevel.Discovered;
    }
}
