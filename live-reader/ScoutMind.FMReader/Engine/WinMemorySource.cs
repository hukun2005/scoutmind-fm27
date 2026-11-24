using FMSuperScout;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Engine;

/// <summary>
/// 对上游只读内存访问的包装：所有读取都经过 <c>ReadProcessMemory</c>，不写入、不注入。
/// </summary>
public sealed class WinMemorySource : IMemorySource, IDisposable
{
    private readonly GameProcess _game;
    private readonly MemScan _scan;

    private WinMemorySource(GameProcess game, MemScan scan)
    {
        _game = game;
        _scan = scan;
    }

    /// <summary>打开当前定位到的 fm.exe。</summary>
    /// <returns>内存源。</returns>
    /// <exception cref="Probes.MemoryUnreadableException">无法打开进程。</exception>
    public static WinMemorySource Open()
    {
        var location = new FmProcessLocator().Locate();
        if (location.ProcessId is null)
        {
            throw new MemoryUnreadableException(0);
        }

        System.Diagnostics.Process process;
        try
        {
            process = System.Diagnostics.Process.GetProcessById(location.ProcessId.Value);
        }
        catch (ArgumentException)
        {
            throw new MemoryUnreadableException(0);
        }

        GameProcess game;
        try
        {
            game = GameProcess.Open(process);
        }
        catch (System.ComponentModel.Win32Exception)
        {
            throw new MemoryUnreadableException(0);
        }

        return new WinMemorySource(game, new MemScan(game));
    }

    /// <summary>底层扫描对象（定位器复用）。</summary>
    internal MemScan Scan => _scan;

    /// <summary>底层游戏进程（定位器复用）。</summary>
    internal GameProcess Game => _game;

    /// <inheritdoc />
    public IReadOnlyList<MemoryRegion> Regions =>
        _scan.ScanRegions.Select(static item => new MemoryRegion(item.start, item.size)).ToArray();

    /// <inheritdoc />
    public bool TryReadBlock(ulong address, byte[] buffer, int length) =>
        length > 0 && length <= buffer.Length && _scan.ReadBlock(address, buffer, length);

    /// <inheritdoc />
    public bool InModule(ulong address) => _scan.InGp(address) || _scan.InGa(address);

    /// <inheritdoc />
    public bool IsReadable(ulong address, int length)
    {
        if (address == 0 || length <= 0)
        {
            return false;
        }

        var buffer = new byte[length];
        return _scan.ReadBlock(address, buffer, length);
    }

    /// <inheritdoc />
    public byte Byte(ulong address)
    {
        var buffer = new byte[1];
        return _scan.ReadBlock(address, buffer, 1) ? buffer[0] : throw new MemoryUnreadableException(address);
    }

    /// <inheritdoc />
    public ushort UInt16(ulong address)
    {
        var buffer = new byte[2];
        return _scan.ReadBlock(address, buffer, 2)
            ? BitConverter.ToUInt16(buffer, 0)
            : throw new MemoryUnreadableException(address);
    }

    /// <inheritdoc />
    public uint UInt32(ulong address)
    {
        var buffer = new byte[4];
        return _scan.ReadBlock(address, buffer, 4)
            ? BitConverter.ToUInt32(buffer, 0)
            : throw new MemoryUnreadableException(address);
    }

    /// <inheritdoc />
    public ulong Pointer(ulong address)
    {
        var buffer = new byte[8];
        return _scan.ReadBlock(address, buffer, 8)
            ? BitConverter.ToUInt64(buffer, 0)
            : throw new MemoryUnreadableException(address);
    }

    /// <inheritdoc />
    public string? NestedString(ulong address) => _scan.NestedString(address);

    /// <inheritdoc />
    public string? IndirectString(ulong address) => _scan.IndirectString(address);

    /// <inheritdoc />
    public void Dispose()
    {
        _scan.ReleaseSnapshot();
        _game.Dispose();
    }
}

/// <summary>打开只读内存的工厂；测试用假实现代替真实进程。</summary>
public interface IProbeEnvironment
{
    /// <summary>打开内存源。</summary>
    /// <returns>内存源。</returns>
    IMemorySource Open();

    /// <summary>创建对象定位器。</summary>
    /// <param name="memory">内存源。</param>
    /// <returns>定位器。</returns>
    IObjectLocator CreateLocator(IMemorySource memory);
}

/// <summary>默认环境：真实 fm.exe 进程 + 堆扫描。</summary>
public sealed class WinMemoryEnvironment : IProbeEnvironment
{
    /// <inheritdoc />
    public IMemorySource Open() => WinMemorySource.Open();

    /// <inheritdoc />
    public IObjectLocator CreateLocator(IMemorySource memory) => new HeapObjectLocator((WinMemorySource)memory);
}

/// <summary>
/// 有界对象定位：按上游的分类器在堆里找对象，只收集少量样本，并且有时间预算。
///
/// 这里只做"定位 + 分类"，不做字段解读——字段正确性由 <see cref="ObjectProbes"/> 判断。
/// </summary>
public sealed class HeapObjectLocator : IObjectLocator
{
    private readonly WinMemorySource _memory;

    /// <summary>创建定位器。</summary>
    /// <param name="memory">内存源。</param>
    public HeapObjectLocator(WinMemorySource memory)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
    }

    /// <inheritdoc />
    public IReadOnlyList<LocatedObject> FindPlayers(ScoutMind.FMReader.Layouts.ILayout layout, int max, TimeSpan budget) =>
        ScanFor(ObjKind.Player, max, budget);

    /// <inheritdoc />
    public IReadOnlyList<LocatedObject> FindClubs(ScoutMind.FMReader.Layouts.ILayout layout, int max, TimeSpan budget) =>
        ScanFor(ObjKind.Club, max, budget);

    private List<LocatedObject> ScanFor(ObjKind kind, int max, TimeSpan budget)
    {
        var found = new List<LocatedObject>(max);
        var scan = _memory.Scan;
        var deadline = DateTime.UtcNow + budget;
        var buffer = new byte[1 << 20];
        var fields = Fields.FM27; // 仅用于 vtable → 类别分类（结构判断），字段偏移来自 ScoutMind 布局。

        foreach (var (start, size) in scan.ScanRegions)
        {
            if (size < 0x40)
            {
                continue;
            }

            ulong scanned = 0;
            while (scanned < size)
            {
                if (DateTime.UtcNow > deadline || found.Count >= max)
                {
                    return found;
                }

                var want = (int)Math.Min((ulong)buffer.Length, size - scanned);
                var chunkBase = start + scanned;
                if (!scan.ReadBlock(chunkBase, buffer, want))
                {
                    scanned += (ulong)Math.Min(1 << 20, want);
                    continue;
                }

                for (var offset = 0; offset + 0x10 <= want; offset += 8)
                {
                    var vtable = BitConverter.ToUInt64(buffer, offset);
                    if (!scan.InGp(vtable) && !scan.InGa(vtable))
                    {
                        continue;
                    }

                    var address = chunkBase + (ulong)offset;
                    var cls = scan.Classify(vtable, address, fields);
                    if (cls is null || cls.Kind != kind)
                    {
                        continue;
                    }

                    found.Add(new LocatedObject(address, cls.BlockOff, cls.PersonOff, cls.DbOff));
                    if (found.Count >= max)
                    {
                        return found;
                    }

                    offset += 0x10; // 同一对象内部不可能再次命中 vtable，跳过紧邻位置
                }

                scanned += (ulong)want;
            }
        }

        return found;
    }
}
