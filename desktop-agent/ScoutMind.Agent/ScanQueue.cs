using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>
/// 本地扫描队列：读取器输出目录、处理中、待同步、已同步、失败与隔离目录。
///
/// 一个扫描任务是「信封 + meta + manifest」三件套：任何移动都必须整体移动，任何重试都必须带上边车，
/// 否则后端或校验器只能看到半份证据。同步失败的结果不会被丢弃，而是回到 <c>pending/</c> 等待下次同步。
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

    /// <summary>正在上传的任务目录；进程异常退出后该目录里的任务会在下次同步时被恢复。</summary>
    public string ProcessingDirectory => Path.Combine(Root, "processing");

    /// <summary>同步失败的待重试目录。</summary>
    public string PendingDirectory => Path.Combine(Root, "pending");

    /// <summary>已确认导入完成的归档目录。</summary>
    public string SentDirectory => Path.Combine(Root, "sent");

    /// <summary>后端明确拒绝且不可重试的任务目录（保留失败原因）。</summary>
    public string FailedDirectory => Path.Combine(Root, "failed");

    /// <summary>同一游戏日期重复扫描的隔离目录（保留文件，不当作已同步）。</summary>
    public string DuplicatesDirectory => Path.Combine(Root, "duplicates");

    /// <summary>完整性校验失败文件的隔离目录；保留信封、meta 和 manifest。</summary>
    public string QuarantineDirectory => Path.Combine(Root, "quarantine");

    /// <summary>确保所有目录存在。</summary>
    public void EnsureCreated()
    {
        Directory.CreateDirectory(ScanDirectory);
        Directory.CreateDirectory(ProcessingDirectory);
        Directory.CreateDirectory(PendingDirectory);
        Directory.CreateDirectory(SentDirectory);
        Directory.CreateDirectory(FailedDirectory);
        Directory.CreateDirectory(DuplicatesDirectory);
        Directory.CreateDirectory(QuarantineDirectory);
    }

    /// <summary>
    /// 列出所有待同步的扫描信封：先 <c>processing/</c>（上次进程遗留），再 <c>pending/</c>，最后 <c>scans/</c>。
    /// </summary>
    /// <returns>按同步顺序排列的绝对路径。</returns>
    public IReadOnlyList<string> ListOutstanding()
    {
        var files = new List<string>();
        files.AddRange(EnumerateEnvelopes(ProcessingDirectory));
        files.AddRange(EnumerateEnvelopes(PendingDirectory));
        files.AddRange(EnumerateEnvelopes(ScanDirectory));
        return files;
    }

    /// <summary>任务信封对应的 meta 路径。</summary>
    /// <param name="envelopePath">信封路径。</param>
    /// <returns>同目录的 <c>*.meta.json</c>。</returns>
    public static string MetaPathFor(string envelopePath) => Path.ChangeExtension(envelopePath, ".meta.json");

    /// <summary>任务信封对应的 manifest 路径。</summary>
    /// <param name="envelopePath">信封路径。</param>
    /// <returns>同目录的 <c>*.manifest.json</c>。</returns>
    public static string ManifestPathFor(string envelopePath) => ScanManifest.PathFor(envelopePath);

    /// <summary>把任务移入 <c>processing/</c> 并返回新路径；文件不存在时返回 <c>null</c>。</summary>
    /// <param name="envelopePath">当前信封路径。</param>
    /// <returns>处理中的信封路径。</returns>
    public string? Claim(string envelopePath)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        if (!File.Exists(fullPath))
        {
            return null;
        }

        var destination = ReserveStem(ProcessingDirectory, Path.GetFileNameWithoutExtension(fullPath));
        Directory.CreateDirectory(ProcessingDirectory);
        MoveAll(fullPath, Path.Combine(ProcessingDirectory, destination));
        return Path.Combine(ProcessingDirectory, destination + ".json");
    }

    /// <summary>把任务归档到 <c>sent/</c>；只有后端确认完成后才应调用。</summary>
    /// <param name="envelopePath">处理中的信封路径。</param>
    /// <returns>归档后的信封路径。</returns>
    public string ArchiveAll(string envelopePath)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        Directory.CreateDirectory(SentDirectory);
        var destination = ReserveStem(SentDirectory, Path.GetFileNameWithoutExtension(fullPath));
        MoveAll(fullPath, Path.Combine(SentDirectory, destination));
        return Path.Combine(SentDirectory, destination + ".json");
    }

    /// <summary>把任务放入 <c>failed/</c>，并记录失败原因。</summary>
    /// <param name="envelopePath">处理中的信封路径。</param>
    /// <param name="failure">写入 <c>failure.json</c> 的失败说明。</param>
    /// <returns>失败目录路径。</returns>
    public string FailAll(string envelopePath, object failure)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        Directory.CreateDirectory(FailedDirectory);
        var stem = Path.GetFileNameWithoutExtension(fullPath);
        var folder = ReserveFolder(FailedDirectory, stem);
        Directory.CreateDirectory(folder);
        foreach (var (source, suffix) in Sidecars(fullPath))
        {
            File.Move(source, Path.Combine(folder, stem + suffix), overwrite: true);
        }

        File.WriteAllText(
            Path.Combine(folder, "failure.json"),
            JsonSerializer.Serialize(failure, new JsonSerializerOptions { WriteIndented = true }));
        return folder;
    }

    /// <summary>把完整性校验失败的三件套隔离，保留证据并写 manifest。</summary>
    /// <param name="envelopePath">信封路径。</param>
    /// <param name="manifest">隔离说明。</param>
    /// <returns>隔离目录；文件都不存在时为 <c>null</c>。</returns>
    public string? QuarantineAll(string envelopePath, object manifest)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        var metaPath = MetaPathFor(fullPath);
        var manifestPath = ManifestPathFor(fullPath);
        if (!File.Exists(fullPath) && !File.Exists(metaPath) && !File.Exists(manifestPath)) return null;
        Directory.CreateDirectory(QuarantineDirectory);
        var stamp = DateTimeOffset.UtcNow.ToString("yyyyMMddTHHmmssfff");
        var stem = Path.GetFileNameWithoutExtension(fullPath);
        var folder = Path.Combine(QuarantineDirectory, $"{stem}-{stamp}");
        Directory.CreateDirectory(folder);
        foreach (var path in new[] { fullPath, metaPath, manifestPath })
        {
            if (File.Exists(path))
            {
                File.Move(path, Path.Combine(folder, Path.GetFileName(path)), overwrite: false);
            }
        }

        File.WriteAllText(
            Path.Combine(folder, "quarantine.json"),
            JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }));
        return folder;
    }

    /// <summary>把同一游戏日期的重复扫描移到 <c>duplicates/</c>，保留原始文件。</summary>
    /// <param name="envelopePath">信封路径。</param>
    /// <returns>隔离后的路径；文件不存在时返回 <c>null</c>。</returns>
    public string? ArchiveDuplicate(string envelopePath)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        if (!File.Exists(fullPath))
        {
            return null;
        }

        Directory.CreateDirectory(DuplicatesDirectory);
        var destination = ReserveStem(DuplicatesDirectory, Path.GetFileNameWithoutExtension(fullPath));
        MoveAll(fullPath, Path.Combine(DuplicatesDirectory, destination));
        return Path.Combine(DuplicatesDirectory, destination + ".json");
    }

    /// <summary>把任务放回 <c>pending/</c>（连同 meta 与 manifest），等待下次重试。</summary>
    /// <param name="envelopePath">任意目录下的信封路径。</param>
    /// <returns>待重试的信封路径；文件不存在时返回 <c>null</c>。</returns>
    public string? EnqueuePending(string envelopePath)
    {
        var fullPath = Path.GetFullPath(envelopePath);
        if (!File.Exists(fullPath))
        {
            return null;
        }

        Directory.CreateDirectory(PendingDirectory);
        var stem = Path.GetFileNameWithoutExtension(fullPath);
        var destination = Path.Combine(PendingDirectory, stem + ".json");
        if (string.Equals(fullPath, destination, StringComparison.OrdinalIgnoreCase))
        {
            return fullPath;
        }

        var targetStem = Path.Combine(PendingDirectory, stem);
        CopyAll(fullPath, targetStem);
        return destination;
    }

    private static void MoveAll(string envelopePath, string destinationStem)
    {
        var folder = Path.GetDirectoryName(destinationStem) ?? ".";
        Directory.CreateDirectory(folder);
        foreach (var (source, suffix) in Sidecars(envelopePath))
        {
            File.Move(source, destinationStem + suffix, overwrite: true);
        }
    }

    private static void CopyAll(string envelopePath, string destinationStem)
    {
        var folder = Path.GetDirectoryName(destinationStem) ?? ".";
        Directory.CreateDirectory(folder);
        foreach (var (source, suffix) in Sidecars(envelopePath))
        {
            File.Copy(source, destinationStem + suffix, overwrite: true);
        }
    }

    /// <summary>信封和它的两个边车（不存在的跳过）。</summary>
    private static IEnumerable<(string Path, string Suffix)> Sidecars(string envelopePath)
    {
        yield return (envelopePath, ".json");
        var meta = MetaPathFor(envelopePath);
        if (File.Exists(meta)) yield return (meta, ".meta.json");
        var manifest = ManifestPathFor(envelopePath);
        if (File.Exists(manifest)) yield return (manifest, ".manifest.json");
    }

    /// <summary>在目标目录里挑一个不冲突的文件名主干，避免覆盖既有任务。</summary>
    private static string ReserveStem(string directory, string stem)
    {
        var candidate = stem;
        var counter = 0;
        while (File.Exists(Path.Combine(directory, candidate + ".json"))
               || File.Exists(Path.Combine(directory, candidate + ".manifest.json")))
        {
            counter++;
            candidate = $"{stem}-{counter}";
        }

        return candidate;
    }

    /// <summary>在目标目录里挑一个不冲突的子目录名。</summary>
    private static string ReserveFolder(string directory, string stem)
    {
        var candidate = stem;
        var counter = 0;
        while (Directory.Exists(Path.Combine(directory, candidate)))
        {
            counter++;
            candidate = $"{stem}-{counter}";
        }

        return Path.Combine(directory, candidate);
    }

    private static IEnumerable<string> EnumerateEnvelopes(string directory)
    {
        if (!Directory.Exists(directory))
        {
            return Array.Empty<string>();
        }

        var paths = Directory.GetFiles(directory, "scan-*.json")
            .Where(path => !path.EndsWith(".meta.json", StringComparison.OrdinalIgnoreCase))
            .Where(path => !path.EndsWith(".manifest.json", StringComparison.OrdinalIgnoreCase))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        return paths;
    }
}
