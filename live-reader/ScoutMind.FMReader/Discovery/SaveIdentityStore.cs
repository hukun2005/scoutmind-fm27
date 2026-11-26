using System.Text.Json;
using System.Text.Json.Serialization;

namespace ScoutMind.FMReader.Discovery;

/// <summary>存档身份的持久化状态（跨进程）。只保存指纹与结论，不保存原始内存/文件内容。</summary>
/// <param name="Fingerprint">最近一次解析出的指纹。</param>
/// <param name="Kind">指纹来源。</param>
/// <param name="Status">最近一次身份状态。</param>
/// <param name="Confidence">最近一次可信度。</param>
/// <param name="Build">构建号。</param>
/// <param name="LastSessionKey">最近一次的会话键（仅会话）。</param>
/// <param name="LastSeenAt">最近一次观测时间（ISO 8601）。</param>
/// <param name="UserConfirmedFingerprint">用户确认过的指纹。</param>
/// <param name="UserConfirmedAt">用户确认时间。</param>
/// <param name="Generation">
/// 身份代次（V3.2.9.2）：存档身份或运行时会话发生变化时递增。依赖旧代次的 Verified / 临时结果
/// 一律作废，防止晚到的异步任务覆盖新存档状态。
/// </param>
public sealed record SaveIdentityState(
    string? Fingerprint,
    SaveIdentityKind? Kind,
    SaveIdentityStatus? Status,
    SaveIdentityConfidence? Confidence,
    string? Build,
    string? LastSessionKey,
    string? LastSeenAt,
    string? UserConfirmedFingerprint,
    string? UserConfirmedAt,
    int Generation = 0)
{
    /// <summary>空状态。</summary>
    public static SaveIdentityState Empty { get; } = new(
        null, null, null, null, null, null, null, null, null);
}

/// <summary>
/// 存档身份状态的 JSON 持久化（临时文件 + 原子替换）。
/// 文件缺失或损坏时返回空状态，绝不猜测。
/// </summary>
public sealed class SaveIdentityStore
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    private readonly string _path;

    /// <summary>创建存储。</summary>
    /// <param name="path">状态文件路径；为空时使用默认路径。</param>
    public SaveIdentityStore(string? path = null)
    {
        _path = string.IsNullOrWhiteSpace(path) ? DefaultPath : System.IO.Path.GetFullPath(path);
    }

    /// <summary>状态文件路径。</summary>
    public string FilePath => _path;

    /// <summary>默认状态文件路径。</summary>
    public static string DefaultPath => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "ScoutMind",
        "save-identity.json");

    /// <summary>读取状态；缺失或损坏时返回空状态。</summary>
    /// <returns>状态。</returns>
    public SaveIdentityState Load()
    {
        if (!File.Exists(_path))
        {
            return SaveIdentityState.Empty;
        }

        try
        {
            return JsonSerializer.Deserialize<SaveIdentityState>(File.ReadAllText(_path), Options)
                ?? SaveIdentityState.Empty;
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            return SaveIdentityState.Empty;
        }
    }

    /// <summary>写入状态（临时文件 + 原子替换）。</summary>
    /// <param name="state">状态。</param>
    public void Save(SaveIdentityState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        var directory = System.IO.Path.GetDirectoryName(_path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var temporary = _path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(state, Options));
        File.Move(temporary, _path, overwrite: true);
    }
}
