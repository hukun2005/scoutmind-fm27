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

/// <summary>
/// 后端导入任务状态。<c>Status</c> 直接来自 <c>import_jobs.status</c>：
/// <c>running</c> / <c>succeeded</c> / <c>partial</c> / <c>failed</c>。
/// </summary>
/// <param name="Id">任务 id。</param>
/// <param name="ScanId">扫描 id。</param>
/// <param name="Status">后端状态。</param>
/// <param name="PlayerCount">已写入的球员快照数。</param>
/// <param name="TransferCount">已写入的转会数。</param>
public sealed record BackendJobState(int Id, string ScanId, string Status, int PlayerCount, int TransferCount)
{
    /// <summary>后端是否已经结束该任务（成功、部分成功或失败）。</summary>
    public bool IsTerminal => Status is "succeeded" or "partial" or "failed";

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

        _endpoint = baseUri.ToString().TrimEnd('/') + "/imports/scan";
        _importsEndpoint = baseUri.ToString().TrimEnd('/') + "/imports";
        _apiToken = string.IsNullOrWhiteSpace(apiToken) ? null : apiToken.Trim();
        _httpClient = handler is null ? new HttpClient() : new HttpClient(handler);
        _httpClient.Timeout = timeout <= TimeSpan.Zero ? TimeSpan.FromSeconds(60) : timeout;
    }

    /// <summary>同步地址，便于日志与排错。</summary>
    public string Endpoint => _endpoint;

    /// <summary>登记一次自动采集状态；失败不抛出，返回 false。</summary>
    public async Task<bool> PostCaptureAsync(object body, CancellationToken cancellationToken)
    {
        try
        {
            var url = _endpoint.Replace("/imports/scan", "/captures", StringComparison.Ordinal);
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

    /// <summary>上传一份已转换好的扫描协议报文。</summary>
    /// <param name="payload">UTF-8 编码的协议 JSON（见 <c>docs/DATA_PROTOCOL.md</c>）。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>同步结果；不会抛出网络异常，失败通过返回值表达。</returns>
    public async Task<BackendSyncResult> PostScanAsync(byte[] payload, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(payload);
        ObjectDisposedException.ThrowIf(_disposed, this);

        string? transportError = null;
        for (var attempt = 1; attempt <= 2; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
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
            catch (Exception ex) when ((ex is HttpRequestException or TaskCanceledException)
                                       && !cancellationToken.IsCancellationRequested)
            {
                transportError = ex.Message;
                if (attempt == 2)
                {
                    break;
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

            using var response = await _httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            using var document = JsonDocument.Parse(body);
            if (!document.RootElement.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
            {
                return null;
            }

            foreach (var item in items.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object) continue;
                var id = item.TryGetProperty("id", out var idValue) && idValue.TryGetInt32(out var parsedId) ? parsedId : 0;
                var status = item.TryGetProperty("status", out var statusValue) ? statusValue.GetString() : null;
                if (string.IsNullOrWhiteSpace(status)) continue;
                var players = item.TryGetProperty("player_count", out var playerValue) && playerValue.TryGetInt32(out var parsedPlayers)
                    ? parsedPlayers
                    : 0;
                var transfers = item.TryGetProperty("transfer_count", out var transferValue) && transferValue.TryGetInt32(out var parsedTransfers)
                    ? parsedTransfers
                    : 0;
                return new BackendJobState(id, scanId, status, players, transfers);
            }

            return null;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            return null;
        }
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
