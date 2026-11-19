using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>属性 / 位置 / 国籍 / 球队关系的字段级探测（与 <see cref="ObjectProbes"/> 同一实例，partial）。</summary>
public sealed partial class ObjectProbes
{
    /// <summary>按 <c>PERO_GENDER</c> 的 0x10 位把样本分成男子/女子数据库两批。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>两批样本。</returns>
    public (IReadOnlyList<LocatedObject> Men, IReadOnlyList<LocatedObject> Women) SplitByGender(IReadOnlyList<LocatedObject> players)
    {
        var men = new List<LocatedObject>();
        var women = new List<LocatedObject>();
        foreach (var player in players)
        {
            try
            {
                var gender = _memory.Byte(player.Person + _layout["PERO_GENDER"]);
                ((gender & 0x10) != 0 ? women : men).Add(player);
            }
            catch (MemoryUnreadableException)
            {
                // 读不到性别的样本不参与分批。
            }
        }

        return (men, women);
    }

    /// <summary>
    /// 属性分组探测：技术 / 精神 / 身体。上游解码是 round(raw/5) 并钳制 0..20，所以只校验 raw ≤100 与解码范围。
    /// </summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <param name="groupName">组名，用于报告。</param>
    /// <param name="keys">该组的属性键；不在映射表里的键会被跳过并记入证据。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeAttributeGroup(IReadOnlyList<LocatedObject> players, string groupName, IReadOnlyList<string> keys)
    {
        var sample = RealPlayers(players).Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome(groupName, ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("samples", CheckStatus.Inconclusive, "没有球员样本") });
        }

        var mapped = new List<(string Key, int Offset)>();
        var unmapped = new List<string>();
        foreach (var key in keys)
        {
            if (AttributeMap.TryGet(key, out var offset))
            {
                mapped.Add((key, offset));
            }
            else
            {
                unmapped.Add(key);
            }
        }

        if (mapped.Count == 0)
        {
            return new ProbeOutcome(groupName, ProbeStatus.NotApplicable, sample.Count,
                new[] { new FieldCheck("mapping", CheckStatus.Inconclusive, $"属性映射表里没有这一组的键：{string.Join("、", unmapped)}") },
                "映射表由后端 ATTRIBUTE_MAP 生成；缺键时不做推断。");
        }

        var checks = new List<FieldCheck>();
        foreach (var (key, offset) in mapped)
        {
            int inRange = 0;
            int decodedInRange = 0;
            foreach (var player in sample)
            {
                try
                {
                    var raw = _memory.Byte(player.Block + _layout["PLAO_ATTRS"] + (uint)offset);
                    if (raw <= 100) inRange++;
                    // 上游解码：round(raw / 5)，钳制 0..20（raw 不要求是 5 的倍数）。
                    var decoded = (int)Math.Floor(raw / 5.0 + 0.5);
                    if (decoded is >= 0 and <= 20) decodedInRange++;
                }
                catch (MemoryUnreadableException)
                {
                    // 跳过不可读样本。
                }
            }

            checks.Add(Ratio("attr." + key, inRange, sample.Count, "原始字节 ≤100", 0.95));
            checks.Add(Ratio("attr." + key + ".decoded", decodedInRange, sample.Count, "round(raw/5) 落在 0..20", 0.95));
        }

        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        var note = unmapped.Count == 0
            ? "属性值只经过范围/步长检查；分组按 FM 惯例，属于程序内部合理性检查。"
            : $"未映射（不检查）：{string.Join("、", unmapped)}。";
        return new ProbeOutcome(groupName, status, sample.Count, checks, note);
    }

    /// <summary>位置熟悉度探测：15 个字节 0..20，且至少一个 ≥15（自然位置）。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbePositions(IReadOnlyList<LocatedObject> players)
    {
        var sample = RealPlayers(players).Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("position", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("samples", CheckStatus.Inconclusive, "没有球员样本") });
        }

        int inRange = 0, natural = 0;
        var distribution = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var player in sample)
        {
            var sane = true;
            var best = 0;
            foreach (var (key, offset) in FieldSpecs.Positions)
            {
                byte value;
                try
                {
                    value = _memory.Byte(player.Block + _layout["PLAO_POSITIONS"] + (uint)offset);
                }
                catch (MemoryUnreadableException)
                {
                    sane = false;
                    break;
                }

                if (value > 20)
                {
                    sane = false;
                }

                if (value > best)
                {
                    best = value;
                }

                if (value >= 15)
                {
                    distribution[key] = distribution.GetValueOrDefault(key) + 1;
                }
            }

            if (sane) inRange++;
            if (best >= 15) natural++;
        }

        var checks = new List<FieldCheck>
        {
            Ratio("position.bytes", inRange, sample.Count, "15 个位置字节都 ≤20", 0.95),
            Ratio("position.natural", natural, sample.Count, "至少一个位置 ≥15（上游注释：自然位置）", 0.95),
            new FieldCheck("position.distribution", CheckStatus.Inconclusive,
                "样本分布：" + string.Join(", ", distribution.Select(item => $"{item.Key}={item.Value}"))),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("position", status, sample.Count, checks,
            "位置字节含义来自上游注释；与游戏内位置列核对之前只算内部一致性。");
    }

    /// <summary>国籍探测：国家指针可读、名称可读、且不像乱码。</summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeNationality(IReadOnlyList<LocatedObject> players)
    {
        var sample = RealPlayers(players).Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("nation", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("samples", CheckStatus.Inconclusive, "没有球员样本") });
        }

        int pointerSane = 0, nameSane = 0;
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var player in sample)
        {
            try
            {
                var nation = _memory.Pointer(player.Person + _layout["PERO_NATION"]);
                if (!IsPlausibleHeapPointer(nation))
                {
                    continue;
                }

                pointerSane++;
                var name = _memory.IndirectString(nation + _layout["NATION_NAME"])
                           ?? _memory.IndirectString(nation + _layout["NATION_SHORT_NAME"]);
                if (IsSaneName(name))
                {
                    nameSane++;
                    names.Add(name!);
                }
            }
            catch (MemoryUnreadableException)
            {
                // 跳过。
            }
        }

        if (pointerSane == 0)
        {
            return new ProbeOutcome("nation", ProbeStatus.Inconclusive, sample.Count,
                new[] { new FieldCheck("nation.pointer", CheckStatus.Inconclusive, "样本中没有可解析的国家指针，无法判断") },
                "国家字段未能验证（可能是样本问题，也可能是偏移不匹配）；不判为通过。");
        }

        var checks = new List<FieldCheck>
        {
            Ratio("nation.pointer", pointerSane, sample.Count, "国家指针是合法堆指针", 0.7),
            Ratio("nation.name", nameSane, pointerSane, "国家名称可读且像名称", 0.95),
            new FieldCheck("nation.distinct", CheckStatus.Inconclusive, $"样本中出现 {names.Count} 个不同国家"),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("nation", status, sample.Count, checks,
            "国家名称只做可读性检查；与游戏内国籍列核对之前只算内部一致性。");
    }

    /// <summary>
    /// 球队关系探测：当前球队、注册俱乐部、球队层级。
    /// 明确区分：注册俱乐部（team → club）与当前球队（contract → team）；母队/租借字段不存在。
    /// </summary>
    /// <param name="players">定位到的球员对象。</param>
    /// <returns>探测结果。</returns>
    public ProbeOutcome ProbeTeamRelations(IReadOnlyList<LocatedObject> players)
    {
        var sample = RealPlayers(players).Take(SampleLimit).ToList();
        if (sample.Count == 0)
        {
            return new ProbeOutcome("team_relation", ProbeStatus.Inconclusive, 0,
                new[] { new FieldCheck("samples", CheckStatus.Inconclusive, "没有球员样本") });
        }

        int clubReachable = 0, clubNameOk = 0, teamTypeInRange = 0, clubTeamsVectorOk = 0, chainSamples = 0;
        var tierCounts = new Dictionary<string, int>(StringComparer.Ordinal);
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

                chainSamples++;
                var teamType = _memory.Byte(team + _layout["TEAM_TYPE"]);
                if (teamType <= 20)
                {
                    teamTypeInRange++;
                    var tier = teamType == 0 ? "一线队(0)" : teamType is >= 1 and <= 9 ? $"预备/其他({teamType})" : $"青年队(≥10，实际 {teamType})";
                    tierCounts[tier] = tierCounts.GetValueOrDefault(tier) + 1;
                }

                var club = _memory.Pointer(team + _layout["TEAM_CLUB"]);
                if (!IsPlausibleHeapPointer(club))
                {
                    continue;
                }

                clubReachable++;
                if (IsSaneName(_memory.IndirectString(club + _layout["CLUB_NAME"])))
                {
                    clubNameOk++;
                }

                var begin = _memory.Pointer(club + _layout["CLUB_TEAMS_BEGIN"]);
                var end = _memory.Pointer(club + _layout["CLUB_TEAMS_END"]);
                if (begin != 0 && end > begin && end - begin <= 0x40 * 16)
                {
                    clubTeamsVectorOk++;
                }
            }
            catch (MemoryUnreadableException)
            {
                // 跳过。
            }
        }

        var checks = new List<FieldCheck>
        {
            Ratio("club.reachable", clubReachable, chainSamples == 0 ? 1 : chainSamples,
                $"当前球队 → 注册俱乐部 指针可达（可解析合同 {chainSamples} 个）"),
            Ratio("club.name", clubNameOk, Math.Max(clubReachable, 1), "注册俱乐部名称可读", 0.95),
            Ratio("club.teams_vector", clubTeamsVectorOk, Math.Max(clubReachable, 1), "俱乐部球队向量合理", 0.9),
            Ratio("team.type", teamTypeInRange, chainSamples == 0 ? 1 : chainSamples, "球队类型字节 0..20", 0.95),
            new FieldCheck("team.tiers", CheckStatus.Inconclusive,
                "样本层级分布（按上游注释归类，语义未核对）：" + string.Join(", ", tierCounts.Select(item => $"{item.Key}={item.Value}"))),
        };
        var status = checks.Any(item => item.Status == CheckStatus.Failed) ? ProbeStatus.Failed : ProbeStatus.Passed;
        return new ProbeOutcome("team_relation", status, sample.Count, checks,
            "注册俱乐部 = team→club；当前球队 = contract→team。母队/租借字段布局里不存在，只能来自 CSV。");
    }
}
