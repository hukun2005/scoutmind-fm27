using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>一个被定位到的对象：扫描位置 p 与三类块偏移。</summary>
/// <param name="Address">扫描命中位置（vtable 所在地址）。</param>
/// <param name="BlockOffset">球员/职员块相对地址。</param>
/// <param name="PersonOffset">个人块相对地址。</param>
/// <param name="DbOffset">数据库块相对地址。</param>
public sealed record LocatedObject(ulong Address, long BlockOffset, long PersonOffset, long DbOffset)
{
    /// <summary>球员块地址（<c>PLAO_*</c> 的基址）。</summary>
    public ulong Block => (ulong)((long)Address + BlockOffset);

    /// <summary>个人块地址（<c>PERO_*</c> 的基址）。</summary>
    public ulong Person => (ulong)((long)Address + PersonOffset);

    /// <summary>数据库块地址（<c>OBJ_DUNI</c> 的基址）。</summary>
    public ulong Db => (ulong)((long)Address + DbOffset);
}

/// <summary>对象定位：真实实现扫描进程内存，测试用固定样本。</summary>
public interface IObjectLocator
{
    /// <summary>定位若干球员对象。</summary>
    /// <param name="layout">布局。</param>
    /// <param name="max">最多返回数量。</param>
    /// <param name="budget">时间预算。</param>
    /// <returns>定位结果。</returns>
    IReadOnlyList<LocatedObject> FindPlayers(ILayout layout, int max, TimeSpan budget);

    /// <summary>定位若干俱乐部对象。</summary>
    /// <param name="layout">布局。</param>
    /// <param name="max">最多返回数量。</param>
    /// <param name="budget">时间预算。</param>
    /// <returns>定位结果。</returns>
    IReadOnlyList<LocatedObject> FindClubs(ILayout layout, int max, TimeSpan budget);
}

/// <summary>FM 日期的解码规则（来自上游 <c>Dumper.DecodeFmDate</c>）：高 16 位年、低 9 位为年内第几天。</summary>
public static class FmDate
{
    /// <summary>解码。</summary>
    /// <param name="raw">原始 u32。</param>
    /// <returns>年份与年内序日；非法时为 <c>(0, 0)</c>。</returns>
    public static (int Year, int DayOfYear) Decode(uint raw)
    {
        var year = (int)(raw >> 16);
        var doy = (int)(raw & 0x1FF);
        return year is < 1900 or > 2100 || doy is < 1 or > 366 ? (0, 0) : (year, doy);
    }
}

/// <summary>对象探测：只读，逐类验证"定位到的对象是否是它声称的东西"。</summary>
public sealed partial class ObjectProbes
{
    private const int SampleLimit = 32;

    private readonly IMemorySource _memory;
    private readonly ILayout _layout;

    /// <summary>创建探测。</summary>
    /// <param name="memory">内存源。</param>
    /// <param name="layout">布局。</param>
    public ObjectProbes(IMemorySource memory, ILayout layout)
    {
        _memory = memory;
        _layout = layout;
    }

    /// <summary>球员对象探测：类型、范围、指针有效性、跨字段一致性。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbePlayers(IReadOnlyList<LocatedObject> players)
    {
        var sample = players.Take(SampleLimit).ToList();
        var checks = new List<FieldCheck>();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("player", ProbeStatus.Failed, 0,
                new[] { new FieldCheck("player_objects_found", CheckStatus.Failed, "没有定位到任何球员对象") },
                "没有在堆里认出球员对象：最常见的两种原因是「游戏还停在主菜单、没有加载存档」与「布局不匹配」。"
                + "请先进入存档再重试；若已进入存档仍然是 0，就可以判定布局不匹配。");
        }

        int caInRange = 0, paInRange = 0, caLePa = 0, heightSane = 0, dobSane = 0, nameSane = 0, positionsSane = 0;
        int contractPointerValid = 0, personInModule = 0, attrsSane = 0, contractApplicable = 0, contractMissing = 0;
        foreach (var player in sample)
        {
            try
            {
                var ca = _memory.UInt16(player.Block + _layout["PLAO_CA"]);
                var pa = _memory.UInt16(player.Block + _layout["PLAO_PA"]);
                if (ca is >= 1 and <= 200) caInRange++;
                if (pa is >= 1 and <= 200) paInRange++;
                if (ca is >= 1 and <= 200 && pa is >= 1 and <= 200 && ca <= pa) caLePa++;

                var height = _memory.UInt16(player.Block + _layout["PLAO_HEIGHT"]);
                if (height is 0 or (>= 140 and <= 230)) heightSane++;

                var (year, doy) = FmDate.Decode(_memory.UInt32(player.Person + _layout["PERO_DOB"]));
                if (year is >= 1940 and <= 2015 && doy is >= 1 and <= 366) dobSane++;

                var name = ReadPlayerName(player.Person);
                if (IsSaneName(name)) nameSane++;

                var positionsSaneHere = true;
                for (var index = 0; index < 15; index++)
                {
                    var value = _memory.Byte(player.Block + _layout["PLAO_POSITIONS"] + (uint)index);
                    if (value > 20)
                    {
                        positionsSaneHere = false;
                        break;
                    }
                }

                if (positionsSaneHere) positionsSane++;

                var attrsSaneHere = true;
                for (var index = 0; index < 20; index++)
                {
                    var value = _memory.Byte(player.Block + _layout["PLAO_ATTRS"] + (uint)index);
                    if (value > 100)
                    {
                        attrsSaneHere = false;
                        break;
                    }
                }

                if (attrsSaneHere) attrsSane++;

                if (IsPlausibleHeapPointer(player.Person)) personInModule++;

                var contract = _memory.Pointer(player.Person + _layout["PERO_FULL_CONTRACT"]);
                if (IsPlausibleHeapPointer(contract) && _memory.IsReadable(contract + _layout["CON_EXPIRY"], 4))
                {
                    contractPointerValid++;
                }
            }
            catch (MemoryUnreadableException)
            {
                // 不可读样本不计入任何通过项。
            }
        }

        var total = sample.Count;
        checks.Add(Ratio("ca_range", caInRange, total, "CA 必须落在 1..200"));
        checks.Add(Ratio("pa_range", paInRange, total, "PA 必须落在 1..200"));
        checks.Add(Ratio("ca_le_pa", caLePa, total, "同一球员 CA<=PA（允许少量异常）", 0.9));
        checks.Add(Ratio("height_range", heightSane, total, "身高为 0（未设置）或 140..230"));
        checks.Add(Ratio("dob_range", dobSane, total, "出生年份 1940..2015 且年内序日合法"));
        checks.Add(Ratio("name_string", nameSane, total, "姓名是可打印字符串且含字母"));
        checks.Add(Ratio("positions_bytes", positionsSane, total, "15 个位置字节都 <=20"));
        checks.Add(Ratio("attributes_head", attrsSane, total, "属性块前 20 字节 <=100（存储值×5）"));
        checks.Add(Ratio("person_in_module", personInModule, total, "个人块地址是合法堆指针（对齐、可读）"));
        checks.Add(Ratio("contract_pointer", contractPointerValid, contractApplicable == 0 ? 1 : contractApplicable, $"合同指针是合法堆指针且可读（{contractMissing} 名无可解析合同，按未知处理）", 0.9));

        var status = checks.Any(item => item.Status == CheckStatus.Failed)
            ? ProbeStatus.Failed
            : ProbeStatus.Passed;
        return new ProbeOutcome("player", status, total, checks,
            "结构自洽只能证明布局没有明显错位，不能证明数值正确；真实值需要与游戏内界面核对。");
    }

    /// <summary>从球员的合同 → 球队 → 俱乐部链上收集俱乐部地址（避免只靠 vtable 扫描）。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>去重后的俱乐部地址与对应球队地址。</returns>
    public IReadOnlyList<(ulong Club, ulong Team)> DeriveClubsFromPlayers(IReadOnlyList<LocatedObject> players)
    {
        var result = new List<(ulong Club, ulong Team)>();
        var seen = new HashSet<ulong>();
        foreach (var player in players.Take(SampleLimit * 4))
        {
            try
            {
                var contract = _memory.Pointer(player.Person + _layout["PERO_FULL_CONTRACT"]);
                if (!IsPlausibleHeapPointer(contract))
                {
                    continue;
                }

                var team = _memory.Pointer(contract + _layout["CON_TEAM"]);
                if (!IsPlausibleHeapPointer(team))
                {
                    continue;
                }

                var club = _memory.Pointer(team + _layout["TEAM_CLUB"]);
                if (IsPlausibleHeapPointer(club) && seen.Add(club))
                {
                    result.Add((club, team));
                }
            }
            catch (MemoryUnreadableException)
            {
                // 跳过不可读样本。
            }
        }

        return result;
    }

    /// <summary>俱乐部对象探测：名称可读、球队向量区间合理。</summary>
    /// <param name="clubs">定位到的俱乐部对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeClubs(IReadOnlyList<LocatedObject> clubs)
    {
        var sample = clubs.Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("club", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("club_objects_found", CheckStatus.Inconclusive, "没有定位到俱乐部对象") },
                "俱乐部对象未找到：可能是本存档在该时刻没有加载俱乐部，也可能布局不匹配。");
        }

        int nameSane = 0, teamsRangeSane = 0;
        foreach (var club in sample)
        {
            var name = _memory.IndirectString(club.Address + _layout["CLUB_NAME"]);
            if (IsSaneName(name)) nameSane++;

            var begin = _memory.Pointer(club.Address + _layout["CLUB_TEAMS_BEGIN"]);
            var end = _memory.Pointer(club.Address + _layout["CLUB_TEAMS_END"]);
            if (begin != 0 && end > begin && end - begin <= 0x40 * 16)
            {
                teamsRangeSane++;
            }
        }

        var checks = new List<FieldCheck>
        {
            Ratio("club_name_string", nameSane, sample.Count, "俱乐部名称可读且像名称"),
            Ratio("club_teams_range", teamsRangeSane, sample.Count, "球队向量 [begin,end) 合理（非空且不超过 16 队）", 0.9),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("club", status, sample.Count, checks, null);
    }

    /// <summary>球队/俱乐部关系探测：从球员的合同指针走到球队，再走到俱乐部。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeTeams(IReadOnlyList<LocatedObject> players)
    {
        var sample = players.Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("team", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("team_samples", CheckStatus.Inconclusive, "没有球员样本，无法验证球队关系") });
        }

        int teamReachable = 0, teamTypeSane = 0, clubReachable = 0, playersRangeSane = 0, crossConsistent = 0;
        int chainApplicable = 0, chainMissing = 0, vectorApplicable = 0, vectorMissing = 0;
        foreach (var player in sample)
        {
            try
            {
                var contract = _memory.Pointer(player.Person + _layout["PERO_FULL_CONTRACT"]);
                if (!IsPlausibleHeapPointer(contract))
                {
                    continue;
                }

                var team = _memory.Pointer(contract + _layout["CON_TEAM"]);
                if (!IsPlausibleHeapPointer(team))
                {
                    continue;
                }

                teamReachable++;
                var teamType = _memory.Byte(team + _layout["TEAM_TYPE"]);
                if (teamType <= 20) teamTypeSane++;

                var club = _memory.Pointer(team + _layout["TEAM_CLUB"]);
                if (IsPlausibleHeapPointer(club) && IsSaneName(_memory.IndirectString(club + _layout["CLUB_NAME"])))
                {
                    clubReachable++;
                }

                var begin = _memory.Pointer(team + _layout["TEAM_PLAYERS_BEGIN"]);
                var end = _memory.Pointer(team + _layout["TEAM_PLAYERS_END"]);
                var sane = begin != 0 && end > begin && end - begin <= 0x40 * 200;
                if (sane) playersRangeSane++;

                // 跨字段一致性：球员必须出现在自己球队的球员向量里（读前 200 个指针抽样）。
                if (sane && ContainsPointer(begin, end, player.Address))
                {
                    crossConsistent++;
                }
            }
            catch (MemoryUnreadableException)
            {
                // 不可读样本跳过。
            }
        }

        var checks = new List<FieldCheck>
        {
            Ratio("team_reachable", teamReachable, chainApplicable == 0 ? 1 : chainApplicable, $"合同 → 球队 指针链可达（{chainMissing} 名无可解析合同，按未知处理）", 0.9),
            Ratio("team_type_range", teamTypeSane, chainApplicable == 0 ? 1 : chainApplicable, "球队类型字节 0..20（上游：0=一线队，>=10=青年队）", 0.7),
            Ratio("club_from_team", clubReachable, chainApplicable == 0 ? 1 : chainApplicable, "球队 → 俱乐部 指针可达且名称可读", 0.9),
            Ratio("team_players_range", playersRangeSane, vectorApplicable == 0 ? 1 : vectorApplicable, $"球队球员向量 [begin,end) 合理（{vectorMissing} 个球队无向量，按未知处理）"),
            new FieldCheck("player_in_team", CheckStatus.Inconclusive,
                $"球员对象出现在球队向量中的比例：{crossConsistent}/{Math.Max(vectorApplicable, 1)}（向量里存的是哪种指针尚未确证，故只作参考）"),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("team", status, sample.Count, checks, null);
    }

    /// <summary>合同探测：到期日、工资、状态位、球队指针。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeContracts(IReadOnlyList<LocatedObject> players)
    {
        var sample = players.Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("contract", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("contract_samples", CheckStatus.Inconclusive, "没有球员样本，无法验证合同") });
        }

        int pointerValid = 0, expirySane = 0, wageSane = 0, flagsSane = 0, expiryAfterBirth = 0;
        int applicable = 0, missing = 0, noExpiry = 0, expiryApplicable = 0;
        var dateDiagnostics = new ContractDateDiagnostics();
        var flagCounts = new Dictionary<byte, int>();
        foreach (var player in sample)
        {
            try
            {
                var contract = _memory.Pointer(player.Person + _layout["PERO_FULL_CONTRACT"]);
                if (contract == 0 || !IsPlausibleHeapPointer(contract))
                {
                    // 退役/自由身：没有可解析的合同对象，按"未知"处理，不计入分母。
                    missing++;
                    continue;
                }

                applicable++;
                pointerValid++;

                var expiryRaw = _memory.UInt32(contract + _layout["CON_EXPIRY"]);
                dateDiagnostics.Add(expiryRaw);
                var (expiryYear, expiryDoy) = FmDate.Decode(expiryRaw);
                if (expiryYear == 0)
                {
                    noExpiry++;
                }
                else
                {
                    expiryApplicable++;
                    if (expiryYear is >= 2000 and <= 2060 && expiryDoy is >= 1 and <= 366)
                    {
                        expirySane++;
                    }
                }

                var wage = _memory.UInt32(contract + _layout["CON_WEEKLY_WAGE"]);
                if (wage <= 5_000_000) wageSane++;

                var flags = _memory.Byte(contract + _layout["CON_STATUS_FLAGS"]);
                flagCounts[flags] = flagCounts.GetValueOrDefault(flags) + 1;
                // 上游只解释 bit0/bit3/bit4/bit5；高位未定义，因此只要求不是全 0xFF。
                if (flags != 0xFF) flagsSane++;

                var (birthYear, _) = FmDate.Decode(_memory.UInt32(player.Person + _layout["PERO_DOB"]));
                if (birthYear != 0 && expiryYear != 0 && expiryYear > birthYear + 14 && expiryYear <= birthYear + 45)
                {
                    expiryAfterBirth++;
                }
            }
            catch (MemoryUnreadableException)
            {
                // 跳过不可读样本。
            }
        }

        var checks = new List<FieldCheck>
        {
            Ratio("contract_pointer", pointerValid, applicable == 0 ? 1 : applicable, $"合同指针可读（{missing} 名无可解析合同，按未知处理）"),
            Ratio("expiry_range", expirySane, expiryApplicable == 0 ? 1 : expiryApplicable, $"到期日 FM 日期可解码且年份 2000..2060（{noExpiry} 人无到期日，按未知处理）", 0.9),
            Ratio("wage_range", wageSane, applicable == 0 ? 1 : applicable, "周薪 <= 5,000,000"),
            Ratio("status_flags", flagsSane, applicable == 0 ? 1 : applicable, "状态位不是 0xFF（未定义值）", 0.9),
            Ratio("expiry_after_birth", expiryAfterBirth, expiryApplicable == 0 ? 1 : expiryApplicable, "到期日晚于出生 14 年且不超过 45 年", 0.8),
            dateDiagnostics.Total > 0
                ? new FieldCheck("expiry_diagnostics", CheckStatus.Inconclusive,
                    $"{dateDiagnostics.Summary}；可解码比例 {dateDiagnostics.DecodableRatio:P0}；原始样本：{dateDiagnostics.RawSamples}")
                : new FieldCheck("expiry_diagnostics", CheckStatus.Inconclusive, "没有可解析合同样本"),
            new FieldCheck("contract_flags_mix", CheckStatus.Inconclusive,
                "状态位分布：" + string.Join("，", flagCounts.OrderBy(item => item.Key)
                    .Select(item => $"0x{item.Key:X2}={item.Value}"))
                + "（仅作为对象类型线索，不能据此判定合同类型）"),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("contract", status, sample.Count, checks,
            "合同探测是数据质量信号：无合同/到期日异常会在个别样本上出现，属于数据完整性问题，不代表布局错位；"
            + "布局正确性由 execution_layout、player、club、position、attributes、nation 与 integrity 共同判定。");
    }

    /// <summary>
    /// 租借探测。当前两份布局都没有租借字段（上游只给出 `ownerClub` 之类的名称，没有 parent/loan 结构），
    /// 因此这里如实报告"不适用"，而不是编一个通过。
    /// </summary>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeLoans()
    {
        var hasLoanField = _layout.Offsets.Keys.Any(key =>
            key.Contains("LOAN", StringComparison.Ordinal) || key.Contains("PARENT", StringComparison.Ordinal));
        if (hasLoanField)
        {
            return new ProbeOutcome("loan", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("loan_fields", CheckStatus.Inconclusive, "布局声明了租借字段，但尚无验证实现") },
                "布局有租借字段，需要补充探测逻辑。");
        }

        return new ProbeOutcome("loan", ProbeStatus.NotApplicable, 0,
            new[] { new FieldCheck("loan_fields", CheckStatus.Inconclusive, "布局没有租借偏移") },
            "内存布局不提供租借/所有权关系：租借只能来自阵容 CSV，或由上游导出的 ownerClub 名称推断（不在此探测范围）。");
    }

    /// <summary>转会记录探测：按上游记录的形状（哨兵常量 + 状态字节）校验。</summary>
    /// <param name="deals">定位到的转会记录地址。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeTransfers(IReadOnlyList<ulong> deals)
    {
        var sample = deals.Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("transfer", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("deal_records", CheckStatus.Inconclusive, "没有定位到转会记录") },
                "转会记录没有 vtable，只能按形状识别；本次没有找到可校验样本。");
        }

        int sentinelSane = 0, statusSane = 0, teamsSane = 0, dateSane = 0;
        foreach (var deal in sample)
        {
            try
            {
                var sentinel1 = _memory.UInt32(deal + _layout["DEAL_SENT1"]);
                var sentinel2 = _memory.UInt32(deal + _layout["DEAL_SENT2"]);
                if (sentinel1 == 0xFFFFFFFF && sentinel2 == 0x076C0001) sentinelSane++;

                var dealStatus = _memory.Byte(deal + _layout["DEAL_STATUS"]);
                if (dealStatus is 0x13 or 0x14 or 0x0F or (>= 0x00 and <= 0x20)) statusSane++;

                var toTeam = _memory.Pointer(deal + _layout["DEAL_TO_TEAM"]);
                var fromTeam = _memory.Pointer(deal + _layout["DEAL_FROM_TEAM"]);
                if (IsPlausibleHeapPointer(toTeam) && IsPlausibleHeapPointer(fromTeam)) teamsSane++;

                var (year, doy) = FmDate.Decode(_memory.UInt32(deal + _layout["DEAL_DATE"]));
                if (year is >= 1990 and <= 2060 && doy is >= 1 and <= 366) dateSane++;
            }
            catch (MemoryUnreadableException)
            {
                // 跳过不可读记录。
            }
        }

        var checks = new List<FieldCheck>
        {
            Ratio("deal_sentinels", sentinelSane, sample.Count, "哨兵 0xFFFFFFFF / 0x076C0001 同时命中", 0.9),
            Ratio("deal_status", statusSane, sample.Count, "状态字节在已知范围"),
            Ratio("deal_teams", teamsSane, sample.Count, "买卖双方球队指针可读"),
            Ratio("deal_date", dateSane, sample.Count, "转会日期可解码", 0.8),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("transfer", status, sample.Count, checks, null);
    }

    /// <summary>数据结构完整性：样本量、唯一性、NULL 比例。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <param name="clubs">定位到的俱乐部对象。</param>
    /// <param name="minimumPlayers">期望的最小球员样本量。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeIntegrity(IReadOnlyList<LocatedObject> players, IReadOnlyList<LocatedObject> clubs, int minimumPlayers = 20)
    {
        var candidates = players.Take(256).ToList();
        var uniqueObjects = new HashSet<ulong>();
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var uids = new HashSet<uint>();
        var samples = new List<ObjectIdSample>();
        int duplicateAddresses = 0, readableDb = 0, readableUid = 0, validUid = 0;
        int zeroUid = 0, sentinelUid = 0, unreadableUid = 0, nullNames = 0;

        foreach (var player in candidates)
        {
            if (!uniqueObjects.Add(player.Address))
            {
                duplicateAddresses++;
                continue;
            }

            var dbReadable = _memory.IsReadable(player.Db, 4);
            if (dbReadable) readableDb++;
            uint? raw = null;
            var sampleStatus = "unreadable";
            string? reason = dbReadable ? null : "db_unreadable";
            if (dbReadable)
            {
                try
                {
                    raw = _memory.UInt32(player.Db + _layout["OBJ_DUNI"]);
                    readableUid++;
                    sampleStatus = "read";
                }
                catch (MemoryUnreadableException)
                {
                    unreadableUid++;
                    sampleStatus = "uid_unreadable";
                    reason = "uid_unreadable";
                }
            }
            else
            {
                unreadableUid++;
            }

            if (raw is 0)
            {
                zeroUid++;
                sampleStatus = "zero";
                reason = "uid_zero";
            }
            else if (raw is 0xFFFFFFFF)
            {
                sentinelUid++;
                sampleStatus = "sentinel";
                reason = "uid_sentinel";
            }
            else if (raw is not null)
            {
                validUid++;
                uids.Add(raw.Value);
            }

            var name = ReadPlayerName(player.Person);
            if (name is null) nullNames++; else names.Add(name);
            if (samples.Count < 20)
            {
                samples.Add(new ObjectIdSample(player.Address, player.Db, raw, sampleStatus, reason, name));
            }
        }

        var uniqueCount = uniqueObjects.Count;
        var duplicateUidCount = validUid - uids.Count;
        var diagnostics = new ObjectIdDiagnostics(
            candidates.Count,
            uniqueCount,
            duplicateAddresses,
            readableDb,
            readableUid,
            validUid,
            zeroUid,
            sentinelUid,
            duplicateUidCount,
            unreadableUid,
            samples);

        var checks = new List<FieldCheck>
        {
            Ratio("player_sample_size", Math.Min(uniqueCount, minimumPlayers), minimumPlayers,
                $"至少定位到 {minimumPlayers} 名去重球员（候选 {candidates.Count}，重复地址 {duplicateAddresses}）", 1.0),
            Ratio("uid_readable", readableUid, Math.Max(1, uniqueCount),
                $"UID 可读比例（DB 可读 {readableDb}/{uniqueCount}；不可读 {unreadableUid}）", 0.95),
            Ratio("uid_valid", validUid, Math.Max(1, readableUid),
                $"UID 合法比例（0={zeroUid}，哨兵={sentinelUid}）", 0.95),
            Ratio("unique_uids", uids.Count, Math.Max(1, validUid),
                $"合法 UID 去重比例（重复 UID {duplicateUidCount}）", 0.95),
            Ratio("unique_names", names.Count, Math.Max(1, uniqueCount - nullNames), "姓名在样本内基本唯一", 0.9),
            Ratio("readable_names", uniqueCount - nullNames, Math.Max(1, uniqueCount), "姓名可读比例", 0.95),
            Ratio("club_sample_size", Math.Min(clubs.Count, 1), 1, "至少定位到 1 个俱乐部对象", 1.0),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("integrity", status, uniqueCount, checks, null) { ObjectIds = diagnostics };
    }

    private string? ReadPlayerName(ulong person)
    {
        var common = _memory.NestedString(person + _layout["PERO_COMMON_NAME"]);
        if (!string.IsNullOrWhiteSpace(common))
        {
            return common;
        }

        var first = _memory.NestedString(person + _layout["PERO_FIRST_NAME"]);
        var second = _memory.NestedString(person + _layout["PERO_SECOND_NAME"]);
        var name = string.Join(" ", new[] { first, second }.Where(item => !string.IsNullOrWhiteSpace(item)));
        return string.IsNullOrWhiteSpace(name) ? null : name;
    }

    private bool ContainsPointer(ulong begin, ulong end, ulong target)
    {
        var count = Math.Min(200, (int)((end - begin) / 8));
        for (var index = 0; index < count; index++)
        {
            try
            {
                if (_memory.Pointer(begin + (ulong)(index * 8)) == target)
                {
                    return true;
                }
            }
            catch (MemoryUnreadableException)
            {
                return false;
            }
        }

        return false;
    }

    /// <summary>筛出"看起来是球员"的对象：CA 在 1..200。被误分类的职员/垃圾对象不参与关系链检查。</summary>
    private IEnumerable<LocatedObject> RealPlayers(IReadOnlyList<LocatedObject> players)
    {
        foreach (var player in players)
        {
            ushort ca;
            try
            {
                ca = _memory.UInt16(player.Block + _layout["PLAO_CA"]);
            }
            catch (MemoryUnreadableException)
            {
                continue;
            }

            if (ca is >= 1 and <= 200)
            {
                yield return player;
            }
        }
    }

    /// <summary>堆指针合理性：非空、8 字节对齐、位于用户态地址范围、且 8 字节可读。</summary>
    private bool IsPlausibleHeapPointer(ulong address)
    {
        if (address < 0x10000 || address > 0x7FFF_FFFF_FF00 || (address & 0x7) != 0)
        {
            return false;
        }

        try
        {
            return _memory.IsReadable(address, 8);
        }
        catch (MemoryUnreadableException)
        {
            return false;
        }
    }

    private static bool IsSaneName(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        var trimmed = value.Trim();
        if (trimmed.Length is < 2 or > 64)
        {
            return false;
        }

        var letters = 0;
        foreach (var ch in trimmed)
        {
            if (char.IsControl(ch))
            {
                return false;
            }

            if (char.IsLetter(ch))
            {
                letters++;
            }
        }

        return letters >= 2;
    }

    private static FieldCheck Ratio(string name, int passed, int total, string rule, double threshold = 0.95)
    {
        if (total <= 0)
        {
            return new FieldCheck(name, CheckStatus.Inconclusive, $"{rule}（无样本）");
        }

        var ratio = (double)passed / total;
        var status = ratio >= threshold ? CheckStatus.Passed : CheckStatus.Failed;
        return new FieldCheck(name, status, $"{rule}：{passed}/{total}（{ratio:P0}，阈值 {threshold:P0}）");
    }
}
