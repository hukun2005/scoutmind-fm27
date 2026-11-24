namespace ScoutMind.FMReader.Discovery;

/// <summary>存档切换检测状态。</summary>
public enum SaveSwitchState
{
    /// <summary>FM27 未运行。</summary>
    NotRunning,

    /// <summary>进程已启动但尚未识别到存档。</summary>
    RunningNoSave,

    /// <summary>身份稳定。</summary>
    Stable,

    /// <summary>疑似变化，先暂停但不下结论。</summary>
    Suspected,

    /// <summary>已确认切换，必须失效旧会话。</summary>
    Confirmed,

    /// <summary>证据冲突，必须人工处理。</summary>
    Conflict,
}

/// <summary>一次观测触发的生命周期事件。</summary>
public enum SaveSwitchEvent
{
    /// <summary>无事件。</summary>
    None,

    /// <summary>首次载入存档。</summary>
    SaveLoaded,

    /// <summary>同一存档发生保存（内容版本变化，身份不变）。</summary>
    SaveSaved,

    /// <summary>疑似切换（尚未达到确认阈值）。</summary>
    SwitchSuspected,

    /// <summary>确认切换。</summary>
    SaveSwitched,

    /// <summary>进程重启后重新识别到同一存档。</summary>
    ProcessRestarted,

    /// <summary>进程退出。</summary>
    ProcessExited,

    /// <summary>读取暂时不稳定，不能据此判断切换。</summary>
    EvidenceUnstable,

    /// <summary>证据冲突。</summary>
    ConflictDetected,
}

/// <summary>一次身份观测。</summary>
/// <param name="ObservedAt">观测时间。</param>
/// <param name="ProcessDetected">是否检测到 FM27 进程。</param>
/// <param name="SessionKey">会话键。</param>
/// <param name="Fingerprint">身份指纹。</param>
/// <param name="IsResolved">指纹是否为已解析身份（不是 unresolved）。</param>
/// <param name="HasConflict">证据是否冲突。</param>
/// <param name="FileVersion">存档文件版本（内容哈希）；只用于判断“保存”。</param>
/// <param name="Build">构建号。</param>
public sealed record SaveObservation(
    DateTime ObservedAt,
    bool ProcessDetected,
    string? SessionKey,
    string? Fingerprint,
    bool IsResolved,
    bool HasConflict,
    string? FileVersion = null,
    string? Build = null);

/// <summary>一次检测结论。</summary>
/// <param name="State">当前状态。</param>
/// <param name="Event">生命周期事件。</param>
/// <param name="PauseTasks">是否必须暂停绑定旧存档的任务。</param>
/// <param name="CancelPendingImports">是否必须取消尚未提交的导入。</param>
/// <param name="InvalidatePreviousSession">是否必须失效旧会话。</param>
/// <param name="PreviousFingerprint">变化前指纹。</param>
/// <param name="CurrentFingerprint">当前指纹。</param>
/// <param name="PreviousSessionKey">变化前会话键。</param>
/// <param name="CurrentSessionKey">当前会话键。</param>
/// <param name="Explanation">解释。</param>
public sealed record SaveSwitchDecision(
    SaveSwitchState State,
    SaveSwitchEvent Event,
    bool PauseTasks,
    bool CancelPendingImports,
    bool InvalidatePreviousSession,
    string? PreviousFingerprint,
    string? CurrentFingerprint,
    string? PreviousSessionKey,
    string? CurrentSessionKey,
    IReadOnlyList<string> Explanation);

/// <summary>
/// 存档切换检测器（有状态）。
///
/// 规则：
/// * 指纹变化必须连续 <c>confirmThreshold</c> 次一致才确认切换；
/// * 短暂的读取失败只进入“疑似”并暂停，不判定切换；
/// * 进程重启后重新识别到同一存档不算切换；
/// * 冲突时不自动选择任何一方；
/// * PID 不变也不代表存档不变。
/// </summary>
public sealed class SaveSwitchDetector
{
    private readonly int _confirmThreshold;

    private SaveSwitchState _state = SaveSwitchState.NotRunning;
    private string? _fingerprint;
    private string? _sessionKey;
    private string? _fileVersion;
    private int _pendingSwitchCount;

    /// <summary>创建检测器。</summary>
    /// <param name="confirmThreshold">确认切换所需的连续观测次数；必须 ≥ 1。</param>
    public SaveSwitchDetector(int confirmThreshold = 2)
    {
        if (confirmThreshold < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(confirmThreshold), "确认阈值必须至少为 1。");
        }

        _confirmThreshold = confirmThreshold;
    }

    /// <summary>当前状态。</summary>
    public SaveSwitchState State => _state;

    /// <summary>当前已确认的指纹。</summary>
    public string? Fingerprint => _fingerprint;

    /// <summary>观测一次。</summary>
    /// <param name="observation">观测。</param>
    /// <returns>结论。</returns>
    public SaveSwitchDecision Observe(SaveObservation observation)
    {
        ArgumentNullException.ThrowIfNull(observation);

        if (!observation.ProcessDetected)
        {
            var hadSession = _state != SaveSwitchState.NotRunning;
            var previousFingerprint = _fingerprint;
            var previousSessionKey = _sessionKey;
            _state = SaveSwitchState.NotRunning;
            _pendingSwitchCount = 0;
            _fingerprint = null;
            _sessionKey = null;
            _fileVersion = null;
            return new SaveSwitchDecision(
                SaveSwitchState.NotRunning,
                hadSession ? SaveSwitchEvent.ProcessExited : SaveSwitchEvent.None,
                PauseTasks: hadSession,
                CancelPendingImports: hadSession,
                InvalidatePreviousSession: hadSession,
                previousFingerprint,
                CurrentFingerprint: null,
                previousSessionKey,
                CurrentSessionKey: null,
                hadSession ? new[] { "FM27 进程已退出，旧会话失效。" } : Array.Empty<string>());
        }

        if (observation.HasConflict)
        {
            _state = SaveSwitchState.Conflict;
            return new SaveSwitchDecision(
                SaveSwitchState.Conflict,
                SaveSwitchEvent.ConflictDetected,
                PauseTasks: true,
                CancelPendingImports: true,
                InvalidatePreviousSession: false,
                _fingerprint,
                observation.Fingerprint,
                _sessionKey,
                observation.SessionKey,
                new[] { "证据冲突：不自动选择任一存档。" });
        }

        if (!observation.IsResolved || string.IsNullOrWhiteSpace(observation.Fingerprint))
        {
            if (_state is SaveSwitchState.NotRunning or SaveSwitchState.RunningNoSave)
            {
                _state = SaveSwitchState.RunningNoSave;
                return new SaveSwitchDecision(
                    _state,
                    SaveSwitchEvent.None,
                    PauseTasks: false,
                    CancelPendingImports: false,
                    InvalidatePreviousSession: false,
                    _fingerprint,
                    observation.Fingerprint,
                    _sessionKey,
                    observation.SessionKey,
                    new[] { "进程已启动，但尚未识别到稳定存档。" });
            }

            _state = SaveSwitchState.Suspected;
            return new SaveSwitchDecision(
                _state,
                SaveSwitchEvent.EvidenceUnstable,
                PauseTasks: true,
                CancelPendingImports: true,
                InvalidatePreviousSession: false,
                _fingerprint,
                observation.Fingerprint,
                _sessionKey,
                observation.SessionKey,
                new[] { "身份证据暂时不可读：先暂停，不据此判定为切换。" });
        }

        var previousFingerprintBeforeAssign = _fingerprint;
        var previousSessionKeyBeforeAssign = _sessionKey;

        if (_sessionKey is null)
        {
            _fingerprint = observation.Fingerprint;
            _sessionKey = observation.SessionKey;
            _fileVersion = observation.FileVersion;
            _state = SaveSwitchState.Stable;
            _pendingSwitchCount = 0;
            return new SaveSwitchDecision(
                _state,
                SaveSwitchEvent.SaveLoaded,
                PauseTasks: false,
                CancelPendingImports: false,
                InvalidatePreviousSession: false,
                previousFingerprintBeforeAssign,
                observation.Fingerprint,
                previousSessionKeyBeforeAssign,
                observation.SessionKey,
                new[] { "首次识别到存档身份。" });
        }

        var sessionChanged = !string.Equals(observation.SessionKey, _sessionKey, StringComparison.Ordinal);
        var fingerprintChanged = !string.Equals(observation.Fingerprint, _fingerprint, StringComparison.Ordinal);
        var fileVersionChanged = !string.Equals(observation.FileVersion, _fileVersion, StringComparison.Ordinal);

        if (sessionChanged)
        {
            _fingerprint = observation.Fingerprint;
            _sessionKey = observation.SessionKey;
            _fileVersion = observation.FileVersion;
            _pendingSwitchCount = 0;

            if (!fingerprintChanged)
            {
                _state = SaveSwitchState.Stable;
                return new SaveSwitchDecision(
                    _state,
                    SaveSwitchEvent.ProcessRestarted,
                    PauseTasks: false,
                    CancelPendingImports: false,
                    InvalidatePreviousSession: true,
                    previousFingerprintBeforeAssign,
                    observation.Fingerprint,
                    previousSessionKeyBeforeAssign,
                    observation.SessionKey,
                    new[] { "进程已重启，但重新识别到同一存档身份。" });
            }

            _state = SaveSwitchState.Confirmed;
            return new SaveSwitchDecision(
                _state,
                SaveSwitchEvent.SaveSwitched,
                PauseTasks: true,
                CancelPendingImports: true,
                InvalidatePreviousSession: true,
                previousFingerprintBeforeAssign,
                observation.Fingerprint,
                previousSessionKeyBeforeAssign,
                observation.SessionKey,
                new[] { "进程重启后载入了另一个存档，旧会话失效。" });
        }

        if (!fingerprintChanged)
        {
            _pendingSwitchCount = 0;
            _state = SaveSwitchState.Stable;
            _fileVersion = observation.FileVersion;
            return new SaveSwitchDecision(
                _state,
                fileVersionChanged ? SaveSwitchEvent.SaveSaved : SaveSwitchEvent.None,
                PauseTasks: false,
                CancelPendingImports: false,
                InvalidatePreviousSession: false,
                previousFingerprintBeforeAssign,
                observation.Fingerprint,
                previousSessionKeyBeforeAssign,
                observation.SessionKey,
                fileVersionChanged
                    ? new[] { "同一存档发生保存：内容版本变化，身份不变。" }
                    : Array.Empty<string>());
        }

        _pendingSwitchCount++;
        if (_pendingSwitchCount >= _confirmThreshold)
        {
            _fingerprint = observation.Fingerprint;
            _fileVersion = observation.FileVersion;
            _pendingSwitchCount = 0;
            _state = SaveSwitchState.Confirmed;
            return new SaveSwitchDecision(
                _state,
                SaveSwitchEvent.SaveSwitched,
                PauseTasks: true,
                CancelPendingImports: true,
                InvalidatePreviousSession: true,
                previousFingerprintBeforeAssign,
                observation.Fingerprint,
                previousSessionKeyBeforeAssign,
                observation.SessionKey,
                new[] { "连续观测确认存档已切换，旧会话失效。" });
        }

        _state = SaveSwitchState.Suspected;
        return new SaveSwitchDecision(
            _state,
            SaveSwitchEvent.SwitchSuspected,
            PauseTasks: true,
            CancelPendingImports: true,
            InvalidatePreviousSession: false,
            previousFingerprintBeforeAssign,
            observation.Fingerprint,
            previousSessionKeyBeforeAssign,
            observation.SessionKey,
            new[] { "身份证据发生变化：先暂停，等待下一次一致观测再确认。" });
    }
}
