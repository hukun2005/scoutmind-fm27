using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>存档身份解析：缺证据即 UNKNOWN，第三优先级不得单独认证，内容哈希不改变身份。</summary>
public static class SaveIdentityTests
{
    private static readonly DateTime Start = new(2026, 11, 24, 10, 0, 0, DateTimeKind.Utc);

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("身份：没有进程时保持 UNKNOWN", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(pid: null, detected: false),
                Array.Empty<SaveFileSnapshot>()));

            TestHarness.Equal(SaveIdentityStatus.Unknown, resolution.Status, "没有进程时必须是 UNKNOWN");
            TestHarness.Equal(SaveIdentityConfidence.None, resolution.Confidence, "可信度必须是 NONE");
            TestHarness.Equal("si:v1:unresolved:26620374", resolution.Fingerprint, "未解析指纹不得伪装成身份");
            TestHarness.True(!resolution.SnapshotEligible, "自动快照必须不可用");
            TestHarness.True(
                resolution.MissingEvidence.Contains(SaveEvidenceType.GameInternalSaveId),
                "必须说明缺少游戏内 Save ID");
            TestHarness.Equal(null, resolution.SessionKey, "没有进程就没有会话键");
        });

        harness.Run("身份：进程 + 稳定文件元数据最高只能到 CANDIDATE", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(),
                new[] { SaveFile("a.fm") },
                new CareerEvidence("Manager", "Club", "42")));

            TestHarness.Equal(SaveIdentityStatus.Candidate, resolution.Status, "没有强证据不得进入 VERIFIED");
            TestHarness.Equal(SaveIdentityConfidence.Medium, resolution.Confidence, "稳定文件元数据对应 MEDIUM");
            TestHarness.Equal(SaveIdentityKind.SaveFile, resolution.Kind, "来源应是存档文件");
            TestHarness.True(resolution.Fingerprint.StartsWith("si:v1:file:", StringComparison.Ordinal), "应生成文件指纹");
            TestHarness.True(!resolution.SnapshotEligible, "本版本自动快照恒不可用");
            TestHarness.True(
                resolution.Explanation.Any(line => line.Contains("CANDIDATE", StringComparison.Ordinal)),
                "必须解释为什么停在 CANDIDATE");
        });

        harness.Run("身份：存档内容哈希变化不改变身份指纹", () =>
        {
            var before = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm", hash: "hash-1") }));
            var after = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm", hash: "hash-2") }));

            TestHarness.Equal(before.Fingerprint, after.Fingerprint, "同一稳定文件元数据必须保持同一身份");
        });

        harness.Run("身份：FileId 变化产生不同指纹", () =>
        {
            var first = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm", fileId: "F1") }));
            var second = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm", fileId: "F2") }));

            TestHarness.True(
                !string.Equals(first.Fingerprint, second.Fingerprint, StringComparison.Ordinal),
                "不同文件身份不得得到同一指纹");
        });

        harness.Run("身份：多个未锁定存档视为歧义", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(),
                new[]
                {
                    SaveFile("a.fm", fileId: "F1", mtime: Start),
                    SaveFile("b.fm", fileId: "F2", mtime: Start.AddMinutes(5)),
                }));

            TestHarness.Equal(SaveIdentityStatus.Discovered, resolution.Status, "歧义时不能给出 CANDIDATE");
            TestHarness.True(resolution.IsAmbiguous, "必须标记歧义");
            TestHarness.Equal("si:v1:unresolved:26620374", resolution.Fingerprint, "歧义时不得生成稳定指纹");
        });

        harness.Run("身份：多存档歧义时用户确认指纹可唯一消歧", () =>
        {
            var files = new[]
            {
                SaveFile("a.fm", fileId: "F1", mtime: Start),
                SaveFile("b.fm", fileId: "F2", mtime: Start.AddMinutes(5)),
            };
            var confirmed = SaveIdentityFingerprint.FromSaveFile("V1", "F2");
            var resolution = SaveIdentityResolver.Resolve(
                new SaveIdentityInput(Process(), files, null, confirmed));

            TestHarness.Equal(SaveIdentityStatus.Verified, resolution.Status, "确认指纹唯一命中时应 VERIFIED");
            TestHarness.Equal(SaveIdentityKind.UserConfirmed, resolution.Kind, "来源应为用户确认");
            TestHarness.True(!resolution.IsAmbiguous, "确认后不得再标记歧义");
            TestHarness.Equal(confirmed, resolution.Fingerprint, "指纹应是被确认的那个存档");
            TestHarness.True(resolution.SnapshotEligible, "确认后的身份应允许参与自动快照评估");

            var unmatched = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), files, null, SaveIdentityFingerprint.FromSaveFile("V9", "F9")));

            TestHarness.Equal(SaveIdentityStatus.Discovered, unmatched.Status, "不匹配的确认不能猜存档");
            TestHarness.True(unmatched.IsAmbiguous, "仍应标记歧义");
        });

        harness.Run("身份：唯一被游戏占用的文件可确定为当前存档", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(),
                new[]
                {
                    SaveFile("a.fm", fileId: "F1"),
                    SaveFile("b.fm", fileId: "F2", locked: true),
                }));

            TestHarness.Equal(SaveIdentityStatus.Candidate, resolution.Status, "唯一占用文件可确定为当前存档");
            TestHarness.True(!resolution.IsAmbiguous, "不应标记歧义");
            TestHarness.True(
                resolution.Fingerprint == SaveIdentityFingerprint.FromSaveFile("V1", "F2"),
                "指纹应来自被占用的文件");
        });

        harness.Run("身份：用户确认指纹一致才 VERIFIED", () =>
        {
            var fingerprint = SaveIdentityFingerprint.FromSaveFile("V1", "F1");
            var verified = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm") }, null, fingerprint));

            TestHarness.Equal(SaveIdentityStatus.Verified, verified.Status, "确认一致时应 VERIFIED");
            TestHarness.Equal(SaveIdentityKind.UserConfirmed, verified.Kind, "来源应为用户确认");
            TestHarness.True(verified.SnapshotEligible, "VERIFIED 身份应允许参与自动快照评估");

            var conflict = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm") }, null, SaveIdentityFingerprint.FromSaveFile("V9", "F9")));

            TestHarness.Equal(SaveIdentityStatus.Conflict, conflict.Status, "确认不一致必须是 CONFLICT");
            TestHarness.True(conflict.Conflicts.Count > 0, "必须给出冲突说明");
        });

        harness.Run("身份：第三优先级证据不得单独认证", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(),
                Array.Empty<SaveFileSnapshot>(),
                new CareerEvidence("Manager", "Club", "42")));

            TestHarness.Equal(SaveIdentityStatus.Discovered, resolution.Status, "职业元数据只能到 DISCOVERED");
            TestHarness.Equal(SaveIdentityKind.Unresolved, resolution.Kind, "不得伪造稳定身份来源");
            TestHarness.True(!resolution.SnapshotEligible, "不得因此放行自动快照");
        });

        harness.Run("身份：会话键包含 PID/构建但不是身份指纹", () =>
        {
            var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(
                Process(), new[] { SaveFile("a.fm") }));

            TestHarness.True(resolution.SessionKey is not null, "应有会话键");
            TestHarness.Contains(resolution.SessionKey!, "123", "会话键应包含 PID");
            TestHarness.Contains(resolution.SessionKey!, "26620374", "会话键应包含构建号");
            TestHarness.True(
                !string.Equals(resolution.SessionKey, resolution.Fingerprint, StringComparison.Ordinal),
                "会话键不得被当作存档身份");
        });

        harness.Run("身份状态：存储往返与损坏降级", () =>
        {
            var directory = Path.Combine(Path.GetTempPath(), "scoutmind-saveid-" + Guid.NewGuid().ToString("N"));
            var path = Path.Combine(directory, "save-identity.json");
            try
            {
                var store = new SaveIdentityStore(path);
                var state = new SaveIdentityState(
                    "si:v1:file:abc", SaveIdentityKind.SaveFile, SaveIdentityStatus.Candidate,
                    SaveIdentityConfidence.Medium, "26620374", "123:start:26620374", "2026-11-24T10:00:00Z",
                    null, null);
                store.Save(state);

                var loaded = store.Load();
                TestHarness.Equal("si:v1:file:abc", loaded.Fingerprint, "指纹应可往返");
                TestHarness.Equal(SaveIdentityStatus.Candidate, loaded.Status, "状态应可往返（字符串枚举）");

                File.WriteAllText(path, "{ not json");
                TestHarness.Equal(null, store.Load().Fingerprint, "损坏状态必须降级为空而不是猜测");
            }
            finally
            {
                if (Directory.Exists(directory))
                {
                    Directory.Delete(directory, recursive: true);
                }
            }
        });
    }

    private static GameProcessEvidence Process(int? pid = 123, bool detected = true) => new(
        pid,
        pid is null ? null : Start,
        "26620374",
        "27.1.0+2505117",
        detected);

    private static SaveFileSnapshot SaveFile(
        string path,
        string? volume = "V1",
        string? fileId = "F1",
        string? hash = "hash-1",
        bool locked = false,
        DateTime? mtime = null) => new(
        path,
        volume,
        fileId,
        1024,
        Start,
        mtime ?? Start,
        hash,
        locked);
}
