using System.Security.Cryptography;
using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>存档文件探测：只读、只认存档扩展名、哈希与稳定元数据可选。</summary>
public static class SaveFileProbeTests
{
    private const string TempDirectoryName = "scoutmind-save-file-probe";

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("存档文件：描述返回大小、哈希与稳定元数据", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var path = Path.Combine(directory, "sample.fm");
                var payload = new byte[] { 1, 2, 3, 4, 5 };
                File.WriteAllBytes(path, payload);

                var snapshot = SaveFileLocator.Describe(path, includeContentHash: true);

                TestHarness.True(snapshot is not null, "存在的存档文件必须能描述");
                TestHarness.Equal((long)payload.Length, snapshot!.SizeBytes, "大小必须正确");
                TestHarness.Equal(
                    Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant(),
                    snapshot.ContentHash ?? string.Empty,
                    "内容哈希必须匹配");
                if (OperatingSystem.IsWindows())
                {
                    TestHarness.True(snapshot.HasStableMetadata, "Windows 上应取得卷序列号与 FileId");
                }
            }
            finally
            {
                Directory.Delete(directory, recursive: true);
            }
        });

        harness.Run("存档文件：不存在的路径返回 null", () =>
        {
            var missing = Path.Combine(Path.GetTempPath(), "scoutmind-missing-" + Guid.NewGuid().ToString("N") + ".fm");

            TestHarness.Equal(null, SaveFileLocator.Describe(missing, includeContentHash: false), "缺失文件不得伪造快照");
        });

        harness.Run("存档文件：定位器只接受 .fm/.sav 并按时间倒序", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var older = Path.Combine(directory, "older.fm");
                var newer = Path.Combine(directory, "newer.sav");
                File.WriteAllText(older, "old");
                File.WriteAllText(newer, "new");
                File.SetLastWriteTimeUtc(older, new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc));
                File.SetLastWriteTimeUtc(newer, new DateTime(2026, 11, 20, 0, 0, 0, DateTimeKind.Utc));
                File.WriteAllText(Path.Combine(directory, "notes.txt"), "ignore");

                var probe = new SaveFileLocator(directory);
                var snapshots = probe.Probe(includeContentHash: false);

                TestHarness.Equal(2, snapshots.Count, "只应返回存档文件");
                TestHarness.Equal("newer.sav", Path.GetFileName(snapshots[0].Path), "最新文件应排在最前");
                TestHarness.Equal("older.fm", Path.GetFileName(snapshots[1].Path), "较旧文件排在后面");
            }
            finally
            {
                Directory.Delete(directory, recursive: true);
            }
        });

        harness.Run("存档文件：MaxFiles 限制生效", () =>
        {
            var directory = CreateDirectory();
            try
            {
                for (var index = 0; index < 4; index++)
                {
                    File.WriteAllText(Path.Combine(directory, $"save-{index}.fm"), index.ToString());
                }

                var probe = new SaveFileLocator(directory, new SaveFileProbeOptions(MaxFiles: 2));
                TestHarness.Equal(2, probe.Probe(includeContentHash: false).Count, "不得超过 MaxFiles");
            }
            finally
            {
                Directory.Delete(directory, recursive: true);
            }
        });

        harness.Run("存档文件：显式单文件探测与缺失降级", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var path = Path.Combine(directory, "explicit.fm");
                File.WriteAllText(path, "explicit");

                var probe = new SingleSaveFileProbe(path);
                TestHarness.Equal(1, probe.Probe(includeContentHash: false).Count, "应返回唯一文件");
                TestHarness.Equal(
                    0,
                    new SingleSaveFileProbe(Path.Combine(directory, "nope.fm")).Probe(false).Count,
                    "文件不存在时返回空列表");
            }
            finally
            {
                Directory.Delete(directory, recursive: true);
            }
        });

        harness.Run("存档文件：空目录不产生候选", () =>
        {
            var directory = CreateDirectory();
            try
            {
                TestHarness.Equal(0, new SaveFileLocator(directory).Probe(includeContentHash: false).Count, "空目录没有候选");
            }
            finally
            {
                Directory.Delete(directory, recursive: true);
            }
        });
    }

    private static string CreateDirectory()
    {
        var directory = Path.Combine(Path.GetTempPath(), TempDirectoryName + "-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        return directory;
    }
}
