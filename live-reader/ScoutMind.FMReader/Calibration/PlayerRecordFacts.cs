using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 一条球员属性记录的只读字段快照。
///
/// 缺失字段必须保持 <c>null</c> 并记入 <see cref="MissingFields"/>；
/// 不允许把"读不到"默认为 0 之后当作读取成功。
/// </summary>
/// <param name="RecordPointer">记录（对象头/vtable）地址；仅本机诊断使用。</param>
/// <param name="PersonPointer">Person 子块地址；仅本机诊断使用。</param>
/// <param name="FirstName">名。</param>
/// <param name="SecondName">姓。</param>
/// <param name="CommonName">常用名。</param>
/// <param name="DateOfBirth">出生日期；读不到为 <c>null</c>。</param>
/// <param name="Ca">CA；读不到或不在合理范围为 <c>null</c>。</param>
/// <param name="Pa">PA；读不到或不在合理范围为 <c>null</c>。</param>
/// <param name="ClubName">俱乐部名称；读不到为 <c>null</c>。</param>
/// <param name="Uid">UID；读不到、为 0 或哨兵时为 <c>null</c>。</param>
/// <param name="MissingFields">缺失字段代码，例如 <c>date_of_birth</c>、<c>club</c>、<c>uid</c>。</param>
public sealed record PlayerRecordFacts(
    ulong RecordPointer,
    ulong PersonPointer,
    string? FirstName,
    string? SecondName,
    string? CommonName,
    DateOnly? DateOfBirth,
    int? Ca,
    int? Pa,
    string? ClubName,
    uint? Uid,
    IReadOnlyList<string> MissingFields);

/// <summary>读取球员属性记录的只读字段快照。</summary>
public sealed class PlayerRecordFactsReader
{
    private const uint SentinelUid = 0xFFFF_FFFF;

    private readonly IMemorySource _memory;
    private readonly ILayout _layout;

    /// <summary>创建读取器。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="layout">布局。</param>
    public PlayerRecordFactsReader(IMemorySource memory, ILayout layout)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
        _layout = layout ?? throw new ArgumentNullException(nameof(layout));
    }

    /// <summary>读取一条记录的字段；个别字段失败只记录缺失，不抛异常。</summary>
    /// <param name="record">已定位的记录。</param>
    /// <returns>字段快照。</returns>
    public PlayerRecordFacts Read(LocatedObject record)
    {
        ArgumentNullException.ThrowIfNull(record);
        var missing = new List<string>();

        var first = ReadName(record, "PERO_FIRST_NAME");
        var second = ReadName(record, "PERO_SECOND_NAME");
        var common = ReadName(record, "PERO_COMMON_NAME");
        if (first is null && second is null && common is null)
        {
            missing.Add("name");
        }

        var dateOfBirth = ReadDateOfBirth(record, missing);
        var ca = ReadRating(record, "PLAO_CA", "ca", missing);
        var pa = ReadRating(record, "PLAO_PA", "pa", missing);
        var club = ReadClub(record, missing);
        var uid = ReadUid(record, missing);

        return new PlayerRecordFacts(
            record.Address,
            record.Person,
            first,
            second,
            common,
            dateOfBirth,
            ca,
            pa,
            club,
            uid,
            missing);
    }

    private string? ReadName(LocatedObject record, string layoutKey)
    {
        try
        {
            var value = _memory.NestedString(record.Person + _layout[layoutKey]);
            if (!string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }

            return null;
        }
        catch (MemoryUnreadableException)
        {
            return null;
        }
    }

    private DateOnly? ReadDateOfBirth(LocatedObject record, List<string> missing)
    {
        try
        {
            var (year, dayOfYear) = FmDate.Decode(_memory.UInt32(record.Person + _layout["PERO_DOB"]));
            if (year is >= 1900 and <= 2100 && dayOfYear is >= 1 and <= 366)
            {
                var date = new DateTime(year, 1, 1, 0, 0, 0, DateTimeKind.Unspecified).AddDays(dayOfYear - 1);
                if (date.Year == year)
                {
                    return DateOnly.FromDateTime(date);
                }
            }
        }
        catch (MemoryUnreadableException)
        {
            // 记录缺失原因。
        }
        catch (ArgumentOutOfRangeException)
        {
            // 非法日期按缺失处理。
        }

        missing.Add("date_of_birth");
        return null;
    }

    private int? ReadRating(LocatedObject record, string layoutKey, string missingCode, List<string> missing)
    {
        int? value = null;
        try
        {
            var raw = _memory.UInt16(record.Block + _layout[layoutKey]);
            if (raw is >= 1 and <= 200)
            {
                value = raw;
            }
        }
        catch (MemoryUnreadableException)
        {
            // 记录缺失原因。
        }

        if (value is null)
        {
            missing.Add(missingCode);
        }

        return value;
    }

    private string? ReadClub(LocatedObject record, List<string> missing)
    {
        try
        {
            var contract = _memory.Pointer(record.Person + _layout["PERO_FULL_CONTRACT"]);
            if (IsPlausiblePointer(contract))
            {
                var team = _memory.Pointer(contract + _layout["CON_TEAM"]);
                if (IsPlausiblePointer(team))
                {
                    var club = _memory.Pointer(team + _layout["TEAM_CLUB"]);
                    if (IsPlausiblePointer(club))
                    {
                        var name = _memory.IndirectString(club + _layout["CLUB_NAME"]);
                        if (!string.IsNullOrWhiteSpace(name))
                        {
                            return name.Trim();
                        }
                    }
                }
            }
        }
        catch (MemoryUnreadableException)
        {
            // 记录缺失原因。
        }

        missing.Add("club");
        return null;
    }

    private uint? ReadUid(LocatedObject record, List<string> missing)
    {
        try
        {
            var offset = _layout["OBJ_DUNI"];
            if (record.Db <= ulong.MaxValue - offset)
            {
                var raw = _memory.UInt32(record.Db + offset);
                if (raw is not 0 and not SentinelUid)
                {
                    return raw;
                }
            }
        }
        catch (MemoryUnreadableException)
        {
            // 记录缺失原因。
        }

        missing.Add("uid");
        return null;
    }

    private bool IsPlausiblePointer(ulong address)
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
}
