namespace ScoutMind.Agent;

/// <summary>身份/会话登记结果。<c>Ok=false</c> 时本轮不得写入后端。</summary>
public sealed record SaveIdentitySyncResult(bool Ok, int? IdentityId, int? SessionId, string? Error, int? SaveId = null);

/// <summary>
/// 把 Reader 的身份结论登记到后端，并维护会话生命周期（V3.2.7.2 Phase 3）。
///
/// 约束：
/// * 只上报证据与声明，后端有权封顶或拒绝；本地不把 <c>candidate</c> 当作 <c>verified</c>。
/// * 指纹变化即视为存档切换：先失效旧会话，再登记新身份。
/// * 后端不可达或会话未 verified 时返回 <c>Ok=false</c>，本轮不写数据（不伪造成功）。
/// </summary>
public sealed class SaveIdentitySync
{
    private readonly BackendClient _client;
    private readonly string _agentId;

    private int? _identityId;
    private int? _sessionId;
    private int? _saveId;
    private string? _sessionKey;
    private string? _fingerprint;
    private bool _networkLost;

    /// <summary>当前已验证的存档指纹；未登记身份时为 <c>null</c>。</summary>
    public string? Fingerprint => _fingerprint;

    /// <summary>后端按指纹解析出的目标存档；未解析时为 <c>null</c>。</summary>
    public int? SaveId => _saveId;

    /// <summary>本进程最近一次会话登记是否发生在断网恢复之后。</summary>
    public bool Reconnected => _networkLost;

    /// <summary>近期是否发生过网络/后端不可达（诊断用）。</summary>
    public bool NetworkLost => _networkLost;

    /// <summary>创建协调器。</summary>
    /// <param name="client">后端客户端（同一实例复用以保留连接）。</param>
    /// <param name="agentId">Agent 实例标识；默认包含机器名与进程号。</param>
    public SaveIdentitySync(BackendClient client, string? agentId = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _agentId = string.IsNullOrWhiteSpace(agentId)
            ? $"agent-{Environment.MachineName}-{Environment.ProcessId}"
            : agentId.Trim();
    }

    /// <summary>当前可写上下文；未同时持有身份与会话时为 <c>null</c>。</summary>
    public SaveContextQuery? Context =>
        _identityId is { } identityId && _sessionId is { } sessionId
            ? new SaveContextQuery(identityId, sessionId, SaveId: _saveId)
            : null;

    /// <summary>确保身份已注册、会话有效并完成一次心跳。</summary>
    /// <param name="gate">Reader 身份诊断结论。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <param name="saveName">新建存档时使用的显示名；为空时后端按指纹生成。</param>
    public async Task<SaveIdentitySyncResult> EnsureAsync(
        SaveIdentityGate gate,
        CancellationToken cancellationToken,
        string? saveName = null)
    {
        var snapshot = gate.Snapshot;
        if (snapshot is null
            || string.IsNullOrWhiteSpace(snapshot.Fingerprint)
            || string.IsNullOrWhiteSpace(snapshot.SessionKey))
        {
            return Fail("身份诊断缺少指纹或会话键，无法登记后端身份。");
        }

        if (_identityId is not null
            && !string.Equals(_fingerprint, snapshot.Fingerprint, StringComparison.Ordinal))
        {
            // 指纹变化：旧身份下不能写新存档的数据。
            await InvalidateAsync("save_switched", cancellationToken).ConfigureAwait(false);
            _identityId = null;
            _saveId = null;
        }

        if (_identityId is null || _saveId is null)
        {
            // 先按指纹解析后端存档：不同存档必须落在不同 fm_save，绝不共用「当前存档」。
            var resolved = await _client.ResolveSaveAsync(
                new { fingerprint = snapshot.Fingerprint, name = saveName },
                cancellationToken).ConfigureAwait(false);
            if (!resolved.Ok)
            {
                TrackTransportFailure(resolved.StatusCode);
                return Fail(resolved.Error ?? "后端拒绝解析存档。");
            }

            var saveId = resolved.ReadInt("save_id");
            if (saveId is null)
            {
                return Fail("后端未返回 save_id。");
            }

            _saveId = saveId;
        }

        if (_identityId is null)
        {
            var body = new
            {
                fingerprint = snapshot.Fingerprint,
                fingerprint_version = snapshot.FingerprintVersion,
                identity_status = snapshot.Status,
                confidence = snapshot.Confidence,
                kind = snapshot.Kind,
                game_build = snapshot.GameBuild,
                plugin_version = snapshot.PluginVersion,
                ambiguous = snapshot.Ambiguous,
                evidence = snapshot.Evidence.Select(item => new
                {
                    type = item.Type,
                    source = item.Source,
                    hash = item.Hash,
                    version = item.Version,
                    confidence = item.Confidence,
                    observed_at = item.ObservedAt,
                    detail = item.Detail,
                }).ToArray(),
                agent_id = _agentId,
                session_key = StableSessionKey(snapshot),
            };

            var registered = await _client.RegisterSaveIdentityAsync(body, cancellationToken, _saveId).ConfigureAwait(false);
            if (!registered.Ok)
            {
                TrackTransportFailure(registered.StatusCode);
                return Fail(registered.Error ?? "后端拒绝注册存档身份。");
            }

            var identityId = registered.ReadInt("identity_id");
            if (identityId is null)
            {
                return Fail("后端未返回 identity_id。");
            }

            _identityId = identityId;
            _fingerprint = snapshot.Fingerprint;
        }

        var stableKey = StableSessionKey(snapshot);
        if (_sessionId is null || !string.Equals(_sessionKey, stableKey, StringComparison.Ordinal))
        {
            await InvalidateAsync("agent_restarted", cancellationToken).ConfigureAwait(false);

            // 每次新建会话都用带时间戳的键：同一进程切换存档、切回旧存档或重启后，
            // 旧会话可能已 invalidated，复用旧键会被后端拒绝（session_key 全局唯一）。
            var startKey = $"{stableKey}#{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}";
            var started = await _client.StartSaveSessionAsync(
                new
                {
                    identity_id = _identityId,
                    session_key = startKey,
                    game_build = snapshot.GameBuild,
                    plugin_version = snapshot.PluginVersion,
                    agent_id = _agentId,
                },
                cancellationToken,
                _saveId).ConfigureAwait(false);
            if (!started.Ok)
            {
                TrackTransportFailure(started.StatusCode);
                return Fail(started.Error ?? "后端拒绝登记会话。");
            }

            var sessionId = started.ReadInt("session_id");
            if (sessionId is null)
            {
                return Fail("后端未返回 session_id。");
            }

            var status = started.ReadString("status");
            if (!string.Equals(status, "verified", StringComparison.Ordinal))
            {
                // 未验证身份只能得到 created 会话：立即关闭，避免同一 session_key
                // 在身份升级后仍复用旧的非可写会话。
                await _client.InvalidateSaveSessionAsync(
                    sessionId.Value,
                    new { reason = "not_verified" },
                    cancellationToken).ConfigureAwait(false);
                return new SaveIdentitySyncResult(
                    false,
                    _identityId,
                    null,
                    $"后端会话状态为 {status ?? "unknown"}，不可写入。",
                    _saveId);
            }

            _sessionId = sessionId;
            _sessionKey = stableKey;
            return new SaveIdentitySyncResult(true, _identityId, _sessionId, null, _saveId);
        }

        var heartbeat = await _client.HeartbeatSaveSessionAsync(
            _sessionId.Value,
            new
            {
                identity_id = _identityId,
                fingerprint = snapshot.Fingerprint,
                game_build = snapshot.GameBuild,
                // 只在本进程经历过传输失败后的首个心跳上报，用于审计 network_reconnected。
                reconnected = _networkLost,
            },
            cancellationToken).ConfigureAwait(false);
        if (!heartbeat.Ok)
        {
            // 失效/切换/超时：清空本地会话，下一轮重新登记；不得沿用旧会话写数据。
            TrackTransportFailure(heartbeat.StatusCode);
            _sessionId = null;
            _sessionKey = null;
            return new SaveIdentitySyncResult(false, _identityId, null, heartbeat.Error ?? "会话心跳失败。");
        }

        _networkLost = false;
        return new SaveIdentitySyncResult(true, _identityId, _sessionId, null, _saveId);
    }

    private void TrackTransportFailure(int? statusCode)
    {
        if (statusCode is null)
        {
            // 无状态码 = 连接失败/超时；下一次成功心跳必须携带 reconnected。
            _networkLost = true;
        }
    }

    /// <summary>失效当前会话；没有会话时为空操作。</summary>
    public async Task InvalidateAsync(string reason, CancellationToken cancellationToken)
    {
        if (_sessionId is not { } sessionId)
        {
            return;
        }

        await _client.InvalidateSaveSessionAsync(sessionId, new { reason }, cancellationToken).ConfigureAwait(false);
        _sessionId = null;
        _sessionKey = null;
    }

    /// <summary>同一进程 + 同一存档的稳定会话键；真正启动会话时再附加时间戳。</summary>
    private static string StableSessionKey(SaveIdentitySnapshot snapshot)
    {
        var fingerprint = snapshot.Fingerprint ?? "unknown";
        var suffix = fingerprint.Length >= 8 ? fingerprint[^8..] : fingerprint;
        return $"{snapshot.SessionKey}#{suffix}";
    }

    private SaveIdentitySyncResult Fail(string error) => new(false, _identityId, _sessionId, error, _saveId);
}
