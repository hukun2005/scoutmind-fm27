using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次存档身份诊断的结果。</summary>
/// <param name="Resolution">身份解析结果。</param>
/// <param name="StatePath">状态文件路径。</param>
/// <param name="Diagnostics">诊断信息。</param>
/// <param name="AutomaticSnapshotEnabled">自动快照开关（由 <c>SCOUTMIND_AUTOMATIC_SNAPSHOT</c> 决定）。</param>
/// <param name="VerifyRequested">是否请求了 <c>--verify</c>。</param>
/// <param name="VerifyApplied">本次是否真的完成了用户确认。</param>
public sealed record SaveIdentityReport(
    SaveIdentityResolution Resolution,
    string StatePath,
    IReadOnlyList<string> Diagnostics,
    bool AutomaticSnapshotEnabled,
    bool VerifyRequested,
    bool VerifyApplied);

/// <summary>
/// 存档身份诊断编排：进程/构建 → 存档文件 → 证据解析 → 持久化。
/// 只读取进程元数据与存档文件元数据，不玩猜身份：证据不足就返回 UNKNOWN/DISCOVERED。
/// </summary>
public sealed class FmSaveIdentityDiagnostics
{
    private readonly GameBuildDetector _detector;
    private readonly ISaveFileProbe _probe;
    private readonly SaveIdentityStore _store;
    private readonly Func<DateTime> _now;

    /// <summary>创建诊断编排。</summary>
    /// <param name="detector">游戏/构建检测器。</param>
    /// <param name="probe">存档文件探测。</param>
    /// <param name="store">身份状态存储。</param>
    /// <param name="now">当前时间提供器（便于测试）。</param>
    /// <param name="statePath">状态文件路径。</param>
    /// <param name="saveFilePath">显式指定的存档文件；为空时自动探测。</param>
    public FmSaveIdentityDiagnostics(
        GameBuildDetector? detector = null,
        ISaveFileProbe? probe = null,
        SaveIdentityStore? store = null,
        Func<DateTime>? now = null,
        string? statePath = null,
        string? saveFilePath = null)
    {
        _detector = detector ?? new GameBuildDetector();
        _probe = probe
            ?? (string.IsNullOrWhiteSpace(saveFilePath)
                ? new SaveFileLocator()
                : new SingleSaveFileProbe(saveFilePath));
        _store = store ?? new SaveIdentityStore(statePath);
        _now = now ?? (() => DateTime.UtcNow);
        SaveFilePath = string.IsNullOrWhiteSpace(saveFilePath) ? null : saveFilePath;
    }

    /// <summary>显式指定的存档文件；未指定时为 <c>null</c>。</summary>
    public string? SaveFilePath { get; }

    /// <summary>执行诊断。</summary>
    /// <param name="verify">是否把当前稳定文件身份记录为用户确认。</param>
    /// <param name="resetSession">是否清除上次会话键。</param>
    /// <param name="includeContentHash">是否计算存档内容哈希。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>诊断结果。</returns>
    public SaveIdentityReport Analyze(
        bool verify,
        bool resetSession,
        bool includeContentHash,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var diagnostics = new List<string>();

        var detected = _detector.Detect();
        diagnostics.AddRange(detected.Diagnostics);

        IReadOnlyList<SaveFileSnapshot> files;
        try
        {
            files = _probe.Probe(includeContentHash);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            files = Array.Empty<SaveFileSnapshot>();
            diagnostics.Add($"读取存档文件失败：{ex.Message}");
        }

        if (files.Count == 0)
        {
            diagnostics.Add("没有发现候选存档文件。");
        }

        if (SaveFilePath is not null)
        {
            diagnostics.Add($"使用显式指定的存档文件：{SaveFilePath}");
        }
        else if (_probe is SaveFileLocator locator)
        {
            diagnostics.Add($"候选存档目录：{string.Join("；", locator.SaveDirectories)}");
        }

        var state = _store.Load();
        var process = new GameProcessEvidence(
            detected.ProcessId,
            detected.ProcessStartTime,
            detected.Build,
            detected.PluginVersion,
            detected.ProcessId is not null);

        var confirmed = state.UserConfirmedFingerprint;
        var resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(process, files, null, confirmed));
        var verifyApplied = false;

        if (verify)
        {
            // 显式 --verify 表示用户确认「就是这份存档」：candidate 与 conflict 都允许确认，
            // 后者等价于用户主动切换确认到新存档（旧存档不再被视为当前存档）。
            if (resolution.Status is SaveIdentityStatus.Candidate or SaveIdentityStatus.Conflict
                && resolution.Kind == SaveIdentityKind.SaveFile)
            {
                var previousStatus = resolution.Status;
                confirmed = resolution.Fingerprint;
                resolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(process, files, null, confirmed));
                verifyApplied = resolution.Status == SaveIdentityStatus.Verified;
                if (verifyApplied && previousStatus == SaveIdentityStatus.Conflict)
                {
                    diagnostics.Add("用户确认了与上次不同的存档文件，已将确认切换至当前存档。");
                }
            }

            if (!verifyApplied && resolution.Status != SaveIdentityStatus.Verified)
            {
                diagnostics.Add("--verify 被拒绝：需要唯一且带稳定元数据的存档文件，或需要用户已有确认。");
            }
        }

        var now = _now().ToUniversalTime();
        var nowText = now.ToString("O");
        var next = new SaveIdentityState(
            Fingerprint: resolution.Fingerprint,
            Kind: resolution.Kind,
            Status: resolution.Status,
            Confidence: resolution.Confidence,
            Build: detected.Build,
            LastSessionKey: resetSession ? null : resolution.SessionKey,
            LastSeenAt: nowText,
            UserConfirmedFingerprint: confirmed,
            UserConfirmedAt: resolution.Status == SaveIdentityStatus.Verified
                ? state.UserConfirmedAt ?? nowText
                : state.UserConfirmedAt);

        _store.Save(next);

        if (resetSession)
        {
            diagnostics.Add("已清除上一次会话键（不影响存档身份）。");
        }

        return new SaveIdentityReport(
            resolution,
            _store.FilePath,
            diagnostics,
            SaveIdentityResolver.AutomaticSnapshotEnabled,
            verify,
            verifyApplied);
    }
}
