using System.Security.Cryptography;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Discovery;

/// <summary>
/// 候选的逻辑身份：与“当前进程里的绝对地址”分离。
///
/// 结构指纹只使用日期字段前后的结构字节与所属模块，<b>不包含日期值本身</b>；
/// 因此同一个逻辑对象在游戏推进日期后指纹不变，而游戏重启导致地址变化时仍可重新关联。
/// 仅靠日期值相同的候选不会被赋予稳定身份，仍保持低可信度。
/// </summary>
public static class CandidateIdentity
{
    /// <summary>日期字段之前的结构头长度（等于 <see cref="WorldDateLocator.DateFieldOffset"/>）。</summary>
    public const int HeaderLength = WorldDateLocator.DateFieldOffset;

    /// <summary>日期字段之后参与指纹的尾部长度。</summary>
    public const int TailLength = 0x80;

    /// <summary>指纹摘要截断字节数（十六进制 16 字符）。</summary>
    public const int DigestBytes = 8;

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
    /// 计算结构指纹：模块类别 + 结构头 [base, date) + 日期之后 [date+0x18, date+0x18+TailLength)。
    /// 日期字段（+0x0）与其后的参考日期（+0x4）都被刻意排除，避免“日期一变身份就变”。
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

        var header = new byte[HeaderLength];
        var headerAddress = dateAddress - HeaderLength;
        var headerReadable = memory.TryReadBlock(headerAddress, header, header.Length);
        hash.AppendData(headerReadable ? header : Array.Empty<byte>());

        var tail = new byte[TailLength];
        var tailAddress = dateAddress + 0x18;
        var tailReadable = memory.TryReadBlock(tailAddress, tail, tail.Length);
        hash.AppendData(tailReadable ? tail : Array.Empty<byte>());

        // 把“哪些区段可读”也纳入指纹：结构损坏时指纹必须变化，不能与前一次悄悄相等。
        hash.AppendData(new[] { (byte)(headerReadable ? 1 : 0), (byte)(tailReadable ? 1 : 0) });
        var digest = hash.GetHashAndReset();
        return Convert.ToHexString(digest.AsSpan(0, DigestBytes)).ToLowerInvariant();
    }

    /// <summary>逻辑签名：模块类别 + 结构指纹。</summary>
    /// <param name="module">模块类别。</param>
    /// <param name="fingerprint">结构指纹。</param>
    /// <returns>逻辑签名。</returns>
    public static string ComputeLogicalSignature(string module, string fingerprint) => $"{module}:{fingerprint}";

    /// <summary>把地址格式化为十六进制字符串。</summary>
    /// <param name="value">地址。</param>
    /// <returns>形如 <c>0x7FF6...</c> 的文本。</returns>
    public static string Hex(ulong value) => $"0x{value:X}";
}
