using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Engine;

namespace ScoutMind.FMReader.Tests;

/// <summary>
/// V3.2.9.2 阶段 1：LiveReader 存档切换安全。
///
/// 覆盖任务书 §5.5 的语义：切档检测、旧指纹不得复用、旧确认失效、歧义/未知拒绝 Verified、
/// 指纹不一致需重新验证、进程重启失效旧会话、显式 --save-file 不能绕过身份校验、
/// 文件缺失失败关闭、文件替换需重新确认、多存档不得静默选第一个。
/// </summary>
public static class LiveReaderSaveSwitchSafetyTests
{
    private static readonly DateTime Start = new(2026, 11, 26, 9, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime Restart = Start.AddMinutes(30);

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("切档：检测到不同存档并使旧确认立即失效", () =>
        {
            using var workspace = new Workspace();
            var first = workspace.Run(Files(Save("a.fm", "F1")), verify: true);
            TestHarness.Equal(SaveIdentityStatus.Verified, first.Report.Resolution.Status, "首次确认应为 VERIFIED");
            TestHarness.Equal(1, first.Report.Generation, "首次运行建立 generation 1");

            var second = workspace.Run(Files(Save("b.fm", "F2")), verify: false);
            TestHarness.True(second.Report.ConfirmationInvalidated, "切档必须使旧确认失效");
            TestHarness.True(second.Report.Generation > first.Report.Generation, "切档必须推进 generation");
            TestHarness.Equal(null, second.State.UserConfirmedFingerprint, "切档后不得保留旧确认");
            TestHarness.True(
                !string.Equals(
                    second.Report.Resolution.Fingerprint,
                    first.Report.Resolution.Fingerprint,
                    StringComparison.Ordinal),
                "切档后必须返回新存档指纹");
        });

        harness.Run("切档：LiveReader 绝不把旧指纹当作当前存档", () =>
        {
            using var workspace = new Workspace();
            var a = workspace.Run(Files(Save("a.fm", "F1")), verify: true);
            var confirmedA = a.State.UserConfirmedFingerprint;

            var b = workspace.Run(Files(Save("b.fm", "F2")), verify: false);
            TestHarness.True(
                !string.Equals(b.Report.Resolution.Fingerprint, confirmedA, StringComparison.Ordinal),
                "当前指纹不得等于旧确认指纹");
            TestHarness.Equal(
                SaveIdentityBinding.CurrentFingerprint(b.Report.Resolution),
                b.Report.Resolution.Fingerprint,
                "当前指纹必须来自本次唯一解析结果");
        });

        harness.Run("切档：旧 Verified 在切档后不得继续有效", () =>
        {
            using var workspace = new Workspace();
            workspace.Run(Files(Save("a.fm", "F1")), verify: true);

            var b = workspace.Run(Files(Save("b.fm", "F2")), verify: false);
            TestHarness.Equal(SaveIdentityStatus.Candidate, b.Report.Resolution.Status, "新存档未重新确认前只能是 CANDIDATE");
            TestHarness.True(!b.Report.Resolution.SnapshotEligible, "旧 Verified 不得继续参与快照");
        });

        harness.Run("歧义：多个候选存档必须拒绝 Verified", () =>
        {
            using var workspace = new Workspace();
            var run = workspace.Run(Files(Save("a.fm", "F1"), Save("b.fm", "F2")), verify: true);

            TestHarness.True(run.Report.Resolution.IsAmbiguous, "多候选必须标记歧义");
            TestHarness.True(!run.Report.VerifyApplied, "歧义时 --verify 必须被拒绝");
            TestHarness.Equal(null, SaveIdentityBinding.CurrentFingerprint(run.Report.Resolution), "歧义时不得给出当前指纹");
            TestHarness.True(
                run.Report.Resolution.LimitationCodes.Contains("AMBIGUOUS_SAVE_FILES"),
                "必须给出歧义限制码");
        });

        harness.Run("未知：无法解析当前存档时必须拒绝 Verified", () =>
        {
            using var workspace = new Workspace();
            var run = workspace.Run(Array.Empty<SaveFileSnapshot>(), verify: true, processDetected: false);

            TestHarness.Equal(SaveIdentityStatus.Unknown, run.Report.Resolution.Status, "无进程必须是 UNKNOWN");
            TestHarness.True(!run.Report.VerifyApplied, "UNKNOWN 时不得完成确认");
            TestHarness.Equal(null, SaveIdentityBinding.CurrentFingerprint(run.Report.Resolution), "不得给出当前指纹");
        });

        harness.Run("不一致：指纹与已绑定身份不一致时必须重新验证", () =>
        {
            using var workspace = new Workspace();
            workspace.Run(Files(Save("a.fm", "F1")), verify: true);

            var conflict = workspace.Run(Files(Save("b.fm", "F2")), verify: false);
            TestHarness.Equal(SaveIdentityStatus.Candidate, conflict.Report.Resolution.Status, "不同文件不得沿用旧确认");
            TestHarness.True(conflict.Report.ConfirmationInvalidated, "必须显式报告确认失效");
            TestHarness.True(
                !string.Equals(
                    conflict.State.UserConfirmedFingerprint,
                    SaveIdentityFingerprint.FromSaveFile("V1", "F1"),
                    StringComparison.Ordinal),
                "旧确认不得继续留在状态里");
        });

        harness.Run("会话：进程重启后旧会话失效并推进 generation", () =>
        {
            using var workspace = new Workspace();
            var first = workspace.Run(Files(Save("a.fm", "F1")), verify: true);

            var restarted = workspace.Run(
                Files(Save("a.fm", "F1")),
                verify: false,
                processDetected: true,
                processStart: Restart,
                processId: 4242);

            TestHarness.True(restarted.Report.Generation > first.Report.Generation, "进程重启必须推进 generation");
            TestHarness.True(!restarted.Report.ConfirmationInvalidated, "同一存档的进程重启不应误判为切档");
        });

        harness.Run("显式文件：--save-file 不得绕过身份校验", () =>
        {
            using var workspace = new Workspace();
            var run = workspace.Run(
                Files(Save("a.fm", "F1")),
                verify: true,
                explicitFile: @"C:\saves\a.fm");

            TestHarness.Equal(SaveIdentityStatus.Candidate, run.Report.Resolution.Status, "显式文件最高只能是 CANDIDATE");
            TestHarness.True(!run.Report.VerifyApplied, "显式文件不得完成当前存档确认");
            TestHarness.True(
                run.Report.Resolution.LimitationCodes.Contains("CURRENT_SAVE_UNCONFIRMED"),
                "必须返回 CURRENT_SAVE_UNCONFIRMED");
            TestHarness.Equal(null, SaveIdentityBinding.CurrentFingerprint(run.Report.Resolution), "不得交给 Verified 门控");
        });

        harness.Run("显式文件：文件缺失时必须失败关闭", () =>
        {
            using var workspace = new Workspace();
            var run = workspace.Run(
                Array.Empty<SaveFileSnapshot>(),
                verify: true,
                explicitFile: @"C:\saves\missing.fm");

            TestHarness.Equal(SaveIdentityStatus.Discovered, run.Report.Resolution.Status, "缺失文件不得给出身份");
            TestHarness.True(!run.Report.VerifyApplied, "缺失文件必须拒绝确认");
            TestHarness.Equal(null, SaveIdentityBinding.CurrentFingerprint(run.Report.Resolution), "不得给出当前指纹");

            var probe = new SingleSaveFileProbe(@"C:\saves\definitely-missing.fm");
            TestHarness.Equal(0, probe.Probe(includeContentHash: false).Count, "单文件探测缺失时必须返回空");
        });

        harness.Run("替换：FileId 变化必须要求重新确认", () =>
        {
            using var workspace = new Workspace();
            workspace.Run(Files(Save("a.fm", "F1")), verify: true);

            var replaced = workspace.Run(Files(Save("a.fm", "F2")), verify: false);
            TestHarness.True(replaced.Report.ConfirmationInvalidated, "文件被替换必须使旧确认失效");
            TestHarness.Equal(null, replaced.State.UserConfirmedFingerprint, "替换后不得保留旧指纹");
        });

        harness.Run("多存档：不得静默选择第一个文件", () =>
        {
            using var workspace = new Workspace();
            var run = workspace.Run(
                Files(Save("a.fm", "F1", DateTime.UtcNow), Save("b.fm", "F2", DateTime.UtcNow.AddMinutes(5))),
                verify: true);

            TestHarness.True(run.Report.Resolution.IsAmbiguous, "多存档必须歧义");
            TestHarness.True(!run.Report.VerifyApplied, "不得静默确认任意一个");
            TestHarness.Equal(null, SaveIdentityBinding.CurrentFingerprint(run.Report.Resolution), "不得静默选中第一个");
        });
    }

    private static SaveFileSnapshot[] Files(params SaveFileSnapshot[] files) => files;

    private static SaveFileSnapshot Save(string name, string fileId, DateTime? mtime = null, bool locked = false) => new(
        Path: @"C:\saves\" + name,
        VolumeSerial: "V1",
        FileId: fileId,
        SizeBytes: 4096,
        CreatedUtc: Start,
        LastWriteUtc: mtime ?? Start,
        ContentHash: null,
        IsLocked: locked);

    private sealed class FakeProbe : ISaveFileProbe
    {
        private readonly IReadOnlyList<SaveFileSnapshot> _files;

        public FakeProbe(IReadOnlyList<SaveFileSnapshot> files) => _files = files;

        public IReadOnlyList<SaveFileSnapshot> Probe(bool includeContentHash) => _files;
    }

    private sealed class FakeLocator : IFmProcessLocator
    {
        private readonly int? _pid;
        private readonly DateTime? _start;

        public FakeLocator(int? pid, DateTime? start)
        {
            _pid = pid;
            _start = start;
        }

        public FmProcessLocation Locate() => _pid is null
            ? new FmProcessLocation(null, null, null, Array.Empty<string>(), null)
            : new FmProcessLocation(_pid, @"C:\fake\fm.exe", @"C:\fake\fm", Array.Empty<string>(), _start);
    }

    private sealed class RunResult
    {
        public required SaveIdentityReport Report { get; init; }

        public required SaveIdentityState State { get; init; }
    }

    private sealed class Workspace : IDisposable
    {
        private readonly string _directory = Path.Combine(
            Path.GetTempPath(), "scoutmind-v3292-" + Guid.NewGuid().ToString("N"));

        public Workspace() => Directory.CreateDirectory(_directory);

        public RunResult Run(
            IReadOnlyList<SaveFileSnapshot> files,
            bool verify,
            bool processDetected = true,
            DateTime? processStart = null,
            int processId = 123,
            string? explicitFile = null)
        {
            var statePath = Path.Combine(_directory, "save-identity.json");
            var locator = new FakeLocator(processDetected ? processId : null, processDetected ? processStart ?? Start : null);
            var diagnostics = new FmSaveIdentityDiagnostics(
                detector: new GameBuildDetector(locator, _ => "26620374"),
                probe: new FakeProbe(files),
                store: new SaveIdentityStore(statePath),
                now: () => Start.AddMinutes(1),
                statePath: statePath,
                saveFilePath: explicitFile);

            var report = diagnostics.Analyze(verify, resetSession: false, includeContentHash: false);
            return new RunResult
            {
                Report = report,
                State = new SaveIdentityStore(statePath).Load(),
            };
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(_directory, recursive: true);
            }
            catch (IOException)
            {
                // 临时目录清理失败不影响测试结论。
            }
        }
    }
}
