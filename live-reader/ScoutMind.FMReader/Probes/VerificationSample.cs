using System.Text;
using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>一名用于人工核对的样本球员。</summary>
/// <param name="PlayerId">内存里的对象唯一 ID（OBJ_DUNI）；不是 FM 内部球员 ID。</param>
/// <param name="Name">姓名。</param>
/// <param name="BirthYear">出生年。</param>
/// <param name="Nationality">国籍名称（读不到为 <c>null</c>）。</param>
/// <param name="Positions">位置串，例如 <c>MC/AMC</c>。</param>
/// <param name="Ca">当前能力（仅作参考，游戏 UI 不可见）。</param>
/// <param name="Pa">潜在能力（同上）。</param>
/// <param name="Height">身高（cm）。</param>
/// <param name="Attributes">抽样属性（实际值，非 ×5）。</param>
/// <param name="ClubName">注册俱乐部（team → club）。</param>
/// <param name="TeamType">球队类型字节（上游注释：0 = 一线队）。</param>
/// <param name="ContractYear">合同到期年。</param>
/// <param name="AgeGroup">年龄分组，用于挑选样本。</param>
public sealed record VerificationPlayer(
    uint PlayerId,
    string Name,
    int BirthYear,
    string? Nationality,
    string Positions,
    int Ca,
    int Pa,
    int Height,
    IReadOnlyDictionary<string, int> Attributes,
    string? ClubName,
    int TeamType,
    int? ContractYear,
    string AgeGroup);

/// <summary>
/// 独立验证样本：从真实内存里挑 30 名球员，覆盖不同年龄、位置与球队层级，
/// 输出一份可以拿游戏界面逐项核对的最小清单。
///
/// 选样规则公开：先按年龄分组、再按位置分组、最后按球队层级补充，避免"只挑明星"。
/// </summary>
public static class VerificationSample
{
    /// <summary>从已读取的行里挑选样本。</summary>
    /// <param name="candidates">候选（真实内存读取结果）。</param>
    /// <param name="target">目标数量，默认 30。</param>
    /// <returns>挑选结果（可能不足 30，如实返回）。</returns>
    public static IReadOnlyList<VerificationPlayer> Select(IReadOnlyList<VerificationPlayer> candidates, int target = 30)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        var picked = new List<VerificationPlayer>();
        var seen = new HashSet<uint>();

        void Take(IEnumerable<VerificationPlayer> source, int max)
        {
            foreach (var player in source)
            {
                if (picked.Count >= target || max-- <= 0)
                {
                    return;
                }

                if (seen.Add(player.PlayerId))
                {
                    picked.Add(player);
                }
            }
        }

        // 1) 年龄覆盖：每个年龄组至少 4 人。
        foreach (var group in new[] { "U21", "22-27", "28-33", "34+" })
        {
            Take(candidates.Where(item => item.AgeGroup == group), 4);
        }

        // 2) 位置覆盖：门将/后卫/中场/前锋各补 2 人。
        foreach (var prefix in new[] { "GK", "D", "M", "S" })
        {
            Take(candidates.Where(item => item.Positions.StartsWith(prefix, StringComparison.Ordinal)), 2);
        }

        // 3) 球队层级覆盖：一线队 / 预备 / 青年 各补 2 人。
        foreach (var selector in new Func<VerificationPlayer, bool>[]
                 {
                     item => item.TeamType == 0,
                     item => item.TeamType is >= 1 and <= 9,
                     item => item.TeamType >= 10,
                 })
        {
            Take(candidates.Where(selector), 2);
        }

        // 4) 有俱乐部的样本补足（人工核对时俱乐部最容易对照）。
        foreach (var player in candidates.Where(item => !string.IsNullOrWhiteSpace(item.ClubName)))
        {
            if (picked.Count >= target)
            {
                break;
            }

            if (seen.Add(player.PlayerId))
            {
                picked.Add(player);
            }
        }

        // 5) 仍不足则按顺序补齐。
        foreach (var player in candidates)
        {
            if (picked.Count >= target)
            {
                break;
            }

            if (seen.Add(player.PlayerId))
            {
                picked.Add(player);
            }
        }

        return picked;
    }

    /// <summary>生成 Markdown 清单。</summary>
    /// <param name="players">样本。</param>
    /// <param name="build">构建号。</param>
    /// <param name="pluginVersion">插件版本。</param>
    /// <returns>Markdown 文本。</returns>
    public static string ToMarkdown(IReadOnlyList<VerificationPlayer> players, string? build, string? pluginVersion)
    {
        ArgumentNullException.ThrowIfNull(players);
        var text = new StringBuilder();
        text.AppendLine("# 人工核对清单（FM27 27.1）");
        text.AppendLine();
        text.AppendLine($"- Build：{build ?? "(未知)"}");
        text.AppendLine($"- game_plugin.dll：{pluginVersion ?? "(未知)"}");
        text.AppendLine($"- 样本数：{players.Count}");
        text.AppendLine("- 说明：CA/PA 在游戏界面不可见，**不能**用本清单把它们标成“游戏界面已验证”；");
        text.AppendLine("  可核对的是姓名、俱乐部、位置、国籍、身高、合同到期、号码。");
        text.AppendLine();
        text.AppendLine("| # | 姓名 | 出生年 | 国籍 | 位置 | 俱乐部 | 身高 | 合同到 | CA/PA | 球队层级字节 | 核对结果 |");
        text.AppendLine("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |");
        var index = 0;
        foreach (var player in players)
        {
            index++;
            text.AppendLine($"| {index} | {player.Name} | {player.BirthYear} | {player.Nationality ?? "?"} | {player.Positions} | " +
                            $"{player.ClubName ?? "(无)"} | {player.Height} | {(player.ContractYear?.ToString() ?? "-")} | " +
                            $"{player.Ca}/{player.Pa} | {player.TeamType} | |");
        }

        text.AppendLine();
        text.AppendLine("## 属性抽样（实际值）");
        text.AppendLine();
        text.AppendLine("| 姓名 | 技术(Passing/Finishing/Tackling) | 精神(Determination/WorkRate) | 身体(Pace/Strength) |");
        text.AppendLine("| --- | --- | --- | --- |");
        foreach (var player in players)
        {
            text.AppendLine($"| {player.Name} | " +
                            $"{Attr(player, "Passing")}/{Attr(player, "Finishing")}/{Attr(player, "Tackling")} | " +
                            $"{Attr(player, "Determination")}/{Attr(player, "WorkRate")} | " +
                            $"{Attr(player, "Pace")}/{Attr(player, "Strength")} |");
        }

        return text.ToString();
    }

    private static string Attr(VerificationPlayer player, string key) =>
        player.Attributes.TryGetValue(key, out var value) ? value.ToString() : "?";
}

/// <summary>从内存读取样本行（与探测共享同一个只读内存源）。</summary>
public sealed class VerificationReader
{
    private readonly IMemorySource _memory;
    private readonly ILayout _layout;

    /// <summary>创建读取器。</summary>
    /// <param name="memory">内存源。</param>
    /// <param name="layout">布局。</param>
    public VerificationReader(IMemorySource memory, ILayout layout)
    {
        _memory = memory;
        _layout = layout;
    }

    /// <summary>读取一行；读不到关键字段时返回 <c>null</c>。</summary>
    /// <param name="player">定位到的对象。</param>
    /// <returns>样本行或 <c>null</c>。</returns>
    public VerificationPlayer? Read(LocatedObject player)
    {
        ArgumentNullException.ThrowIfNull(player);
        try
        {
            var name = _memory.NestedString(player.Person + _layout["PERO_COMMON_NAME"])
                       ?? string.Join(" ", new[]
                       {
                           _memory.NestedString(player.Person + _layout["PERO_FIRST_NAME"]),
                           _memory.NestedString(player.Person + _layout["PERO_SECOND_NAME"]),
                       }.Where(part => !string.IsNullOrWhiteSpace(part)));
            if (string.IsNullOrWhiteSpace(name))
            {
                return null;
            }

            var birth = FmDate.Decode(_memory.UInt32(player.Person + _layout["PERO_DOB"]));
            var ca = _memory.UInt16(player.Block + _layout["PLAO_CA"]);
            var pa = _memory.UInt16(player.Block + _layout["PLAO_PA"]);
            if (ca is < 1 or > 200)
            {
                return null;
            }

            var positions = ReadPositions(player);
            var attributes = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var key in new[] { "Passing", "Finishing", "Tackling", "Determination", "WorkRate", "Pace", "Strength" })
            {
                if (AttributeMap.TryGet(key, out var offset))
                {
                    attributes[key] = _memory.Byte(player.Block + _layout["PLAO_ATTRS"] + (uint)offset) / 5;
                }
            }

            var contractYear = (int?)null;
            var teamType = -1;
            string? clubName = null;
            var contract = _memory.Pointer(player.Person + _layout["PERO_FULL_CONTRACT"]);
            if (contract != 0 && _memory.IsReadable(contract + _layout["CON_EXPIRY"], 4))
            {
                var expiry = FmDate.Decode(_memory.UInt32(contract + _layout["CON_EXPIRY"]));
                if (expiry.Year != 0)
                {
                    contractYear = expiry.Year;
                }

                var team = _memory.Pointer(contract + _layout["CON_TEAM"]);
                if (team != 0 && _memory.IsReadable(team + _layout["TEAM_CLUB"], 8))
                {
                    teamType = _memory.Byte(team + _layout["TEAM_TYPE"]);
                    var club = _memory.Pointer(team + _layout["TEAM_CLUB"]);
                    if (club != 0)
                    {
                        clubName = _memory.IndirectString(club + _layout["CLUB_NAME"]);
                    }
                }
            }

            var nation = _memory.Pointer(player.Person + _layout["PERO_NATION"]);
            var nationality = nation == 0
                ? null
                : _memory.IndirectString(nation + _layout["NATION_NAME"])
                  ?? _memory.IndirectString(nation + _layout["NATION_SHORT_NAME"]);

            var ageGroup = birth.Year switch
            {
                0 => "unknown",
                var year when year >= DateTime.UtcNow.Year - 21 => "U21",
                var year when year >= DateTime.UtcNow.Year - 27 => "22-27",
                var year when year >= DateTime.UtcNow.Year - 33 => "28-33",
                _ => "34+",
            };

            return new VerificationPlayer(
                PlayerId: _memory.UInt32(player.Db + _layout["OBJ_DUNI"]),
                Name: name!,
                BirthYear: birth.Year,
                Nationality: nationality,
                Positions: positions,
                Ca: ca,
                Pa: pa,
                Height: _memory.UInt16(player.Block + _layout["PLAO_HEIGHT"]),
                Attributes: attributes,
                ClubName: clubName,
                TeamType: teamType,
                ContractYear: contractYear,
                AgeGroup: ageGroup);
        }
        catch (MemoryUnreadableException)
        {
            return null;
        }
    }

    private string ReadPositions(LocatedObject player)
    {
        var parts = new List<string>();
        foreach (var (key, offset) in FieldSpecs.Positions)
        {
            if (_memory.Byte(player.Block + _layout["PLAO_POSITIONS"] + (uint)offset) >= 15)
            {
                parts.Add(key);
            }
        }

        return parts.Count == 0 ? "?" : string.Join("/", parts);
    }
}
