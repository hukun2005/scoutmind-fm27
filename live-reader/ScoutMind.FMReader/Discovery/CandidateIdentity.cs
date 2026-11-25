using System.Buffers.Binary;
using System.Security.Cryptography;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>
/// 候选的逻辑身份：与“当前进程里的绝对地址”分离。
///
/// 结构指纹只使用日期字段前后的结构字节与所属模块，<b>不包含日期值本身</b>；
/// 因此同一个逻辑对象在游戏推进日期后指纹不变，而游戏重启导致地址变化时仍可重新关联。
/// 仅靠日期值相同的候选不会被赋予稳定身份，仍保持低可信度。
///
/// 指纹版本 2 起对结构窗口内的“用户态指针”做归一化：命中指针形态的 8 字节被替换为固定标记，
/// 使 ASLR / 堆分配变化不会改变逻辑身份；标量字段仍逐字节参与哈希，结构不同必然指纹不同。
/// </summary>
public static class CandidateIdentity
{
    /// <summary>结构指纹版本；参与逻辑签名，旧版本证据不会与新版本混用。</summary>
    public const int FingerprintVersion = 2;

    /// <summary>日期字段之前的结构头长度（等于 <see cref="WorldDateLocator.DateFieldOffset"/>）。</summary>
    public const int HeaderLength = WorldDateLocator.DateFieldOffset;

    /// <summary>日期字段之后参与指纹的起始偏移：跳过日期（+0x0）与参考日期（+0x4）。</summary>
    public const int TailStart = 0x08;

    /// <summary>
    /// 日期字段之后参与指纹的尾部长度。取 0x50 覆盖 [date+0x08, date+0x58)，
    /// 既包含哨兵/零字段之后的标量（如对象 ID），又尽量留在候选自身的记录内，
    /// 避免把相邻记录的日期/引用日期算进指纹（相邻记录会随日历数据滚动）。
    /// </summary>
    public const int TailLength = 0x50;

    /// <summary>指纹摘要截断字节数（十六进制 16 字符）。</summary>
    public const int DigestBytes = 8;

    /// <summary>指针归一化标记（8 字节，长度与指针一致以保持后续字段偏移不变）。</summary>
    private static readonly byte[] PointerMarker = { 0x00, (byte)'P', (byte)'T', (byte)'R', (byte)'8', 0x00, 0x00, 0x00 };

    /// <summary>判断候选所属模块类别：<c>module</c>（游戏模块内）或 <c>heap</c>。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="address">候选地址。</param>
    /// <returns>模块类别。</returns>
    public static string ModuleOf(IMemorySource memory, ulong address)
    {
        ArgumentNullException.ThrowIfNull(memory);
        return memory.InModule(address) ? "module" : "heap";
    }

    /// <summary>
    /// 计算结构指纹：模块类别 + 结构头 [base, date) + 日期之后 [date+0x08, date+0x08+TailLength)。
    /// 日期字段（+0x0）与其后的参考日期（+0x4）都被刻意排除，避免“日期一变身份就变”；
    /// 结构窗口内的用户态指针被替换为固定标记，避免跨进程堆地址变化改变身份。
    /// </summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="dateAddress">日期字段地址。</param>
    /// <param name="module">模块类别。</param>
    /// <returns>指纹（小写十六进制）。</returns>
    public static string ComputeFingerprint(IMemorySource memory, ulong dateAddress, string module)
    {
        ArgumentNullException.ThrowIfNull(memory);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        hash.AppendData(System.Text.Encoding.UTF8.GetBytes(module));
        hash.AppendData(new[] { (byte)FingerprintVersion });

        var header = new byte[HeaderLength];
        var headerAddress = dateAddress - HeaderLength;
        var headerReadable = memory.TryReadBlock(headerAddress, header, header.Length);
        if (headerReadable)
        {
            MaskPointers(memory, header, headerAddress, dateAddress);
        }

        hash.AppendData(headerReadable ? header : Array.Empty<byte>());

        var tail = new byte[TailLength];
        var tailAddress = dateAddress + TailStart;
        var tailReadable = memory.TryReadBlock(tailAddress, tail, tail.Length);
        if (tailReadable)
        {
            MaskPointers(memory, tail, tailAddress, dateAddress);
        }

        hash.AppendData(tailReadable ? tail : Array.Empty<byte>());

        // 把“哪些区段可读”也纳入指纹：结构损坏时指纹必须变化，不能与前一次悄悄相等。
        hash.AppendData(new[] { (byte)(headerReadable ? 1 : 0), (byte)(tailReadable ? 1 : 0) });
        var digest = hash.GetHashAndReset();
        return Convert.ToHexString(digest.AsSpan(0, DigestBytes)).ToLowerInvariant();
    }

    /// <summary>逻辑签名：模块类别 + 指纹版本 + 结构指纹。</summary>
    /// <param name="module">模块类别。</param>
    /// <param name="fingerprint">结构指纹。</param>
    /// <returns>逻辑签名，形如 <c>heap:v2:0123456789abcdef</c>。</returns>
    public static string ComputeLogicalSignature(string module, string fingerprint) =>
        $"{module}:v{FingerprintVersion}:{fingerprint}";

    /// <summary>把地址格式化为十六进制字符串。</summary>
    /// <param name="value">地址。</param>
    /// <returns>形如 <c>0x7FF6...</c> 的文本。</returns>
    public static string Hex(ulong value) => $"0x{value:X}";

    /// <summary>
    /// 就地归一化指针：以 4 字节为步长扫描（相对日期字段的偏移固定，
    /// 因此与候选自身在堆上的绝对对齐无关），把“指针形态且目标可读”的 8 字节替换为固定标记。
    /// 目标可读性校验很关键：相邻两个 32 位标量拼成的 8 字节可能凑出指针形态
    /// （如 <c>0x0001060900000000</c>），若整段屏蔽就会抹掉区分不同对象的字段。
    /// </summary>
    /// <param name="memory">只读内存源（用于校验指针目标是否可读）。</param>
    /// <param name="buffer">窗口字节。</param>
    /// <param name="blockAddress">窗口起始绝对地址。</param>
    /// <param name="dateAddress">日期字段绝对地址。</param>
    private static void MaskPointers(IMemorySource memory, byte[] buffer, ulong blockAddress, ulong dateAddress)
    {
        var offset = 0;
        while (offset + 8 <= buffer.Length)
        {
            var delta = (long)(blockAddress + (ulong)offset) - (long)dateAddress;
            if (delta % 4 != 0)
            {
                offset++;
                continue;
            }

            var value = BinaryPrimitives.ReadUInt64LittleEndian(buffer.AsSpan(offset, 8));
            if (!IsPointerLike(value) || !memory.IsReadable(value, 1))
            {
                offset += 4;
                continue;
            }

            PointerMarker.CopyTo(buffer, offset);
            offset += 8;
        }
    }

    /// <summary>
    /// 是否为可能的用户态指针：8 字节对齐、落在合法用户地址范围，且低 32 位不是“紧邻零字段”的假指纹。
    ///
    /// 低 32 位约束用来排除 [0x00000000][对象ID] 这类跨字段窗口：它们拼出的
    /// <c>0x0000XXXXXXXX00000000</c> 也满足“对齐 + 可读”，若当作指针整段屏蔽会抹掉对象 ID。
    /// </summary>
    /// <param name="value">待判定的 64 位值。</param>
    /// <returns>指针形态为 <c>true</c>。</returns>
    private static bool IsPointerLike(ulong value) =>
        (value & 7) == 0 &&
        (value & 0xFFFF_FFFF) >= 0x10000 &&
        value < 0x0000_8000_0000_0000;
}
