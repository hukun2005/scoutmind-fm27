using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>
/// 一次后端同步的结果。
/// </summary>
/// <param name="Ok">后端是否接受（HTTP 2xx）。</param>
/// <param name="StatusCode">HTTP 状态码；传输失败时为 <c>null</c>。</param>
/// <param name="ResponseBody">响应体（截断），用于排错。</param>
/// <param name="Error">失败说明；成功时为 <c>null</c>。</param>
/// <param name="Duplicate">后端报告该 <c>scan_id</c> 已导入（幂等命中）。</param>
/// <param name="Attempts">实际请求次数（含一次传输重试）。</param>
public sealed record BackendSyncResult(
    bool Ok,
    int? StatusCode,
    string? ResponseBody,
    string? Error,
    bool Duplicate,
    int Attempts);

/// <summary>写接口必须显式携带的存档上下文；缺失时后端按历史行为放行。</summary>
public sealed record SaveContextQuery(int IdentityId, int SessionId, string? OperationId = null)
{
    /// <summary>追加到写接口的查询串。</summary>
    public string Query => OperationId is null
        ? $"?save_identity_id={IdentityId}&save_session_id={SessionId}"
        : $"?save_identity_id={IdentityId}&save_session_id={SessionId}&operation_id={Uri.EscapeDataString(OperationId)}";
}

/// <summary>一次 JSON 请求的结果（身份注册/会话生命周期使用）。</summary>
public sealed record BackendJsonResult(bool Ok, int? StatusCode, JsonElement? Body, string? Error)
{
    /// <summary>从响应体读取整数属性。</summary>
    public int? ReadInt(string name) =>
        Body is { ValueKind: JsonValueKind.Object } body
        && body.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetInt32(out var parsed)
            ? parsed
            : null;

    /// <summary>从响应体读取字符串属性。</summary>
    public string? ReadString(string name) =>
        Body is { ValueKind: JsonValueKind.Object } body
        && body.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
}

/// <summary>
/// 后端导入任务状态。<c>Status</c> 直接来自 <c>import_jobs.status</c>：
/// <c>running</c> / <c>succeeded</c> / <c>partial</c> / <c>failed</c>。
/// </summary>
/// <param name="Id">任务 id。</param>
/// <param name="ScanId">扫描 id。</param>
/// <param name="Status">后端状态（V3.2.7.4 含 queued/cancel_requested/cancelled）。</param>
/// <param name="PlayerCount">已写入的球员快照数。</param>
/// <param name="TransferCount">已写入的转会数。</param>
/// <param name="AttemptCount">后端记录的尝试次数。</param>
/// <param name="RejectedReason">写入被拒绝时的稳定原因码。</param>
public sealed record BackendJobState(
    int Id,
    string ScanId,
    string Status,
    int PlayerCount,
    int TransferCount,
    int AttemptCount = 0,
    string? RejectedReason = null)
{
    /// <summary>后端是否已经结束该任务（成功、部分成功、失败、拒绝或取消）。</summary>
    public bool IsTerminal => Status is "succeeded" or "partial" or "failed" or "rejected" or "cancelled";

    /// <summary>是否已经完成到可以归档（成功或部分成功）。</summary>
    public bool IsComplete => Status is "succeeded" or "partial";
}

/// <summary>
/// 后端导入客户端：<c>POST {backendBaseUrl}/imports/scan</c>，可选 <c>X-ScoutMind-Token</c> 头。
/// 后端以 <c>scan_id</c> 幂等，因此只在传输层失败时重试一次，避免重复扫描或重复入库。
/// 超时并不等于失败：调用方可以再用 <see cref="GetJobAsync"/> 核实服务端是否已经完成。
/// </summary>
public sealed class BackendClient : IDisposable
{
    private const int MaxResponseChars = 4000;

    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;
    private readonly string _endpoint;
    private readonly string _importsEndpoint;
    private readonly string? _apiToken;
    private bool _disposed;

    /// <summary>创建客户端。</summary>
    /// <param name="backendBaseUrl">后端基础地址，例如 <c>http://127.0.0.1:8000/api/v1</c>。</param>
    /// <param name="apiToken">API Token；为空时不发送认证头（后端须只监听回环地址）。</param>
    /// <param name="timeout">单次请求超时。</param>
    /// <param name="handler">测试用消息处理器。</param>
    public BackendClient(
        string backendBaseUrl,
        string? apiToken,
        TimeSpan timeout,
        HttpMessageHandler? handler = null)
    {
        if (string.IsNullOrWhiteSpace(backendBaseUrl))
        {
            throw new ArgumentException("后端地址不能为空。", nameof(backendBaseUrl));
        }

        if (!Uri.TryCreate(backendBaseUrl.Trim(), UriKind.Absolute, out var baseUri)
            || (baseUri.Scheme != Uri.UriSchemeHttp && baseUri.Scheme != Uri.UriSchemeHttps))
        {
            throw new ArgumentException($"后端地址必须是 http/https 绝对地址：{backendBaseUrl}", nameof(backendBaseUrl));
        }

        _baseUrl = baseUri.ToString().TrimEnd('/');
        _endpoint = _baseUrl + "/imports/scan";
        _importsEndpoint = baseUri.ToString().TrimEnd('/') + "/imports";
        _apiToken = string.IsNullOrWhiteSpace(apiToken) ? null : apiToken.Trim();
        _httpClient = handler is null ? new HttpClient() : new HttpClient(handler);
        _httpClient.Timeout = timeout <= TimeSpan.Zero ? TimeSpan.FromSeconds(60) : timeout;
    }

    /// <summary>同步地址，便于日志与排错。</summary>
    public string Endpoint => _endpoint;

    /// <summary>登记一次自动采集状态；失败不抛出，返回 false。</summary>
    public async Task<bool> PostCaptureAsync(object body, CancellationToken cancellationToken, SaveContextQuery? context = null)
    {
        try
        {
            var url = _baseUrl + "/captures" + (context?.Query ?? string.Empty);
            using var request = new HttpRequestMessage(HttpMethod.Post, url)
            {
                Content = JsonContent.Create(body),
            };
            if (!string.IsNullOrWhiteSpace(_apiToken))
            {
                request.Headers.Add("X-ScoutMind-Token", _apiToken);
            }
            using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return false;
        }
    }

    /// <summary>登记采集开始（必须携带存档上下文）。</summary>
    public Task<BackendJsonResult> StartCaptureAsync(
        object body,
        CancellationToken cancellationToken,
        SaveContextQuery? context = null) =>
        SendJsonAsync(HttpMethod.Post, _baseUrl + "/captures" + (context?.Query ?? string.Empty), body, cancellationToken);

    /// <summary>更新采集状态（失败/完成同样需要上下文）。</summary>
    public Task<BackendJsonResult> UpdateCaptureAsync(
        int captureId,
        object body,
        CancellationToken cancellationToken,
        SaveContextQuery? context = null) =>
        SendJsonAsync(
            HttpMethod.Patch,
            $"{_baseUrl}/captures/{captureId}" + (context?.Query ?? string.Empty),
            body,
            cancellationToken);

    /// <summary>注册/更新存档身份。后端按证据封顶，Agent 不自行宣称 verified。</summary>
    public Task<BackendJsonResult> RegisterSaveIdentityAsync(object body, CancellationToken cancellationToken) =>
        SendJsonAsync(HttpMethod.Post, _baseUrl + "/save-identities/register", body, cancellationToken);

    /// <summary>登记会话；同一 <c>session_key</c> 幂等。</summary>
    public Task<BackendJsonResult> StartSaveSessionAsync(object body, CancellationToken cancellationToken) =>
        SendJsonAsync(HttpMethod.Post, _baseUrl + "/save-sessions/start", body, cancellationToken);

    /// <summary>会话心跳；后端发现身份/指纹变化会使会话失效。</summary>
    public Task<BackendJsonResult> HeartbeatSaveSessionAsync(
        int sessionId,
        object body,
        CancellationToken cancellationToken) =>
        SendJsonAsync(HttpMethod.Post, $"{_baseUrl}/save-sessions/{sessionId}/heartbeat", body, cancellationToken);

    /// <summary>显式失效会话（切换/结束/重启）。</summary>
    public Task<BackendJsonResult> InvalidateSaveSessionAsync(
        int sessionId,
        object body,
        CancellationToken cancellationToken) =>
        SendJsonAsync(HttpMethod.Post, $"{_baseUrl}/save-sessions/{sessionId}/invalidate", body, cancellationToken);

    private async Task<BackendJsonResult> SendJsonAsync(
        HttpMethod method,
        string url,
        object? body,
        CancellationToken cancellationToken)
    {
        try
        {
            using var request = new HttpRequestMessage(method, url);
            if (body is not null)
            {
                request.Content = JsonContent.Create(body);
            }
            if (!string.IsNullOrWhiteSpace(_apiToken))
            {
                request.Headers.TryAddWithoutValidation("X-ScoutMind-Token", _apiToken);
            }

            using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            JsonElement? parsed = null;
            if (!string.IsNullOrWhiteSpace(text))
            {
                try
                {
                    using var document = JsonDocument.Parse(text);
                    parsed = document.RootElement.Clone();
                }
                catch (JsonException)
                {
                    parsed = null;
                }
            }

            var error = response.IsSuccessStatusCode
                ? null
                : $"后端返回 HTTP {(int)response.StatusCode}：{(text.Length <= MaxResponseChars ? text : text[..MaxResponseChars])}";
            return new BackendJsonResult(response.IsSuccessStatusCode, (int)response.StatusCode, parsed, error);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return new BackendJsonResult(false, null, null, $"无法连接后端 {url}：{ex.Message}");
        }
    }

    /// <summary>上传一份已转换好的扫描协议报文。</summary>
    /// <param name="payload">UTF-8 编码的协议 JSON（见 <c>docs/DATA_PROTOCOL.md</c>）。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <param name="context">自动采集必须携带的存档身份/会话；手动同步为 <c>null</c>（历史行为）。</param>
    /// <returns>同步结果；不会抛出网络异常，失败通过返回值表达。</returns>
    public async Task<BackendSyncResult> PostScanAsync(byte[] payload, CancellationToken cancellationToken, SaveContextQuery? context = null)
    {
        ArgumentNullException.ThrowIfNull(payload);
        ObjectDisposedException.ThrowIf(_disposed, this);

        string? transportError = null;
        var url = _endpoint + (context?.Query ?? string.Empty);
        for (var attempt = 1; attempt <= 2; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, url)
                {
                    Content = new ByteArrayContent(payload),
                };
                request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json")
                {
                    CharSet = "utf-8",
                };

                if (_apiToken is not null)
                {
                    request.Headers.TryAddWithoutValidation("X-ScoutMind-Token", _apiToken);
                }

                using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
                var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                var trimmedBody = body.Length <= MaxResponseChars ? body : body[..MaxResponseChars];

                if (!response.IsSuccessStatusCode)
                {
                    return new BackendSyncResult(
                        false,
                        (int)response.StatusCode,
                        trimmedBody,
                        $"后端返回 HTTP {(int)response.StatusCode}。",
                        false,
                        attempt);
                }

                return new BackendSyncResult(
                    true,
                    (int)response.StatusCode,
                    trimmedBody,
                    null,
                    TryReadDuplicate(trimmedBody),
                    attempt);
            }
            catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
            {
                return new BackendSyncResult(
                    false,
                    null,
                    null,
                    $"上传超时：{ex.Message}；服务端可能仍在导入，将按 scan_id 核实",
                    false,
                    attempt);
            }
            catch (HttpRequestException ex) when (!cancellationToken.IsCancellationRequested)
            {
                // 连接失败可以重试；超时不能：服务端可能已经在导入，重试只会制造第二个请求。
                transportError = ex.Message;
                if (attempt < 2)
                {
                    // 单次退避 500ms：断网恢复期间不做高频重试；总次数由循环上限（2 次）约束。
                    await Task.Delay(TimeSpan.FromMilliseconds(500 * attempt), cancellationToken).ConfigureAwait(false);
                }
            }
        }

        return new BackendSyncResult(
            false,
            null,
            null,
            $"无法连接后端 {_endpoint}：{transportError}",
            false,
            2);
    }

    /// <summary>
    /// 按 scan_id 查询最近一次导入任务。用于核实“上传超时但服务端可能已完成”的情况。
    /// </summary>
    /// <param name="scanId">扫描 id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>任务状态；查不到或后端不可达时为 <c>null</c>。</returns>
    public async Task<BackendJobState?> GetJobAsync(string scanId, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(scanId))
        {
            return null;
        }

        try
        {
            var url = $"{_importsEndpoint}?limit=5&scan_id={Uri.EscapeDataString(scanId)}";
            using var request = new HttpRequestMessage(HttpMethod.Get, url);
            if (_apiToken is not null)
            {
                request.Headers.TryAddWithoutValidation("X-ScoutMind-Token", _apiToken);
            }

            // 核实查询必须比上传快：上传已经占满一次 60 s，这里最多再等 15 s。
            using var shortTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            shortTimeout.CancelAfter(TimeSpan.FromSeconds(15));
            using var response = await _httpClient.SendAsync(request, shortTimeout.Token).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            foreach (var job in ParseJobs(body))
            {
                if (string.Equals(job.ScanId, scanId, StringComparison.Ordinal))
                {
                    return job;
                }
            }

            return null;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return null;
        }
    }

    /// <summary>查询最近导入任务，供 <c>jobs list</c> 与诊断使用；后端不可达时返回空列表。</summary>
    public async Task<IReadOnlyList<BackendJobState>> GetRecentJobsAsync(int limit, CancellationToken cancellationToken)
    {
        var safeLimit = Math.Clamp(limit, 1, 200);
        try
        {
            var url = $"{_importsEndpoint}?limit={safeLimit}";
            using var response = await SendGetAsync(url, cancellationToken).ConfigureAwait(false);
            if (response is null || !response.IsSuccessStatusCode)
            {
                return Array.Empty<BackendJobState>();
            }

            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            return ParseJobs(body);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return Array.Empty<BackendJobState>();
        }
    }

    /// <summary>探测后端可达性与认证是否有效（诊断用，不写入任何数据）。</summary>
    /// <returns>成功时的 HTTP 状态码；不可达时为 <c>null</c>。</returns>
    public async Task<int?> ProbeAsync(CancellationToken cancellationToken)
    {
        try
        {
            var url = $"{_importsEndpoint}?limit=1";
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(5));
            using var response = await SendGetAsync(url, timeout.Token).ConfigureAwait(false);
            return response is null ? null : (int)response.StatusCode;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            return null;
        }
    }

    private async Task<HttpResponseMessage?> SendGetAsync(string url, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (_apiToken is not null)
        {
            request.Headers.TryAddWithoutValidation("X-ScoutMind-Token", _apiToken);
        }

        return await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
    }

    private static IReadOnlyList<BackendJobState> ParseJobs(string body)
    {
        using var document = JsonDocument.Parse(body);
        if (!document.RootElement.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<BackendJobState>();
        }

        var jobs = new List<BackendJobState>();
        foreach (var item in items.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object) continue;
            var id = item.TryGetProperty("id", out var idValue) && idValue.TryGetInt32(out var parsedId) ? parsedId : 0;
            var scanId = item.TryGetProperty("scan_id", out var scanValue) ? scanValue.GetString() : null;
            var status = item.TryGetProperty("status", out var statusValue) ? statusValue.GetString() : null;
            if (string.IsNullOrWhiteSpace(status)) continue;
            var players = item.TryGetProperty("player_count", out var playerValue) && playerValue.TryGetInt32(out var parsedPlayers)
                ? parsedPlayers
                : 0;
            var transfers = item.TryGetProperty("transfer_count", out var transferValue) && transferValue.TryGetInt32(out var parsedTransfers)
                ? parsedTransfers
                : 0;
            var attempts = item.TryGetProperty("attempt_count", out var attemptValue) && attemptValue.TryGetInt32(out var parsedAttempts)
                ? parsedAttempts
                : 0;
            var rejected = item.TryGetProperty("rejected_reason", out var rejectedValue) && rejectedValue.ValueKind == JsonValueKind.String
                ? rejectedValue.GetString()
                : null;
            jobs.Add(new BackendJobState(id, scanId ?? string.Empty, status, players, transfers, attempts, rejected));
        }

        return jobs;
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _httpClient.Dispose();
    }

    private static bool TryReadDuplicate(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            return document.RootElement.ValueKind == JsonValueKind.Object
                   && document.RootElement.TryGetProperty("duplicate", out var duplicate)
                   && duplicate.ValueKind == JsonValueKind.True;
        }
        catch (JsonException)
        {
            return false;
        }
    }
}
