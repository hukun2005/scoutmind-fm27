using System.Text;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>可在测试里构造的假内存：按地址写入字节，字符串用字典模拟。</summary>
internal sealed class FakeMemory : IMemorySource
{
    private readonly Dictionary<ulong, byte> _bytes = new();
    private readonly Dictionary<ulong, string> _nested = new();
    private readonly Dictionary<ulong, string> _indirect = new();

    public ulong ModuleStart { get; init; } = 0x1000_0000;
    public ulong ModuleEnd { get; init; } = 0x2000_0000;

    public void Write(ulong address, byte[] bytes)
    {
        for (var offset = 0; offset < bytes.Length; offset++)
        {
            _bytes[address + (ulong)offset] = bytes[offset];
        }
    }

    public void WriteUInt16(ulong address, ushort value) => Write(address, BitConverter.GetBytes(value));

    public void WriteUInt32(ulong address, uint value) => Write(address, BitConverter.GetBytes(value));

    public void WritePointer(ulong address, ulong value) => Write(address, BitConverter.GetBytes(value));

    public void WriteNestedString(ulong address, string value) => _nested[address] = value;

    public void WriteIndirectString(ulong address, string value) => _indirect[address] = value;

    public bool InModule(ulong address) => address >= ModuleStart && address < ModuleEnd;

    public bool IsReadable(ulong address, int length)
    {
        for (var offset = 0; offset < length; offset++)
        {
            if (!_bytes.ContainsKey(address + (ulong)offset))
            {
                return false;
            }
        }

        return true;
    }

    public byte Byte(ulong address) =>
        _bytes.TryGetValue(address, out var value) ? value : throw new MemoryUnreadableException(address);

    public ushort UInt16(ulong address)
    {
        var bytes = Read(address, 2);
        return BitConverter.ToUInt16(bytes, 0);
    }

    public uint UInt32(ulong address)
    {
        var bytes = Read(address, 4);
        return BitConverter.ToUInt32(bytes, 0);
    }

    public ulong Pointer(ulong address)
    {
        var bytes = Read(address, 8);
        return BitConverter.ToUInt64(bytes, 0);
    }

    public string? NestedString(ulong address) => _nested.TryGetValue(address, out var value) ? value : null;

    public string? IndirectString(ulong address) => _indirect.TryGetValue(address, out var value) ? value : null;

    private byte[] Read(ulong address, int length)
    {
        var buffer = new byte[length];
        for (var offset = 0; offset < length; offset++)
        {
            buffer[offset] = Byte(address + (ulong)offset);
        }

        return buffer;
    }
}

/// <summary>假定位器：直接返回构造好的对象。</summary>
internal sealed class FakeLocator : IObjectLocator
{
    public List<LocatedObject> Players { get; } = new();
    public List<LocatedObject> Clubs { get; } = new();

    public IReadOnlyList<LocatedObject> FindPlayers(ILayout layout, int max, TimeSpan budget) => Players;

    public IReadOnlyList<LocatedObject> FindClubs(ILayout layout, int max, TimeSpan budget) => Clubs;
}

/// <summary>假环境：注入 FakeMemory 与 FakeLocator。</summary>
internal sealed class FakeEnvironment : Engine.IProbeEnvironment
{
    public FakeMemory Memory { get; } = new();
    public FakeLocator Locator { get; } = new();

    public IMemorySource Open() => Memory;

    public IObjectLocator CreateLocator(IMemorySource memory) => Locator;
}

/// <summary>搭一个"结构完全自洽"的假存档，用来验证探测逻辑本身。</summary>
internal static class FakeSave
{
    public const ulong Base = 0x1100_0000;

    /// <summary>写一名结构合法的球员，返回其对象地址。</summary>
    public static LocatedObject WritePlayer(
        FakeMemory memory,
        ILayout layout,
        int index,
        ushort ca = 150,
        ushort pa = 160,
        ushort height = 183,
        int birthYear = 2000,
        int birthDoy = 40,
        string name = "Test Player",
        ulong? teamAddress = null,
        ulong? clubAddress = null,
        bool includeInTeam = true)
    {
        var address = Base + (ulong)(index * 0x2000);
        var block = address;              // BlockOffset = 0
        var person = address + 0x1000;    // PersonOffset
        var db = address + 0x1800;        // DbOff

        // 对象在堆上是连续可读的：为各基址写入零块，模拟"该地址可读"。
        memory.Write(block, new byte[0x400]);
        memory.Write(person, new byte[0x120]);
        memory.Write(db, new byte[0x20]); // 数据库块（OBJ_DUNI、PERO_GENDER 都相对它读取）

        memory.WriteUInt32(db + layout["OBJ_DUNI"], (uint)(9000 + index));
        memory.WriteUInt16(block + layout["PLAO_CA"], ca);
        memory.WriteUInt16(block + layout["PLAO_PA"], pa);
        memory.WriteUInt16(block + layout["PLAO_HEIGHT"], height);
        for (var offset = 0; offset < 15; offset++)
        {
            memory.Write(block + layout["PLAO_POSITIONS"] + (ulong)offset, new[] { (byte)(offset == 0 ? 20 : 0) });
        }

        for (var offset = 0; offset < 55; offset++)
        {
            memory.Write(block + layout["PLAO_ATTRS"] + (ulong)offset, new[] { (byte)(offset % 20) });
        }

        memory.WriteUInt32(person + layout["PERO_DOB"], ((uint)birthYear << 16) | (uint)birthDoy);
        memory.WriteNestedString(person + layout["PERO_COMMON_NAME"], name);
        memory.WritePointer(person + layout["PERO_NATION"], 0);

        var contract = address + 0x1900;
        memory.Write(contract, new byte[0x80]);
        memory.WritePointer(person + layout["PERO_FULL_CONTRACT"], contract);
        memory.WriteUInt32(contract + layout["CON_EXPIRY"], (2028u << 16) | 180u);
        memory.WriteUInt32(contract + layout["CON_WEEKLY_WAGE"], 25_000);
        memory.Write(contract + layout["CON_STATUS_FLAGS"], new byte[] { 0x01 });

        var team = teamAddress ?? address + 0x1A00;
        memory.Write(team, new byte[0x100]);
        memory.WritePointer(contract + layout["CON_TEAM"], team);
        memory.Write(team + layout["TEAM_TYPE"], new byte[] { 0x00 });
        memory.Write(team + layout["TEAM_PLAYERS_BEGIN"], BitConverter.GetBytes(team + 0x200));
        memory.Write(team + layout["TEAM_PLAYERS_END"], BitConverter.GetBytes(team + 0x208));
        memory.WritePointer(team + 0x200, address);

        var club = clubAddress ?? address + 0x1B00;
        memory.Write(club, new byte[0x100]);
        memory.WritePointer(team + layout["TEAM_CLUB"], club);
        memory.WriteIndirectString(club + layout["CLUB_NAME"], "Test FC");
        memory.WritePointer(club + layout["CLUB_TEAMS_BEGIN"], club + 0x100);
        memory.WritePointer(club + layout["CLUB_TEAMS_END"], club + 0x108);

        return new LocatedObject(address, 0, 0x1000, 0x1800);
    }

    public static LocatedObject WriteClub(FakeMemory memory, ILayout layout, int index, string name)
    {
        var address = Base + 0x400_000 + (ulong)(index * 0x1000);
        memory.Write(address, new byte[0x100]);
        memory.WriteIndirectString(address + layout["CLUB_NAME"], name);
        memory.WritePointer(address + layout["CLUB_TEAMS_BEGIN"], address + 0x100);
        memory.WritePointer(address + layout["CLUB_TEAMS_END"], address + 0x110);
        return new LocatedObject(address, 0, 0, 0);
    }
}
