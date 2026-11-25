using System.Text.Json;

namespace ScoutMind.FMReader.Discovery;

/// <summary>一个逻辑候选跨读取、跨进程的追踪状态。</summary>
/// <param name="LogicalSignature">逻辑签名（模块 + 结构指纹）。</param>
/// <param name="Module">模块类别。</param>
/// <param name="StructureFingerprint">结构指纹。</param>
/// <param name="FirstSeen">首次发现时间（ISO 8601）。</param>
/// <param name="LastSeen">最近发现时间。</param>
/// <param name="ReadCount">累计读取次数。</param>
/// <param name="ConsecutiveConsistentReads">最近一次稳定性复读的一致次数。</param>
/// <param name="LastRawValue">最近原始值（十六进制）。</param>
/// <param name="LastAddress">最近地址（十六进制，仅当前会话诊断用）。</param>
/// <param name="LastSessionKey">最近观测到的进程会话。</param>
/// <param name="FirstSessionKey">首次发现时的进程会话。</param>
/// <param name="ObservedDates">观测到的日期集合。</param>
/// <param name="VerifiedDates">被界面日期确认过的日期集合。</param>
/// <param name="VerifiedSessionKeys">完成验证的进程会话集合。</param>
/// <param name="IdentitySignature">逻辑身份；存在引用链时为链签名，旧状态可能为空。</param>
/// <param name="ChainSignature">引用链签名（无引用链为 <c>null</c>）。</param>
/// <param name="ChainHops">引用链偏移描述（诊断用）。</param>
/// <param name="ChainLevel">引用链跳数（0 表示没有引用链）。</param>
public sealed record TrackedCandidateState(
    string LogicalSignature,
    string Module,
    string StructureFingerprint,
    string? FirstSeen,
    string? LastSeen,
    int ReadCount,
    int ConsecutiveConsistentReads,
    string? LastRawValue,
    string? LastAddress,
    string? LastSessionKey,
    string? FirstSessionKey,
    IReadOnlyList<string> ObservedDates,
    IReadOnlyList<string> VerifiedDates,
    IReadOnlyList<string> VerifiedSessionKeys,
    string? IdentitySignature = null,
    string? ChainSignature = null,
    string? ChainHops = null,
    int ChainLevel = 0);

/// <summary>一条验证证据。`visible_date` 来自人工观察到的界面日期，`reader_date` 来自内存读取，两者独立记录。</summary>
/// <param name="Kind">证据类型。</param>
/// <param name="Detail">说明。</param>
/// <param name="At">时间（ISO 8601）。</param>
/// <param name="SessionKey">进程会话。</param>
/// <param name="VisibleDate">人工确认的界面日期。</param>
/// <param name="ReaderDate">Reader 读取的日期。</param>
/// <param name="LogicalSignature">候选逻辑签名。</param>
public sealed record DateEvidenceEntry(
    string Kind,
    string Detail,
    string At,
    string? SessionKey,
    string? VisibleDate,
    string? ReaderDate,
    string? LogicalSignature);

/// <summary>
/// 跨读取持久化状态。它保存的是“逻辑身份 + 观测事实 + 验证证据”，不是绝对地址；
/// 绝对地址只作为上一次会话的诊断值保留。
/// </summary>
/// <param name="Build">游戏构建号。</param>
/// <param name="SaveKey">存档身份（当前实现未识别，保持 <c>null</c>）。</param>
/// <param name="LastSessionKey">最近一次观测的进程会话。</param>
/// <param name="LastConfirmedDate">最近一次被界面确认的日期。</param>
/// <param name="LastObservedDate">最近一次读取到的日期。</param>
/// <param name="Candidates">候选追踪状态。</param>
/// <param name="Evidence">证据日志（有上限，避免无限增长）。</param>
/// <param name="LastConfirmedIdentity">最近一次通过界面日期验证的逻辑身份（引用链签名或结构签名）。</param>
public sealed record DateVerificationState(
    string? Build,
    string? SaveKey,
    string? LastSessionKey,
    string? LastConfirmedDate,
    string? LastObservedDate,
    IReadOnlyList<TrackedCandidateState> Candidates,
    IReadOnlyList<DateEvidenceEntry> Evidence,
    string? LastConfirmedIdentity = null)
{
    /// <summary>空状态。</summary>
    public static DateVerificationState Empty { get; } = new(
        null, null, null, null, null, Array.Empty<TrackedCandidateState>(), Array.Empty<DateEvidenceEntry>());
}

/// <summary>
/// 日期验证状态的 JSON 持久化（原子替换）。默认位置在用户本地应用数据目录，
/// CLI 可用 <c>--state &lt;路径&gt;</c> 覆盖，便于测试与隔离。
/// </summary>
public sealed class DateVerificationStore
{
    /// <summary>证据日志最多保留条数。</summary>
    public const int MaxEvidenceEntries = 200;

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    private readonly string _path;

    /// <summary>创建存储。</summary>
    /// <param name="path">状态文件路径；为空时使用默认路径。</param>
    public DateVerificationStore(string? path = null)
    {
        _path = string.IsNullOrWhiteSpace(path) ? DefaultPath : System.IO.Path.GetFullPath(path);
    }

    /// <summary>状态文件路径。</summary>
    public string FilePath => _path;

    /// <summary>默认状态文件路径。</summary>
    public static string DefaultPath => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "ScoutMind",
        "date-verification.json");

    /// <summary>读取状态；文件缺失或损坏时返回空状态（不抛异常）。</summary>
    /// <returns>状态。</returns>
    public DateVerificationState Load()
    {
        if (!File.Exists(_path))
        {
            return DateVerificationState.Empty;
        }

        try
        {
            return JsonSerializer.Deserialize<DateVerificationState>(File.ReadAllText(_path), Options)
                ?? DateVerificationState.Empty;
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            return DateVerificationState.Empty;
        }
    }

    /// <summary>写入状态（临时文件 + 原子替换）。</summary>
    /// <param name="state">状态。</param>
    public void Save(DateVerificationState state)
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
