using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace ScoutMind.FMReader.Integration;

/// <summary>映射过程中发现的缺口，原样进入 <c>warnings</c>，不静默丢弃。</summary>
public sealed class MappingDiagnostics
{
    /// <summary>上游出现但 ScoutMind 没有对应字段的属性名（去重）。</summary>
    public SortedSet<string> UnmappedAttributes { get; } = new(StringComparer.Ordinal);

    /// <summary>上游出现但未建模的球员字段名（去重）。</summary>
    public SortedSet<string> IgnoredFields { get; } = new(StringComparer.Ordinal);

    /// <summary>无法解析的合同日期个数。</summary>
    public int InvalidContractDates { get; set; }

    /// <summary>无法解析出生日期的球员数。</summary>
    public int InvalidBirthDates { get; set; }

    /// <summary>没有俱乐部的球员数。</summary>
    public int PlayersWithoutClub { get; set; }

    /// <summary>带整数 <c>teamType</c> 的球员数（语义未验证，因此不使用）。</summary>
    public int PlayersWithTeamType { get; set; }

    /// <summary>没有可用身份（哨兵 / 缺失 / 非法 ID）的球员数。</summary>
    public int UnresolvedPlayers { get; set; }

    /// <summary>上游 ID 为 <c>0xFFFFFFFF</c> 的球员数。</summary>
    public int SentinelUidPlayers { get; set; }

    /// <summary>上游完全没有 id 的球员数。</summary>
    public int MissingUidPlayers { get; set; }

    /// <summary>id 存在但不是合法身份的球员数。</summary>
    public int InvalidUidPlayers { get; set; }

    /// <summary>额外告警。</summary>
    public List<string> Notes { get; } = new();
}

/// <summary>映射结果。</summary>
/// <param name="Payload">符合 ScoutMind 扫描协议的 JSON 文本。</param>
/// <param name="Players">球员数。</param>
/// <param name="Clubs">俱乐部数。</param>
/// <param name="Coverage">覆盖域。</param>
/// <param name="Warnings">告警。</param>
/// <param name="PlayersWithValidUid">拥有合法 UID 的球员数。</param>
/// <param name="PlayersUnresolved">只作为无身份观察输出的球员数。</param>
public sealed record MappedPayload(
    string Payload,
    int Players,
    int Clubs,
    IReadOnlyDictionary<string, bool> Coverage,
    IReadOnlyList<string> Warnings,
    int PlayersWithValidUid = 0,
    int PlayersUnresolved = 0);

/// <summary>
/// 把上游 FMSuperScout 的 dump（<c>meta</c> / <c>players</c> / <c>staff</c>）转换成 ScoutMind 标准扫描协议。
///
/// 三条硬规则：
/// <list type="number">
/// <item>不知道就留空：字段缺失写 <c>null</c> 或不写，绝不填 0 或猜一个值；</item>
/// <item>上游没有的数据域写进 <c>coverage=false</c> 并附告警（转会、租借、所有权、梯队）；</item>
/// <item>球员与俱乐部的关联用稳定 uid：俱乐部 uid 由名称规范化得到（与后端 ClubResolver 同一算法），
/// 因此重复扫描不会产生重复俱乐部。</item>
/// </list>
/// </summary>
public sealed partial class UpstreamDumpMapper
{
    private readonly IReadOnlyDictionary<string, string> _attributeMap;
    private readonly IReadOnlySet<string> _unmappedAttributes;
    private readonly IReadOnlySet<string> _ignoredFields;

    /// <summary>使用嵌入的属性映射表。</summary>
    public UpstreamDumpMapper()
        : this(LoadEmbeddedAttributes())
    {
    }

    /// <summary>使用给定映射（测试可注入）。</summary>
    /// <param name="attributes">上游属性名 → 协议键。</param>
    /// <param name="unmapped">已知不映射的属性名。</param>
    /// <param name="ignored">已知不建模的球员字段。</param>
    public UpstreamDumpMapper(
        IReadOnlyDictionary<string, string> attributes,
        IReadOnlySet<string>? unmapped = null,
        IReadOnlySet<string>? ignored = null)
    {
        _attributeMap = attributes ?? throw new ArgumentNullException(nameof(attributes));
        _unmappedAttributes = unmapped ?? new HashSet<string>(StringComparer.Ordinal);
        _ignoredFields = ignored ?? new HashSet<string>(StringComparer.Ordinal);
    }

    /// <summary>把上游 dump 文本映射为协议报文。</summary>
    /// <param name="dumpJson">上游 dump 的 JSON 文本。</param>
    /// <param name="game">游戏版本/构建/AppId（读取器检测结果，优先于 dump 里的值）。</param>
    /// <param name="readerVersion">读取器版本。</param>
    /// <param name="scanId">扫描 ID；为空时按 dump 内容哈希生成。</param>
    /// <returns>映射结果。</returns>
    public MappedPayload Map(string dumpJson, GameIdentity game, string readerVersion, string? scanId = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(dumpJson);
        using var document = JsonDocument.Parse(dumpJson, new JsonDocumentOptions { MaxDepth = 128 });
        var root = document.RootElement;
        var meta = root.TryGetProperty("meta", out var metaElement) && metaElement.ValueKind == JsonValueKind.Object
            ? metaElement
            : default;
        var players = root.TryGetProperty("players", out var playersElement) && playersElement.ValueKind == JsonValueKind.Array
            ? playersElement
            : default;

        var diagnostics = new MappingDiagnostics();
        var warnings = new List<string>();
        var clubs = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
        var playerNodes = new JsonArray();
        var validUidPlayers = 0;
        var unresolvedPlayers = 0;

        var myClubName = ReadString(meta, "myClub");
        string? userClubUid = null;
        if (!string.IsNullOrWhiteSpace(myClubName))
        {
            userClubUid = ClubUid(myClubName);
            clubs[userClubUid] = NewClub(userClubUid, myClubName, isUserClub: true, reputation: ReadInt(meta, "myClubRep"));
        }
        else
        {
            warnings.Add("上游没有提供主执教俱乐部（meta.myClub 为空）：需要在 ScoutMind 里手动指定本队。");
        }

        var gameDate = ReadString(meta, "gameDate");
        var generated = ReadString(meta, "generated");
        var rowIndex = 0;
        foreach (var player in players.EnumerateArray())
        {
            rowIndex++;
            if (player.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var node = MapPlayer(player, rowIndex, generated, clubs, diagnostics, userClubUid);
            if (node is null)
            {
                continue;
            }

            playerNodes.Add(node);
            if (node.ContainsKey("save_local_uid"))
            {
                validUidPlayers++;
            }
            else
            {
                unresolvedPlayers++;
            }
        }

        var coverage = BuildCoverage(players.GetArrayLength(), clubs.Count, diagnostics);
        warnings.AddRange(BuildWarnings(meta, diagnostics, coverage, players.GetArrayLength()));

        var payload = new JsonObject
        {
            ["schema_version"] = "1.1",
            ["source"] = "fm27_live_reader",
            ["reader_version"] = readerVersion,
            ["game"] = new JsonObject
            {
                ["version"] = game.Version,
                ["build"] = game.Build,
                ["app_id"] = game.AppId,
            },
            ["scan"] = new JsonObject
            {
                ["scan_id"] = scanId ?? StableScanId(game, generated, players.GetArrayLength()),
                ["observed_at"] = NormalizeTimestamp(generated),
                ["game_date"] = NormalizeDate(gameDate),
                ["user_club_uid"] = userClubUid,
            },
            ["coverage"] = ToJsonObject(coverage),
            ["warnings"] = new JsonArray(warnings.Select(static item => (JsonNode)JsonValue.Create(item)!).ToArray()),
            ["clubs"] = new JsonArray(clubs.Values.Select(static club => (JsonNode)club.DeepClone()).ToArray()),
            ["players"] = playerNodes,
            ["transfers"] = new JsonArray(),
        };

        return new MappedPayload(
            payload.ToJsonString(new JsonSerializerOptions { WriteIndented = false }),
            playerNodes.Count,
            clubs.Count,
            coverage,
            warnings,
            validUidPlayers,
            unresolvedPlayers);
    }

    private JsonObject? MapPlayer(
        JsonElement player,
        int rowIndex,
        string? dumpGenerated,
        Dictionary<string, JsonObject> clubs,
        MappingDiagnostics diagnostics,
        string? userClubUid)
    {
        var name = ReadString(player, "name");
        if (string.IsNullOrWhiteSpace(name))
        {
            diagnostics.Notes.Add($"存在没有姓名的球员行（第 {rowIndex} 行），已跳过。");
            return null;
        }

        var identity = ReadIdentity(player);
        var node = new JsonObject
        {
            ["name"] = name,
            ["birth_date"] = BirthDate(player, diagnostics),
            ["nationality"] = Nationality(player),
            ["position"] = ReadString(player, "pos"),
            ["ca"] = PositiveOrNull(player, "ca"),
            ["pa"] = PositiveOrNull(player, "pa"),
            ["market_value"] = PositiveOrNull(player, "value"),
            ["wage"] = PositiveOrNull(player, "wage"),
            ["contract_end"] = NormalizeDate(ReadString(player, "expires")) ?? InvalidContract(player, diagnostics),
            ["height_cm"] = PositiveOrNull(player, "height"),
            ["foot"] = MapFoot(ReadString(player, "foot")),
            ["world_reputation"] = ReadInt(player, "worldRep"),
        };

        if (identity.IsValid)
        {
            // 只有合法 UID 才写 save_local_uid；identity 块是新协议的显式声明，老后端仍可读旧字段。
            node["save_local_uid"] = identity.Raw;
            node["identity"] = new JsonObject
            {
                ["kind"] = "save_local_uid",
                ["value"] = identity.Raw,
            };
        }
        else
        {
            CountUnresolved(identity.Status, diagnostics);
            var evidence = new JsonObject
            {
                ["source"] = "fmsuperscout_dump",
                ["field"] = "id",
                ["row_index"] = rowIndex,
            };
            if (dumpGenerated is not null)
            {
                evidence["dump_generated"] = dumpGenerated;
            }

            var unresolved = new JsonObject
            {
                ["kind"] = "unresolved",
                ["reason"] = identity.Reason,
                ["uid_status"] = identity.StatusText,
                ["source_record_id"] = $"dump_row:{rowIndex}",
                ["evidence"] = evidence,
            };
            if (identity.Raw is not null)
            {
                unresolved["raw_uid"] = identity.Raw;
            }

            node["identity"] = unresolved;
        }

        var clubName = ReadString(player, "club");
        if (string.IsNullOrWhiteSpace(clubName))
        {
            diagnostics.PlayersWithoutClub++;
        }
        else
        {
            var clubUid = ClubUid(clubName);
            if (!clubs.TryGetValue(clubUid, out var club))
            {
                club = NewClub(clubUid, clubName, isUserClub: string.Equals(clubUid, userClubUid, StringComparison.Ordinal),
                    reputation: ReadInt(player, "clubRep"));
                clubs[clubUid] = club;
            }
            else if (ReadInt(player, "clubRep") is { } reputation
                     && (ReadNodeInt(club, "reputation") is null || ReadNodeInt(club, "reputation") < reputation))
            {
                club["reputation"] = reputation;
            }

            node["club_uid"] = clubUid;
        }

        if (ReadInt(player, "teamType") is not null)
        {
            // 上游只在有俱乐部的行给出整数 teamType；含义未验证，因此不映射成梯队，只计数。
            diagnostics.PlayersWithTeamType++;
        }

        var attributes = MapAttributes(player, diagnostics);
        if (attributes.Count > 0)
        {
            node["attributes"] = attributes;
        }

        var availability = BuildAvailability(player, attributes);
        if (availability.Count > 0)
        {
            node["availability"] = availability;
        }

        foreach (var property in player.EnumerateObject())
        {
            if (!KnownPlayerFields.Contains(property.Name))
            {
                diagnostics.IgnoredFields.Add(property.Name);
            }
        }

        return node;
    }

    private JsonObject MapAttributes(JsonElement player, MappingDiagnostics diagnostics)
    {
        var result = new JsonObject();
        if (!player.TryGetProperty("attrs", out var attrs) || attrs.ValueKind != JsonValueKind.Object)
        {
            return result;
        }

        foreach (var attribute in attrs.EnumerateObject())
        {
            if (_attributeMap.TryGetValue(attribute.Name, out var key))
            {
                if (attribute.Value.ValueKind == JsonValueKind.Number && attribute.Value.TryGetInt32(out var value))
                {
                    result[key] = value;
                }

                continue;
            }

            if (_unmappedAttributes.Contains(attribute.Name))
            {
                continue;
            }

            diagnostics.UnmappedAttributes.Add(attribute.Name);
        }

        return result;
    }

    private static JsonObject BuildAvailability(JsonElement player, JsonObject attributes)
    {
        var availability = new JsonObject();
        var hasFlag = false;
        foreach (var (field, key) in AvailabilityFields)
        {
            if (player.TryGetProperty(field, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                availability[key] = value.GetBoolean();
                hasFlag = true;
            }
        }

        if (attributes.TryGetPropertyValue("injury_proneness", out var proneness))
        {
            availability["injury_proneness"] = proneness?.DeepClone();
        }

        return hasFlag || availability.Count > 0 ? availability : new JsonObject();
    }

    private static readonly (string Field, string Key)[] AvailabilityFields =
    {
        ("listed", "listed"),
        ("loanListed", "loan_listed"),
        ("notForSale", "not_for_sale"),
        ("setForRelease", "set_for_release"),
    };

    private static readonly HashSet<string> KnownPlayerFields = new(StringComparer.Ordinal)
    {
        "id", "name", "age", "dob", "birthYear", "birthDoy", "nat", "natId", "club", "div", "ca", "pa",
        "wage", "expires", "pos", "posArr", "posNat", "foot", "height", "value", "askingPrice", "wageDemand",
        "listed", "loanListed", "notForSale", "setForRelease", "clubRep", "worldRep", "teamType", "attrs",
        "ambition", "loyalty", "professionalism", "adaptability", "pressure", "sportsmanship", "temperament",
        "controversy", "job", "jobId", "jobPrefs", "prefJob", "state", "v", "source",
    };

    private static JsonObject NewClub(string uid, string name, bool isUserClub, int? reputation)
    {
        var club = new JsonObject
        {
            ["uid"] = uid,
            ["name"] = name,
            ["is_user_club"] = isUserClub,
        };
        if (reputation is not null)
        {
            club["reputation"] = reputation.Value;
        }

        return club;
    }

    private Dictionary<string, bool> BuildCoverage(int players, int clubs, MappingDiagnostics diagnostics)
    {
        return new Dictionary<string, bool>(StringComparer.Ordinal)
        {
            ["players"] = players > 0,
            ["clubs"] = clubs > 0,
            ["identity"] = players > 0,
            ["unresolved_identity"] = players > 0,
            ["contracts"] = diagnostics.InvalidContractDates < players,
            ["teams"] = false,
            ["team_tiers"] = false,
            ["loans"] = false,
            ["ownership"] = false,
            ["agreed_transfers"] = false,
            ["transfers"] = false,
            ["statistics"] = false,
        };
    }

    private List<string> BuildWarnings(
        JsonElement meta,
        MappingDiagnostics diagnostics,
        IReadOnlyDictionary<string, bool> coverage,
        int players)
    {
        var warnings = new List<string>(diagnostics.Notes);
        if (coverage["transfers"] is false)
        {
            warnings.Add("上游 dump 不含转会历史与逐场统计：转会与表现模块只能显示已有数据。");
        }

        if (coverage["loans"] is false)
        {
            warnings.Add("上游 dump 不含 parentClub / loanClub / ownerTeamType：租借与所有权标为未知，不做推断。");
        }

        if (coverage["teams"] is false)
        {
            warnings.Add("上游 dump 不提供一线队/预备队/青年队层级：梯队归属需要导入阵容 CSV。");
        }

        if (diagnostics.PlayersWithTeamType > 0)
        {
            warnings.Add(
                $"{diagnostics.PlayersWithTeamType} 名球员带未验证的整数 teamType；含义未确认，因此没有映射成梯队。");
        }

        if (diagnostics.PlayersWithoutClub > 0)
        {
            warnings.Add($"{diagnostics.PlayersWithoutClub} 名球员没有俱乐部名称：保持为未知，不归入任何俱乐部。");
        }

        if (diagnostics.SentinelUidPlayers > 0)
        {
            warnings.Add(
                $"{diagnostics.SentinelUidPlayers} 名球员的上游 ID 是哨兵 0xFFFFFFFF（4294967295）："
                + "已按无身份观察（identity.kind=unresolved）输出，不写 save_local_uid，也不会合并成一个球员。");
        }

        if (diagnostics.MissingUidPlayers > 0)
        {
            warnings.Add($"{diagnostics.MissingUidPlayers} 名球员上游没有提供 ID：保留为无身份观察，不丢弃。");
        }

        if (diagnostics.InvalidUidPlayers > 0)
        {
            warnings.Add($"{diagnostics.InvalidUidPlayers} 名球员的 ID 不是合法身份（0 或非数字）：保留原始值并进入待确认。");
        }

        if (diagnostics.UnmappedAttributes.Count > 0)
        {
            warnings.Add($"以下属性 ScoutMind 没有对应字段，已忽略：{string.Join("、", diagnostics.UnmappedAttributes)}。");
        }

        if (diagnostics.InvalidContractDates > 0)
        {
            warnings.Add($"{diagnostics.InvalidContractDates} 条合同到期日无法解析，留空未填。");
        }

        if (diagnostics.InvalidBirthDates > 0)
        {
            warnings.Add($"{diagnostics.InvalidBirthDates} 名球员出生日期无法解析，留空未填。");
        }

        if (ReadString(meta, "versionOk") is null
            && meta.ValueKind == JsonValueKind.Object
            && meta.TryGetProperty("versionOk", out var versionOk)
            && versionOk.ValueKind == JsonValueKind.False)
        {
            warnings.Add("上游自检 versionOk=false：它按更早的版本假设解析当前游戏，字段可靠性需要复核。");
        }

        if (players == 0)
        {
            warnings.Add("本次扫描没有读到任何球员。");
        }

        return warnings;
    }

    private static string? InvalidContract(JsonElement player, MappingDiagnostics diagnostics)
    {
        if (ReadString(player, "expires") is not null)
        {
            diagnostics.InvalidContractDates++;
        }

        return null;
    }

    private string? BirthDate(JsonElement player, MappingDiagnostics diagnostics)
    {
        var year = ReadInt(player, "birthYear");
        var doy = ReadInt(player, "birthDoy");
        if (year is null || doy is null || year < 1900 || doy < 1 || doy > 366)
        {
            // 没有 birthYear/birthDoy 时尝试 dob（部分导出是年份字符串），仍不可靠则留空。
            var dob = ReadString(player, "dob");
            if (dob is not null && DateOnly.TryParseExact(dob, "yyyy-MM-dd", CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out var exact))
            {
                return exact.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
            }

            diagnostics.InvalidBirthDates++;
            return null;
        }

        try
        {
            var date = new DateTime(year.Value, 1, 1, 0, 0, 0, DateTimeKind.Unspecified)
                .AddDays(doy.Value - 1);
            if (date.Year != year.Value)
            {
                diagnostics.InvalidBirthDates++;
                return null;
            }

            return date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        }
        catch (ArgumentOutOfRangeException)
        {
            diagnostics.InvalidBirthDates++;
            return null;
        }
    }


    private static string? Nationality(JsonElement player)
    {
        if (!player.TryGetProperty("nat", out var nat))
        {
            return null;
        }

        if (nat.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in nat.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
                {
                    return item.GetString();
                }
            }

            return null;
        }

        return nat.ValueKind == JsonValueKind.String ? nat.GetString() : null;
    }

    private static int? PositiveOrNull(JsonElement element, string name)
    {
        var value = ReadInt(element, name);
        return value is > 0 ? value : null;
    }

    private static int? ReadInt(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var number) => number,
            JsonValueKind.String when int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed) => parsed,
            _ => null,
        };
    }

    private static int? ReadNodeInt(JsonObject node, string name)
    {
        if (node[name] is not JsonValue value)
        {
            return null;
        }

        return value.TryGetValue<int>(out var number) ? number : null;
    }

    /// <summary>读取上游 <c>id</c> 并判定身份；缺失、哨兵与非法值都不会被当成合法 UID。</summary>
    private static IdentityAssessment ReadIdentity(JsonElement player)
    {
        if (player.ValueKind != JsonValueKind.Object || !player.TryGetProperty("id", out var value))
        {
            return PlayerIdentityClassifier.Classify(null);
        }

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt64(out var number) => PlayerIdentityClassifier.Classify(number),
            JsonValueKind.String => PlayerIdentityClassifier.ClassifyText(value.GetString()),
            JsonValueKind.Null => PlayerIdentityClassifier.Classify(null),
            _ => new IdentityAssessment(IdentityStatus.InvalidUid, null, "invalid_uid_type"),
        };
    }

    private static void CountUnresolved(IdentityStatus status, MappingDiagnostics diagnostics)
    {
        diagnostics.UnresolvedPlayers++;
        switch (status)
        {
            case IdentityStatus.SentinelUid:
                diagnostics.SentinelUidPlayers++;
                break;
            case IdentityStatus.MissingUid:
                diagnostics.MissingUidPlayers++;
                break;
            default:
                diagnostics.InvalidUidPlayers++;
                break;
        }
    }

    private static long? ReadLong(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt64(out var number) => number,
            JsonValueKind.String when long.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed) => parsed,
            _ => null,
        };
    }

    private static string? ReadString(JsonElement element, string name)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(name, out var value))
        {
            return null;
        }

        if (value.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        var text = value.GetString();
        return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
    }

    /// <summary>上游惯用脚标签（多语言）→ 协议枚举；未知留空。</summary>
    /// <param name="value">上游标签。</param>
    /// <returns><c>right</c> / <c>left</c> / <c>both</c>；未知为 <c>null</c>。</returns>
    public static string? MapFoot(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var text = value.Trim().ToLowerInvariant();
        return text switch
        {
            "rechts" or "right" or "droit" or "derecho" or "destro" or "prawo" or "rechter" => "right",
            "links" or "left" or "gauche" or "izquierdo" or "sinistro" or "lewo" or "linker" => "left",
            "beide" or "beid" or "both" or "either" or "les deux" or "ambos" or "entrambi" or "obojetnie" or "obojętnie" => "both",
            _ => null,
        };
    }

    /// <summary>把上游日期/时间字符串规范化为 ISO 日期；无法解析时为 <c>null</c>。</summary>
    /// <param name="value">上游字符串。</param>
    /// <returns><c>yyyy-MM-dd</c> 或 <c>null</c>。</returns>
    public static string? NormalizeDate(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        var text = value.Trim();
        if (DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var exact))
        {
            return exact.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        }

        if (DateTime.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed))
        {
            return parsed.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        }

        return null;
    }

    /// <summary>把上游时间戳规范化为 ISO-8601（UTC 语义未知，因此不加 Z）。</summary>
    /// <param name="value">上游字符串。</param>
    /// <returns>ISO-8601 本地时间字符串，或当前时间。</returns>
    public static string NormalizeTimestamp(string? value)
    {
        if (!string.IsNullOrWhiteSpace(value)
            && DateTime.TryParse(value.Trim(), CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed))
        {
            return parsed.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture);
        }

        return DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture);
    }

    /// <summary>俱乐部 uid：与后端 <c>ClubResolver</c> 相同的规范化算法，保证跨语言一致。</summary>
    /// <param name="name">俱乐部名称。</param>
    /// <returns><c>name:&lt;slug&gt;</c>。</returns>
    public static string ClubUid(string name)
    {
        var normalized = NormalizeClubName(name);
        var slug = NonWord().Replace(normalized, "-").Trim('-');
        return slug.Length == 0 ? "name:unknown" : $"name:{slug}";
    }

    /// <summary>俱乐部名称归一化：去重音、去大小写、<c>&amp;</c> 归一、标点转空格、压缩空白。</summary>
    /// <param name="name">原始名称。</param>
    /// <returns>归一化名称。</returns>
    public static string NormalizeClubName(string name)
    {
        var decomposed = name.Normalize(NormalizationForm.FormKD);
        var builder = new StringBuilder(decomposed.Length);
        foreach (var ch in decomposed)
        {
            if (CharUnicodeInfo.GetUnicodeCategory(ch) == UnicodeCategory.NonSpacingMark)
            {
                continue;
            }

            builder.Append(ch);
        }

        var folded = builder.ToString().ToLowerInvariant().Replace("&", " and ", StringComparison.Ordinal);
        folded = NonWord().Replace(folded, " ");
        return Whitespace().Replace(folded, " ").Trim();
    }

    private static string StableScanId(GameIdentity game, string? generated, int players)
    {
        var seed = $"{game.AppId}|{game.Build}|{generated}|{players}";
        var bytes = System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(seed));
        return "fmreader-" + Convert.ToHexString(bytes)[..16].ToLowerInvariant();
    }

    private static JsonObject ToJsonObject(IReadOnlyDictionary<string, bool> coverage)
    {
        var node = new JsonObject();
        foreach (var (key, value) in coverage)
        {
            node[key] = value;
        }

        return node;
    }

    [GeneratedRegex("[^0-9a-z\\u4e00-\\u9fff]+", RegexOptions.CultureInvariant)]
    private static partial Regex NonWord();

    [GeneratedRegex("\\s+", RegexOptions.CultureInvariant)]
    private static partial Regex Whitespace();

    private static IReadOnlyDictionary<string, string> LoadEmbeddedAttributes()
    {
        var assembly = typeof(UpstreamDumpMapper).Assembly;
        var name = assembly.GetManifestResourceNames()
            .FirstOrDefault(item => item.EndsWith("upstream-attributes.json", StringComparison.Ordinal));
        if (name is null)
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }

        using var stream = assembly.GetManifestResourceStream(name);
        if (stream is null)
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }

        using var document = JsonDocument.Parse(stream);
        return ParseAttributes(document.RootElement);
    }

    /// <summary>解析属性映射资源（测试直接复用）。</summary>
    /// <param name="root">JSON 根元素。</param>
    /// <returns>上游名 → 协议键。</returns>
    public static IReadOnlyDictionary<string, string> ParseAttributes(JsonElement root)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        if (!root.TryGetProperty("attributes", out var attributes) || attributes.ValueKind != JsonValueKind.Object)
        {
            return result;
        }

        foreach (var property in attributes.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.String && property.Value.GetString() is { } key)
            {
                result[property.Name] = key;
            }
        }

        return result;
    }

    /// <summary>解析资源里的 <c>unmapped</c> 与 <c>ignored_fields</c>。</summary>
    /// <param name="root">JSON 根元素。</param>
    /// <returns>已知不映射的属性名与已知不建模的字段名。</returns>
    public static (IReadOnlySet<string> Unmapped, IReadOnlySet<string> Ignored) ParseKnownKeys(JsonElement root)
    {
        static HashSet<string> Read(JsonElement element, string name)
        {
            var set = new HashSet<string>(StringComparer.Ordinal);
            if (element.TryGetProperty(name, out var array) && array.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in array.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String && item.GetString() is { } text)
                    {
                        set.Add(text);
                    }
                }
            }

            return set;
        }

        return (Read(root, "unmapped"), Read(root, "ignored_fields"));
    }
}

/// <summary>游戏身份：版本、构建号、AppId。缺失值为 <c>null</c>。</summary>
/// <param name="Version">游戏版本，例如 <c>27.1</c>。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="AppId">Steam AppId。</param>
public sealed record GameIdentity(string? Version, string? Build, string? AppId);
