using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>
/// 一个扫描任务在创建时固定的写入上下文（V3.2.7.4）。
///
/// 为什么必须落盘：Agent 重启后 <c>pending/</c>、<c>processing/</c> 里的文件不能自动改绑到
/// 「当前」存档或新会话。恢复上传前必须比对指纹，只有同一存档才允许用重新验证后的会话续传；
/// <c>operation_id</c> 与 <c>payload_sha256</c> 保持不变，保证后端按 operation 幂等。
/// </summary>
/// <param name="SaveId">后端存档 id；未知时为 0（由后端按活动存档解析）。</param>
/// <param name="IdentityId">创建任务时已验证的存档身份 id。</param>
/// <param name="SessionId">创建任务时的会话 id（重启后会被新会话替换，仅作审计）。</param>
/// <param name="Fingerprint">创建任务时的存档指纹，用于重启后判定是否为同一存档。</param>
/// <param name="OperationId">固定的幂等操作 id。</param>
/// <param name="PayloadSha256">任务报文的 SHA-256，用于检测内容漂移。</param>
/// <param name="CreatedAt">任务创建时间（ISO-8601）。</param>
public sealed record ScanTaskContext(
    int SaveId,
    int IdentityId,
    int SessionId,
    string Fingerprint,
    string OperationId,
    string PayloadSha256,
    string CreatedAt)
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };

    /// <summary>读取任务上下文；文件不存在或损坏时返回 <c>null</c>（调用方必须隔离该任务）。</summary>
    public static ScanTaskContext? TryLoad(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return null;
        }

        try
        {
            var text = File.ReadAllText(path);
            var context = JsonSerializer.Deserialize<ScanTaskContext>(text);
            return context is not null && !string.IsNullOrWhiteSpace(context.OperationId) ? context : null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }

    /// <summary>写入任务上下文；目录不存在时创建。</summary>
    public void Save(string path)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(path, JsonSerializer.Serialize(this, Options));
    }

    /// <summary>是否属于当前已验证的存档（指纹一致才允许恢复上传）。</summary>
    public bool BelongsTo(string? fingerprint) =>
        !string.IsNullOrWhiteSpace(Fingerprint)
        && string.Equals(Fingerprint, fingerprint, StringComparison.Ordinal);

    /// <summary>用重新验证后的会话续传，但保留原 operation_id 与指纹判定。</summary>
    public ScanTaskContext WithSession(int sessionId) => this with { SessionId = sessionId };
}
