using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace ScoutMind.FMReader.Discovery;

/// <summary>存档文件探测参数。</summary>
/// <param name="MaxFiles">最多返回的文件数。</param>
/// <param name="MaxHashBytes">计算内容哈希的最大文件字节数；超过时跳过哈希。</param>
public sealed record SaveFileProbeOptions(int MaxFiles = 50, long MaxHashBytes = 1L * 1024 * 1024 * 1024)
{
    /// <summary>默认参数。</summary>
    public static SaveFileProbeOptions Default { get; } = new();
}

/// <summary>存档文件探测接口，便于在没有真实游戏文件的机器上测试身份逻辑。</summary>
public interface ISaveFileProbe
{
    /// <summary>探测候选存档文件。</summary>
    /// <param name="includeContentHash">是否计算内容哈希。</param>
    /// <returns>按最后写入时间倒序的快照。</returns>
    IReadOnlyList<SaveFileSnapshot> Probe(bool includeContentHash);
}

/// <summary>
/// 只读定位 FM27 存档文件。默认目录为
/// <c>%USERPROFILE%\Documents\Sports Interactive\Football Manager 27\games</c>（兼容 2027 命名），
/// 可用环境变量 <c>SCOUTMIND_FM_SAVE_DIR</c> 覆盖（多个目录用 <c>;</c> 分隔）。
///
/// 这里只读取文件元数据与可选的内容哈希，不修改文件，也不解析存档格式。
/// </summary>
public sealed class SaveFileLocator : ISaveFileProbe
{
    /// <summary>覆盖存档目录的环境变量名。</summary>
    public const string SaveDirectoryEnvironmentVariable = "SCOUTMIND_FM_SAVE_DIR";

    private static readonly string[] SaveExtensions = { ".fm", ".sav" };
    private static readonly string[] FolderNames = { "Football Manager 27", "Football Manager 2027" };

    private readonly string? _saveDirectory;
    private readonly SaveFileProbeOptions _options;

    /// <summary>创建定位器。</summary>
    /// <param name="saveDirectory">存档目录；为空时读取环境变量或默认目录。</param>
    /// <param name="options">探测参数。</param>
    public SaveFileLocator(string? saveDirectory = null, SaveFileProbeOptions? options = null)
    {
        _saveDirectory = saveDirectory;
        _options = options ?? SaveFileProbeOptions.Default;
    }

    /// <summary>解析后的候选存档目录。</summary>
    public IReadOnlyList<string> SaveDirectories => ResolveDirectories();

    /// <inheritdoc />
    public IReadOnlyList<SaveFileSnapshot> Probe(bool includeContentHash)
    {
        var snapshots = new List<SaveFileSnapshot>();
        foreach (var directory in ResolveDirectories())
        {
            if (!Directory.Exists(directory))
            {
                continue;
            }

            try
            {
                snapshots.AddRange(Directory
                    .EnumerateFiles(directory, "*", SearchOption.TopDirectoryOnly)
                    .Where(path => SaveExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase))
                    .Select(path => Describe(path, includeContentHash, _options))
                    .Where(snapshot => snapshot is not null)
                    .Select(snapshot => snapshot!));
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                // 单个目录不可读时继续尝试其他目录。
            }
        }

        return snapshots
            .OrderByDescending(snapshot => snapshot.LastWriteUtc)
            .Take(_options.MaxFiles)
            .ToList();
    }

    private IReadOnlyList<string> ResolveDirectories()
    {
        if (!string.IsNullOrWhiteSpace(_saveDirectory))
        {
            return _saveDirectory
                .Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        }

        var configured = Environment.GetEnvironmentVariable(SaveDirectoryEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured
                .Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        }

        var documents = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        if (string.IsNullOrWhiteSpace(documents))
        {
            return Array.Empty<string>();
        }

        return FolderNames
            .Select(folder => Path.Combine(documents, "Sports Interactive", folder, "games"))
            .ToArray();
    }

    /// <summary>只读描述一个存档文件；文件不存在或不可读时返回 <c>null</c>。</summary>
    /// <param name="path">文件路径。</param>
    /// <param name="includeContentHash">是否计算内容哈希。</param>
    /// <param name="options">探测参数；为空时使用默认值。</param>
    /// <returns>快照。</returns>
    public static SaveFileSnapshot? Describe(
        string path,
        bool includeContentHash,
        SaveFileProbeOptions? options = null)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }
        try
        {
            var info = new FileInfo(path);
            if (!info.Exists)
            {
                return null;
            }

            var (volumeSerial, fileId) = ReadStableIdentity(path);
            var effective = options ?? SaveFileProbeOptions.Default;
            var contentHash = includeContentHash && info.Length <= effective.MaxHashBytes
                ? TryHash(path)
                : null;

            return new SaveFileSnapshot(
                Path: path,
                VolumeSerial: volumeSerial,
                FileId: fileId,
                SizeBytes: info.Length,
                CreatedUtc: info.CreationTimeUtc,
                LastWriteUtc: info.LastWriteTimeUtc,
                ContentHash: contentHash,
                IsLocked: IsLocked(path));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static (string? VolumeSerial, string? FileId) ReadStableIdentity(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            return (null, null);
        }

        try
        {
            using var handle = File.OpenHandle(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            if (!GetFileInformationByHandle(handle, out var information))
            {
                return (null, null);
            }

            var fileId = ((ulong)information.FileIndexHigh << 32) | information.FileIndexLow;
            return (
                information.VolumeSerialNumber.ToString("X8", System.Globalization.CultureInfo.InvariantCulture),
                fileId.ToString("X16", System.Globalization.CultureInfo.InvariantCulture));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return (null, null);
        }
    }

    private static string? TryHash(string path)
    {
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var sha = SHA256.Create();
            return Convert.ToHexString(sha.ComputeHash(stream)).ToLowerInvariant();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static bool IsLocked(string path)
    {
        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None);
            return false;
        }
        catch (IOException)
        {
            return true;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public uint Low;
        public uint High;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public FileTime CreationTime;
        public FileTime LastAccessTime;
        public FileTime LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation information);
}

/// <summary>只探测用户显式指定的一个存档文件。用于机器上存在多个存档、无法自动判断当前存档的场景。</summary>
public sealed class SingleSaveFileProbe : ISaveFileProbe
{
    private readonly string _path;

    /// <summary>创建单文件探测。</summary>
    /// <param name="path">存档文件路径。</param>
    public SingleSaveFileProbe(string path)
    {
        _path = string.IsNullOrWhiteSpace(path)
            ? throw new ArgumentException("存档文件路径不能为空。", nameof(path))
            : path;
    }

    /// <inheritdoc />
    public IReadOnlyList<SaveFileSnapshot> Probe(bool includeContentHash)
    {
        var snapshot = SaveFileLocator.Describe(_path, includeContentHash);
        return snapshot is null ? Array.Empty<SaveFileSnapshot>() : new[] { snapshot };
    }
}
