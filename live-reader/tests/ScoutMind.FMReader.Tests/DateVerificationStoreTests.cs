using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>日期验证状态持久化：缺失、损坏、往返与原子写入。</summary>
public static class DateVerificationStoreTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("日期状态：文件缺失时返回空状态", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var store = new DateVerificationStore(Path.Combine(directory, "missing.json"));
                var state = store.Load();

                TestHarness.True(state.Candidates.Count == 0, "缺失状态不应包含候选");
                TestHarness.True(state.LastConfirmedDate is null, "缺失状态不应有确认日期");
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        });

        harness.Run("日期状态：保存后可完整读回", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var path = Path.Combine(directory, "state.json");
                var store = new DateVerificationStore(path);
                var candidate = new TrackedCandidateState(
                    "heap:abc",
                    "heap",
                    "abc",
                    "2026-11-24T00:00:00Z",
                    "2026-11-24T00:10:00Z",
                    6,
                    3,
                    "0x12345678",
                    "0x30001000",
                    "s1",
                    "s1",
                    new[] { "2026-11-06" },
                    new[] { "2026-11-06" },
                    new[] { "s1" });
                store.Save(new DateVerificationState(
                    "26620374", null, "s1", "2026-11-06", "2026-11-06",
                    new[] { candidate },
                    new[] { new DateEvidenceEntry("operator_date_check", "界面日期一致", "2026-11-24T00:10:00Z", "s1", "2026-11-06", "2026-11-06", "heap:abc") }));

                var loaded = store.Load();

                TestHarness.Equal("2026-11-06", loaded.LastConfirmedDate, "确认日期应读回");
                TestHarness.Equal(1, loaded.Candidates.Count, "候选应读回");
                TestHarness.Equal("heap:abc", loaded.Candidates[0].LogicalSignature, "逻辑签名应保留");
                TestHarness.True(!File.Exists(path + ".tmp"), "不应遗留临时文件");
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        });

        harness.Run("日期状态：损坏文件安全降级为空状态", () =>
        {
            var directory = CreateDirectory();
            try
            {
                var path = Path.Combine(directory, "broken.json");
                File.WriteAllText(path, "{ not json");
                var store = new DateVerificationStore(path);

                var state = store.Load();

                TestHarness.True(state.Candidates.Count == 0, "损坏文件不能被当成有效证据");
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        });
    }

    private static string CreateDirectory()
    {
        var path = Path.Combine(Path.GetTempPath(), "scoutmind-date-state-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
