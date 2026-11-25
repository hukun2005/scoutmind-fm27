using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Integration;

/// <summary>
/// 一个"没有可用 UID"的球员对象，来自读取器自己的对象枚举，而不是上游 dump。
/// 它只携带观察证据：哨兵/零值、对象序号、可读到的姓名与 CA/PA。
/// 不包含对象地址，避免把内存布局写进上传报文。
/// </summary>
/// <param name="Name">姓名；读不到时不生成该行。</param>
/// <param name="Ca">当前能力。</param>
/// <param name="Pa">潜在能力。</param>
/// <param name="BirthDate">生日（YYYY-MM-DD）。</param>
/// <param name="UidStatus">sentinel / invalid。</param>
/// <param name="RawUid">原始 UID 的十进制文本。</param>
/// <param name="Reason">原因码。</param>
/// <param name="SourceRecordId">稳定来源标识（对象序号）。</param>
public sealed record UnresolvedObjectRow(
    string Name,
    int? Ca,
    int? Pa,
    string? BirthDate,
    string UidStatus,
    string RawUid,
    string Reason,
    string SourceRecordId);

/// <summary>
/// 从对象枚举里补齐上游 dump 不会导出的无 UID 球员，并把它们合并进扫描报文。
///
/// 上游只导出"有身份"的球员，因此只依赖 dump 时真实数据永远看不到哨兵自由球员；
/// 这里用读取器自己的 vtable 枚举补上这些对象，并明确标记为 unresolved 观察。
/// </summary>
public static class UnresolvedObjectCollector
{
    /// <summary>FM 的哨兵 UID。</summary>
    public const uint SentinelUid = 0xFFFFFFFF;

    /// <summary>枚举上限；只是防御性上限，正常存档远低于它。</summary>
    public const int DefaultMaxObjects = 200_000;

    /// <summary>
    /// 枚举球员对象并挑出没有可用 UID 的那些。读到 UID 但合法的对象交给 dump，不在这里重复输出。
    /// </summary>
    /// <param name="locator">对象定位器。</param>
    /// <param name="memory">内存源。</param>
    /// <param name="layout">布局。</param>
    /// <param name="max">最多枚举的对象数。</param>
    /// <param name="budget">枚举时间预算。</param>
    /// <param name="readable">成功读到 UID 的对象数。</param>
    /// <param name="diagnostic">需要写入扫描告警的说明；没有异常时为 <c>null</c>。</param>
    /// <returns>无 UID 对象行。</returns>
    public static IReadOnlyList<UnresolvedObjectRow> Collect(
        IObjectLocator locator,
        IMemorySource memory,
        ILayout layout,
        int max,
        TimeSpan budget,
        out int readable,
        out string? diagnostic)
    {
        ArgumentNullException.ThrowIfNull(locator);
        ArgumentNullException.ThrowIfNull(memory);
        ArgumentNullException.ThrowIfNull(layout);

        var rows = new List<UnresolvedObjectRow>();
        readable = 0;
        diagnostic = null;
        var located = locator.FindPlayers(layout, Math.Max(1, max), budget);
        var index = 0;
        var unnamed = 0;
        foreach (var player in located)
        {
            index++;
            uint uid;
            try
            {
                uid = memory.UInt32(player.Db + layout["OBJ_DUNI"]);
            }
            catch (MemoryUnreadableException)
            {
                continue;
            }

            readable++;
            string status;
            string reason;
            if (uid == SentinelUid)
            {
                status = "sentinel";
                reason = "sentinel_uid";
            }
            else if (uid == 0)
            {
                status = "invalid";
                reason = "zero_uid";
            }
            else
            {
                continue;
            }

            string name;
            try
            {
                name = memory.NestedString(player.Person + layout["PERO_COMMON_NAME"]);
            }
            catch (MemoryUnreadableException)
            {
                name = string.Empty;
            }

            if (string.IsNullOrWhiteSpace(name))
            {
                // 没有姓名就没有可展示的观察：不编造 "未知球员"，只计数。
                unnamed++;
                continue;
            }

            int? ca = null;
            int? pa = null;
            string? birthDate = null;
            try
            {
                ca = memory.UInt16(player.Block + layout["PLAO_CA"]);
                pa = memory.UInt16(player.Block + layout["PLAO_PA"]);
                var (year, doy) = FmDate.Decode(memory.UInt32(player.Person + layout["PERO_DOB"]));
                if (year is >= 1940 and <= 2015 && doy is >= 1 and <= 366)
                {
                    birthDate = new DateTime(year, 1, 1, 0, 0, 0, DateTimeKind.Unspecified)
                        .AddDays(doy - 1)
                        .ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                }
            }
            catch (MemoryUnreadableException)
            {
                // 字段缺失时保留行：身份状态本身仍然有诊断价值。
            }

            rows.Add(new UnresolvedObjectRow(
                Name: name.Trim(),
                Ca: ca is >= 1 and <= 200 ? ca : null,
                Pa: pa is >= 1 and <= 200 ? pa : null,
                BirthDate: birthDate,
                UidStatus: status,
                RawUid: uid.ToString(CultureInfo.InvariantCulture),
                Reason: reason,
                SourceRecordId: $"reader_object:player:{index}"));
        }

        if (unnamed > 0)
        {
            diagnostic = $"对象枚举：{unnamed} 个无 UID 对象没有可读姓名，未作为观察输出。";
        }

        return rows;
    }

    /// <summary>把无 UID 观察合并进扫描报文的 <c>players</c> 数组。</summary>
    /// <param name="payloadJson">上游映射产物。</param>
    /// <param name="rows">要追加的观察。</param>
    /// <param name="readerVersion">读取器版本，写入证据。</param>
    /// <returns>新的 JSON 文本。</returns>
    public static string Merge(string payloadJson, IReadOnlyList<UnresolvedObjectRow> rows, string readerVersion)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(payloadJson);
        ArgumentNullException.ThrowIfNull(rows);
        if (rows.Count == 0)
        {
            return payloadJson;
        }

        JsonNode? node;
        try
        {
            node = JsonNode.Parse(payloadJson);
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException($"扫描报文不是合法 JSON：{ex.Message}", ex);
        }

        if (node is not JsonObject root || root["players"] is not JsonArray players)
        {
            throw new InvalidDataException("扫描报文缺少 players 数组");
        }

        foreach (var row in rows)
        {
            players.Add(new JsonObject
            {
                ["name"] = row.Name,
                ["record_id"] = row.SourceRecordId,
                ["birth_date"] = row.BirthDate,
                ["nationality"] = null,
                ["position"] = null,
                ["club_uid"] = null,
                ["ca"] = row.Ca,
                ["pa"] = row.Pa,
                ["contract_end"] = null,
                ["attributes"] = new JsonObject(),
                ["identity"] = new JsonObject
                {
                    ["kind"] = "unresolved",
                    ["reason"] = row.Reason,
                    ["uid_status"] = row.UidStatus,
                    ["raw_uid"] = row.RawUid,
                    ["source_record_id"] = row.SourceRecordId,
                    ["evidence"] = new JsonObject
                    {
                        ["source"] = "reader_object_enumeration",
                        ["reader_version"] = readerVersion,
                        ["object_index"] = row.SourceRecordId,
                        ["note"] = "上游 dump 未导出该对象；由读取器对象枚举补齐",
                    },
                },
            });
        }

        return root.ToJsonString();
    }
}
