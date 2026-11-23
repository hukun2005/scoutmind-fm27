namespace ScoutMind.Agent;

/// <summary>
/// 本地扫描队列：读取器输出目录、待同步队列与已同步归档。
/// 同步失败的结果不会被丢弃，而是留在 <c>pending/</c> 中等待下次 <c>sync</c>。
/// </summary>
public sealed class ScanQueue
{
    /// <summary>创建队列。</summary>
    /// <param name="rootDirectory">队列根目录。</param>
    public ScanQueue(string rootDirectory)
    {
        if (string.IsNullOrWhiteSpace(rootDirectory))
        {
            throw new ArgumentException("队列目录不能为空。", nameof(rootDirectory));
        }

        Root = Path.GetFullPath(rootDirectory);
    }

    /// <summary>队列根目录。</summary>
    public string Root { get; }

    /// <summary>读取器扫描输出目录。</summary>
    public string ScanDirectory => Path.Combine(Root, "scans");

    /// <summary>同步失败的待重试目录。</summary>
    public string PendingDirectory => Path.Combine(Root, "pending");

    /// <summary>已成功同步的归档目录。</summary>
    public string SentDirectory => Path.Combine(Root, "sent");

    /// <summary>同一游戏日期重复扫描的隔离目录（保留文件，不当作已同步）。</summary>
    public string DuplicatesDirectory => Path.Combine(Root, "duplicates");

    /// <summary>确保三个目录存在。</summary>
    public void EnsureCreated()
    {
        Directory.CreateDirectory(ScanDirectory);
        Directory.CreateDirectory(PendingDirectory);
        Directory.CreateDirectory(SentDirectory);
        Directory.CreateDirectory(DuplicatesDirectory);
    }

    /// <summary>列出所有待同步的扫描信封文件：先 <c>pending/</c>，再 <c>scans/</c>，各自按文件名排序。</summary>
    /// <returns>按同步顺序排列的绝对路径。</returns>
    public IReadOnlyList<string> ListOutstanding()
    {
        var files = new List<string>();
        files.AddRange(EnumerateEnvelopes(PendingDirectory));
        files.AddRange(EnumerateEnvelopes(ScanDirectory));
        return files;
    }

    /// <summary>把成功同步的文件移动到 <c>sent/</c>；文件已在归档目录时直接返回。</summary>
    /// <param name="path">扫描信封文件路径。</param>
    /// <returns>归档后的路径。</returns>
    public string Archive(string path)
    {
        var fullPath = Path.GetFullPath(path);
        var destination = Path.Combine(SentDirectory, Path.GetFileName(fullPath));
        if (string.Equals(fullPath, destination, StringComparison.OrdinalIgnoreCase))
        {
            return destination;
        }

        Directory.CreateDirectory(SentDirectory);
        File.Move(fullPath, destination, overwrite: true);
        return destination;
    }

    /// <summary>把同一游戏日期的重复扫描移到 <c>duplicates/</c>，保留原始文件。</summary>
    /// <param name="path">扫描信封文件路径。</param>
    /// <returns>隔离后的路径；文件不存在时返回 <c>null</c>。</returns>
    public string? ArchiveDuplicate(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
        {
            return null;
        }

        Directory.CreateDirectory(DuplicatesDirectory);
        var destination = Path.Combine(DuplicatesDirectory, Path.GetFileName(fullPath));
        File.Move(fullPath, destination, overwrite: true);
        return destination;
    }

    /// <summary>把同步失败的文件放入 <c>pending/</c>（若它已经在队列内则保留原位）。</summary>
    /// <param name="path">扫描信封文件路径。</param>
    /// <returns>待重试文件路径；文件不存在时返回 <c>null</c>。</returns>
    public string? EnqueuePending(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
        {
            return null;
        }

        var destination = Path.Combine(PendingDirectory, Path.GetFileName(fullPath));
        if (string.Equals(Path.GetDirectoryName(fullPath), PendingDirectory, StringComparison.OrdinalIgnoreCase))
        {
            return fullPath;
        }

        Directory.CreateDirectory(PendingDirectory);
        File.Copy(fullPath, destination, overwrite: true);
        return destination;
    }

    private static IEnumerable<string> EnumerateEnvelopes(string directory)
    {
        if (!Directory.Exists(directory))
        {
            return Array.Empty<string>();
        }

        var paths = Directory.GetFiles(directory, "scan-*.json")
            .Where(path => !path.EndsWith(".meta.json", StringComparison.OrdinalIgnoreCase))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return paths;
    }
}
