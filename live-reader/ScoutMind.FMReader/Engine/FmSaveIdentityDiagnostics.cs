using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次存档身份诊断的结果。</summary>
/// <param name="Resolution">身份解析结果。</param>
/// <param name="StatePath">状态文件路径。</param>
/// <param name="Diagnostics">诊断信息。</param>
/// <param name="AutomaticSnapshotEnabled">自动快照开关（由 <c>SCOUTMIND_AUTOMATIC_SNAPSHOT</c> 决定）。</param>
/// <param name="VerifyRequested">是否请求了 <c>--verify</c>。</param>
/// <param name="VerifyApplied">本次是否真的完成了用户确认。</param>
/// <param name="Generation">身份代次；切档/会话变化时递增。</param>
/// <param name="ConfirmationInvalidated">本次是否因存档变化使旧确认失效。</param>
public sealed record SaveIdentityReport(
    SaveIdentityResolution Resolution,
    string StatePath,
    IReadOnlyList<string> Diagnostics,
    bool AutomaticSnapshotEnabled,
    bool VerifyRequested,
    bool VerifyApplied,
    int Generation = 0,
    bool ConfirmationInvalidated = false);

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

        var explicitSelection = SaveFilePath is not null;
        var generation = state.Generation;
        var confirmed = state.UserConfirmedFingerprint;
        var confirmationInvalidated = false;

        // 第一步：只用运行时证据解析当前存档。历史确认不参与选择，避免切档后仍选中旧存档。
        var resolution = SaveIdentityResolver.Resolve(
            new SaveIdentityInput(process, files, Career: null, UserConfirmedFingerprint: null, ExplicitFileSelection: explicitSelection));
        var currentFingerprint = SaveIdentityBinding.CurrentFingerprint(resolution);

        if (currentFingerprint is not null
            && !string.IsNullOrWhiteSpace(confirmed)
            && !string.Equals(confirmed, currentFingerprint, StringComparison.Ordinal))
        {
            confirmationInvalidated = true;
            generation++;
            diagnostics.Add(
                $"检测到当前存档已变化（确认 {Shorten(confirmed)} → 当前 {Shorten(currentFingerprint)}）：旧确认与依赖旧存档的 Verified 立即失效。");
            confirmed = null;
        }
        else if (currentFingerprint is null && !string.IsNullOrWhiteSpace(confirmed))
        {
            diagnostics.Add(
                "无法唯一确认当前存档：历史确认仅保留用于审计，本次不得用于 Verified（CURRENT_SAVE_UNCONFIRMED）。");
        }

        if (!string.IsNullOrWhiteSpace(state.LastSessionKey)
            && !string.IsNullOrWhiteSpace(resolution.SessionKey)
            && !string.Equals(state.LastSessionKey, resolution.SessionKey, StringComparison.Ordinal))
        {
            generation++;
            diagnostics.Add("游戏会话已变化（新进程/新会话）：依赖旧会话的 Verified 立即失效。");
        }

        if (resetSession)
        {
            generation++;
        }

        generation = Math.Max(generation, 1);

        // 第二步：把（仍有效的）确认作为校验证据，而不是选择依据。
        if (!string.IsNullOrWhiteSpace(confirmed))
        {
            resolution = SaveIdentityResolver.Resolve(
                new SaveIdentityInput(process, files, Career: null, UserConfirmedFingerprint: confirmed, ExplicitFileSelection: explicitSelection));
        }

        var verifyApplied = false;

        if (verify)
        {
            if (explicitSelection)
            {
                diagnostics.Add(
                    "--verify 被拒绝：显式 --save-file 只能证明该文件自身的身份，不能证明它是当前加载存档（CURRENT_SAVE_UNCONFIRMED）。");
            }
            else if (resolution.CurrentSaveConfirmed
                     && (resolution.Status is SaveIdentityStatus.Candidate or SaveIdentityStatus.Conflict)
                     && resolution.Kind == SaveIdentityKind.SaveFile)
            {
                // 显式 --verify 表示用户确认「就是这份存档」：candidate 与 conflict 都允许确认，
                // 后者等价于用户主动切换确认到新存档（旧存档不再被视为当前存档）。
                var previousStatus = resolution.Status;
                confirmed = resolution.Fingerprint;
                resolution = SaveIdentityResolver.Resolve(
                    new SaveIdentityInput(process, files, Career: null, UserConfirmedFingerprint: confirmed, ExplicitFileSelection: false));
                verifyApplied = resolution.Status == SaveIdentityStatus.Verified;
                if (verifyApplied)
                {
                    diagnostics.Add($"已确认当前存档（generation {generation}）。");
                }

                if (verifyApplied && previousStatus == SaveIdentityStatus.Conflict)
                {
                    diagnostics.Add("用户确认了与上次不同的存档文件，已将确认切换至当前存档。");
                }
            }

            if (!verifyApplied && resolution.Status != SaveIdentityStatus.Verified)
            {
                diagnostics.Add("--verify 被拒绝：需要唯一且带稳定元数据的当前存档文件，或需要用户已有确认。");
            }
        }

        var now = _now().ToUniversalTime();
        var nowText = now.ToString("O");
        string? confirmedAt;
        if (string.IsNullOrWhiteSpace(confirmed))
        {
            confirmedAt = null;
        }
        else if (verifyApplied)
        {
            confirmedAt = nowText;
        }
        else
        {
            confirmedAt = state.UserConfirmedAt;
        }

        var next = new SaveIdentityState(
            Fingerprint: resolution.Fingerprint,
            Kind: resolution.Kind,
            Status: resolution.Status,
            Confidence: resolution.Confidence,
            Build: detected.Build,
            LastSessionKey: resetSession ? null : resolution.SessionKey,
            LastSeenAt: nowText,
            UserConfirmedFingerprint: confirmed,
            UserConfirmedAt: confirmedAt,
            Generation: generation);

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
            verifyApplied,
            generation,
            confirmationInvalidated);
    }

    private static string Shorten(string fingerprint) =>
        fingerprint.Length <= 24 ? fingerprint : fingerprint[^12..];
}
