namespace ScoutMind.FMReader.Probes;

/// <summary>一段可读内存区域（起止地址由上游扫描器给出）。</summary>
/// <param name="Start">起始地址。</param>
/// <param name="Size">字节数。</param>
public sealed record MemoryRegion(ulong Start, ulong Size);

/// <summary>只读内存访问。真实实现包住上游 <c>MemScan</c>，测试用假实现。</summary>
public interface IMemorySource
{
    /// <summary>可读内存区域；不支持枚举时返回空列表（调用方必须安全降级）。</summary>
    IReadOnlyList<MemoryRegion> Regions => Array.Empty<MemoryRegion>();

    /// <summary>批量读取一个区块。</summary>
    /// <param name="address">起始地址。</param>
    /// <param name="buffer">目标缓冲区。</param>
    /// <param name="length">要读取的字节数。</param>
    /// <returns>读成功为 <c>true</c>；不可读或越界为 <c>false</c>。</returns>
    bool TryReadBlock(ulong address, byte[] buffer, int length)
    {
        if (length > buffer.Length || !IsReadable(address, length))
        {
            return false;
        }

        for (var offset = 0; offset < length; offset++)
        {
            buffer[offset] = Byte(address + (ulong)offset);
        }

        return true;
    }

    /// <summary>地址是否落在游戏模块内（game_plugin / GameAssembly）。</summary>
    /// <param name="address">地址。</param>
    /// <returns>在模块内为 <c>true</c>。</returns>
    bool InModule(ulong address);

    /// <summary>该地址区间是否可读。</summary>
    /// <param name="address">起始地址。</param>
    /// <param name="length">字节数。</param>
    /// <returns>可读为 <c>true</c>。</returns>
    bool IsReadable(ulong address, int length);

    /// <summary>读 1 字节。</summary>
    /// <param name="address">地址。</param>
    /// <returns>值；不可读时抛 <see cref="MemoryUnreadableException"/>。</returns>
    byte Byte(ulong address);

    /// <summary>读 2 字节。</summary>
    /// <param name="address">地址。</param>
    /// <returns>值。</returns>
    ushort UInt16(ulong address);

    /// <summary>读 4 字节。</summary>
    /// <param name="address">地址。</param>
    /// <returns>值。</returns>
    uint UInt32(ulong address);

    /// <summary>读 8 字节指针。</summary>
    /// <param name="address">地址。</param>
    /// <returns>值。</returns>
    ulong Pointer(ulong address);

    /// <summary>读"嵌套字符串"（上游对姓名的读取方式）。</summary>
    /// <param name="address">字段地址。</param>
    /// <returns>字符串；读不到为 <c>null</c>。</returns>
    string? NestedString(ulong address);

    /// <summary>读"间接字符串"（上游对俱乐部/联赛名称的读取方式）。</summary>
    /// <param name="address">字段地址。</param>
    /// <returns>字符串；读不到为 <c>null</c>。</returns>
    string? IndirectString(ulong address);
}

/// <summary>内存不可读。</summary>
public sealed class MemoryUnreadableException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="address">不可读地址。</param>
    public MemoryUnreadableException(ulong address)
        : base($"地址 0x{address:X} 不可读")
    {
        Address = address;
    }

    /// <summary>不可读地址。</summary>
    public ulong Address { get; }
}
