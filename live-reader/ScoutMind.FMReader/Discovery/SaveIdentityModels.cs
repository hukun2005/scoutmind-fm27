using System.Security.Cryptography;
using System.Text;

namespace ScoutMind.FMReader.Discovery;

/// <summary>存档身份状态。只有强证据（或稳定文件元数据 + 用户确认）才允许 <see cref="Verified"/>。</summary>
public enum SaveIdentityStatus
{
    /// <summary>没有任何可用证据。</summary>
    Unknown,

    /// <summary>发现了进程/文件，但不足以构成存档身份。</summary>
    Discovered,

    /// <summary>复合证据一致，但尚未达到可验证等级。</summary>
    Candidate,

    /// <summary>已通过强证据或用户确认完成认证。</summary>
    Verified,

    /// <summary>证据互相矛盾，必须人工处理。</summary>
    Conflict,

    /// <summary>既有身份已失效。</summary>
    Invalidated,
}

/// <summary>身份可信度。</summary>
public enum SaveIdentityConfidence
{
    /// <summary>无。</summary>
    None,

    /// <summary>低：只有进程/职业元数据等辅助证据。</summary>
    Low,

    /// <summary>中：稳定文件元数据一致。</summary>
    Medium,

    /// <summary>高：强证据一致。</summary>
    High,

    /// <summary>已认证。</summary>
    Verified,
}

/// <summary>身份指纹的主要来源。</summary>
public enum SaveIdentityKind
{
    /// <summary>游戏内真实 Save ID（当前尚未定位）。</summary>
    InternalSaveId,

    /// <summary>可证明稳定的世界 ID（当前尚未定位）。</summary>
    WorldId,

    /// <summary>存档文件稳定元数据。</summary>
    SaveFile,

    /// <summary>用户显式确认。</summary>
    UserConfirmed,

    /// <summary>无法解析出稳定身份。</summary>
    Unresolved,
}

/// <summary>证据类型。前两类为第一优先级，文件类为第二优先级，其余只能辅助判断。</summary>
public enum SaveEvidenceType
{
    /// <summary>游戏内真实 Save ID。</summary>
    GameInternalSaveId,

    /// <summary>世界 ID。</summary>
    WorldId,

    /// <summary>存档文件稳定元数据（卷序列号 + FileId）。</summary>
    SaveFileMetadata,

    /// <summary>存档文件内容 SHA-256（仅版本证据，不作长期身份）。</summary>
    SaveFileHash,

    /// <summary>存档文件头特征。</summary>
    SaveFileHeader,

    /// <summary>经理/俱乐部/联赛等职业元数据。</summary>
    CareerMetadata,

    /// <summary>进程会话元数据（PID/启动时间/构建/插件）。</summary>
    GameSessionMetadata,

    /// <summary>用户显式确认。</summary>
    UserConfirmed,

    /// <summary>历史数据，未经身份验证。</summary>
    LegacyUnverified,
}

/// <summary>证据来源。</summary>
public enum SaveEvidenceSource
{
    /// <summary>游戏内存。</summary>
    Memory,

    /// <summary>文件系统。</summary>
    File,

    /// <summary>扫描器载荷。</summary>
    Scanner,

    /// <summary>进程/模块。</summary>
    Process,

    /// <summary>用户。</summary>
    User,

    /// <summary>后端。</summary>
    Backend,
}

/// <summary>一条身份证据。</summary>
/// <param name="Type">证据类型。</param>
/// <param name="Source">证据来源。</param>
/// <param name="Hash">证据的规范化哈希（不存原始内存/文件内容）。</param>
/// <param name="Version">证据版本（如文件大小、构建号）。</param>
/// <param name="Confidence">该条证据自身的可信度。</param>
/// <param name="Detail">面向人的说明。</param>
/// <param name="ObservedAt">观测时间（ISO 8601）。</param>
public sealed record SaveEvidence(
    SaveEvidenceType Type,
    SaveEvidenceSource Source,
    string Hash,
    string? Version,
    SaveIdentityConfidence Confidence,
    string Detail,
    string? ObservedAt = null);

/// <summary>进程会话证据。PID 与进程启动时间只用于会话，不进入身份指纹。</summary>
/// <param name="ProcessId">进程号。</param>
/// <param name="ProcessStartTime">进程启动时间（本地时间）。</param>
/// <param name="Build">Steam 构建号。</param>
/// <param name="PluginVersion">game_plugin.dll 版本。</param>
/// <param name="ProcessDetected">是否检测到 FM27 进程。</param>
public sealed record GameProcessEvidence(
    int? ProcessId,
    DateTime? ProcessStartTime,
    string? Build,
    string? PluginVersion,
    bool ProcessDetected);

/// <summary>职业元数据（第三优先级，只作辅助，不能单独认证）。</summary>
/// <param name="ManagerName">人类经理名。</param>
/// <param name="UserClubName">执教俱乐部名。</param>
/// <param name="UserClubUid">俱乐部在该存档内的 UID。</param>
public sealed record CareerEvidence(
    string? ManagerName,
    string? UserClubName,
    string? UserClubUid)
{
    /// <summary>是否有任意一项可用。</summary>
    public bool HasAny =>
        !string.IsNullOrWhiteSpace(ManagerName)
        || !string.IsNullOrWhiteSpace(UserClubName)
        || !string.IsNullOrWhiteSpace(UserClubUid);
}

/// <summary>一个存档文件的观测快照。内容哈希会随保存变化，稳定元数据不会。</summary>
/// <param name="Path">文件路径。</param>
/// <param name="VolumeSerial">卷序列号（十六进制）。</param>
/// <param name="FileId">文件索引（FileId，十六进制）。</param>
/// <param name="SizeBytes">文件大小。</param>
/// <param name="CreatedUtc">创建时间（UTC）。</param>
/// <param name="LastWriteUtc">最后写入时间（UTC）。</param>
/// <param name="ContentHash">内容 SHA-256；未计算时为 <c>null</c>。</param>
/// <param name="IsLocked">是否被其他进程占用（通常是游戏正在使用）。</param>
public sealed record SaveFileSnapshot(
    string Path,
    string? VolumeSerial,
    string? FileId,
    long SizeBytes,
    DateTime CreatedUtc,
    DateTime LastWriteUtc,
    string? ContentHash,
    bool IsLocked)
{
    /// <summary>是否具备可用于身份的稳定文件元数据。</summary>
    public bool HasStableMetadata =>
        !string.IsNullOrWhiteSpace(VolumeSerial) && !string.IsNullOrWhiteSpace(FileId);
}

/// <summary>身份解析输入。</summary>
/// <param name="Process">进程会话证据。</param>
/// <param name="SaveFiles">发现的存档文件。</param>
/// <param name="Career">职业元数据（可选）。</param>
/// <param name="UserConfirmedFingerprint">用户此前确认过的指纹。</param>
public sealed record SaveIdentityInput(
    GameProcessEvidence Process,
    IReadOnlyList<SaveFileSnapshot> SaveFiles,
    CareerEvidence? Career = null,
    string? UserConfirmedFingerprint = null);

/// <summary>身份解析结果。所有字段都用于解释“为什么这样判定”。</summary>
/// <param name="Status">身份状态。</param>
/// <param name="Confidence">可信度。</param>
/// <param name="Fingerprint">复合指纹。</param>
/// <param name="Kind">指纹来源。</param>
/// <param name="SessionKey">会话键（PID + 启动时间 + 构建），只用于会话。</param>
/// <param name="Build">构建号。</param>
/// <param name="PluginVersion">插件版本。</param>
/// <param name="Evidence">使用的证据。</param>
/// <param name="MissingEvidence">缺失的关键证据。</param>
/// <param name="Conflicts">冲突说明。</param>
/// <param name="Explanation">判定解释。</param>
/// <param name="IsAmbiguous">是否无法唯一确定当前存档。</param>
/// <param name="SnapshotEligible">是否允许自动快照；本版本恒为 <c>false</c>。</param>
public sealed record SaveIdentityResolution(
    SaveIdentityStatus Status,
    SaveIdentityConfidence Confidence,
    string Fingerprint,
    SaveIdentityKind Kind,
    string? SessionKey,
    string? Build,
    string? PluginVersion,
    IReadOnlyList<SaveEvidence> Evidence,
    IReadOnlyList<SaveEvidenceType> MissingEvidence,
    IReadOnlyList<string> Conflicts,
    IReadOnlyList<string> Explanation,
    bool IsAmbiguous,
    bool SnapshotEligible);

/// <summary>复合指纹算法。只允许强证据进入指纹；第三优先级证据不参与。</summary>
public static class SaveIdentityFingerprint
{
    /// <summary>当前指纹算法版本。</summary>
    public const int CurrentVersion = 1;

    private const string Prefix = "si:v1:";

    /// <summary>用存档文件稳定元数据生成身份指纹。</summary>
    /// <param name="volumeSerial">卷序列号。</param>
    /// <param name="fileId">文件索引。</param>
    /// <returns>形如 <c>si:v1:file:&lt;sha256&gt;</c> 的指纹。</returns>
    public static string FromSaveFile(string volumeSerial, string fileId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(volumeSerial);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileId);
        return Prefix + "file:" + Sha256($"save-file|{volumeSerial.Trim().ToUpperInvariant()}|{fileId.Trim().ToUpperInvariant()}");
    }

    /// <summary>没有任何强证据时的显式“未解析”指纹（不是身份）。</summary>
    /// <param name="build">构建号。</param>
    /// <returns>形如 <c>si:v1:unresolved:&lt;build&gt;</c> 的指纹。</returns>
    public static string Unresolved(string? build) =>
        Prefix + "unresolved:" + (string.IsNullOrWhiteSpace(build) ? "unknown" : build.Trim());

    /// <summary>规范化哈希，供证据与指纹共用。</summary>
    /// <param name="text">原文。</param>
    /// <returns>小写十六进制 SHA-256。</returns>
    public static string Sha256(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(text));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}

/// <summary>
/// 存档身份解析器。严格按证据等级判定：缺证据即 UNKNOWN，第三优先级不得单独认证，
/// 内容哈希变化不改变身份，存档不明确时不得给出稳定指纹。
/// </summary>
public static class SaveIdentityResolver
{
    /// <summary>自动快照开关。本版本固定关闭。</summary>
    public const bool AutomaticSnapshotEnabled = false;

    /// <summary>解析身份。</summary>
    /// <param name="input">输入。</param>
    /// <returns>解析结果。</returns>
    public static SaveIdentityResolution Resolve(SaveIdentityInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        var process = input.Process;

        if (!process.ProcessDetected || process.ProcessId is null)
        {
            return new SaveIdentityResolution(
                SaveIdentityStatus.Unknown,
                SaveIdentityConfidence.None,
                SaveIdentityFingerprint.Unresolved(process.Build),
                SaveIdentityKind.Unresolved,
                SessionKey: null,
                process.Build,
                process.PluginVersion,
                Array.Empty<SaveEvidence>(),
                AllStrongTypes(),
                Array.Empty<string>(),
                new[] { "没有检测到正在运行的 FM27 进程。" },
                IsAmbiguous: false,
                SnapshotEligible: false);
        }

        var sessionKey = BuildSessionKey(process);
        var evidence = new List<SaveEvidence>
        {
            new(
                SaveEvidenceType.GameSessionMetadata,
                SaveEvidenceSource.Process,
                SaveIdentityFingerprint.Sha256(sessionKey ?? "unknown"),
                process.Build,
                SaveIdentityConfidence.Low,
                "进程会话元数据；只用于会话，不构成存档身份。"),
        };
        var explanation = new List<string>
        {
            $"检测到 FM27 进程 {process.ProcessId}（构建 {process.Build ?? "未知"}，插件 {process.PluginVersion ?? "未知"}）。",
        };
        var missing = new List<SaveEvidenceType> { SaveEvidenceType.GameInternalSaveId, SaveEvidenceType.WorldId };

        if (input.Career is { HasAny: true } career)
        {
            var careerHash = SaveIdentityFingerprint.Sha256(
                $"career|{career.ManagerName}|{career.UserClubName}|{career.UserClubUid}");
            evidence.Add(new SaveEvidence(
                SaveEvidenceType.CareerMetadata,
                SaveEvidenceSource.Scanner,
                careerHash,
                null,
                SaveIdentityConfidence.Low,
                "经理/俱乐部元数据；第三优先级，只能辅助判断。"));
            explanation.Add("使用了经理/俱乐部元数据辅助判断。");
        }

        var files = input.SaveFiles ?? Array.Empty<SaveFileSnapshot>();
        var selection = SelectActiveFile(files);
        if (selection.Ambiguous)
        {
            explanation.Add("存在多个可能的存档文件，无法唯一确定当前存档。");
            evidence.AddRange(files.Take(3).Select(f => FileMetadataEvidence(f, SaveIdentityConfidence.Low)));
            return new SaveIdentityResolution(
                SaveIdentityStatus.Discovered,
                SaveIdentityConfidence.Low,
                SaveIdentityFingerprint.Unresolved(process.Build),
                SaveIdentityKind.Unresolved,
                sessionKey,
                process.Build,
                process.PluginVersion,
                evidence,
                AddSaveFileMissing(missing, files),
                Array.Empty<string>(),
                explanation,
                IsAmbiguous: true,
                SnapshotEligible: false);
        }

        if (selection.File is null)
        {
            explanation.Add("没有找到可用的存档文件。");
            return new SaveIdentityResolution(
                SaveIdentityStatus.Discovered,
                SaveIdentityConfidence.Low,
                SaveIdentityFingerprint.Unresolved(process.Build),
                SaveIdentityKind.Unresolved,
                sessionKey,
                process.Build,
                process.PluginVersion,
                evidence,
                AddSaveFileMissing(missing, files),
                Array.Empty<string>(),
                explanation,
                IsAmbiguous: false,
                SnapshotEligible: false);
        }

        var file = selection.File;
        evidence.Add(FileMetadataEvidence(
            file,
            file.HasStableMetadata ? SaveIdentityConfidence.Medium : SaveIdentityConfidence.Low));

        if (file.ContentHash is { Length: > 0 } hash)
        {
            evidence.Add(new SaveEvidence(
                SaveEvidenceType.SaveFileHash,
                SaveEvidenceSource.File,
                hash,
                file.SizeBytes.ToString(System.Globalization.CultureInfo.InvariantCulture),
                SaveIdentityConfidence.Medium,
                "存档文件内容哈希；保存后可能变化，只作版本证据。"));
        }
        else
        {
            missing.Add(SaveEvidenceType.SaveFileHash);
        }

        if (!file.HasStableMetadata)
        {
            explanation.Add("存档文件缺少稳定元数据（卷序列号/FileId），不能生成稳定身份指纹。");
            return new SaveIdentityResolution(
                SaveIdentityStatus.Discovered,
                SaveIdentityConfidence.Low,
                SaveIdentityFingerprint.Unresolved(process.Build),
                SaveIdentityKind.Unresolved,
                sessionKey,
                process.Build,
                process.PluginVersion,
                evidence,
                missing,
                Array.Empty<string>(),
                explanation,
                IsAmbiguous: false,
                SnapshotEligible: false);
        }

        var fingerprint = SaveIdentityFingerprint.FromSaveFile(file.VolumeSerial!, file.FileId!);
        explanation.Add(
            file.IsLocked
                ? "存档文件被游戏进程占用，按当前存档处理。"
                : "按最近写入的存档文件处理（未能确认被游戏占用）。");

        var conflicts = new List<string>();
        var status = SaveIdentityStatus.Candidate;
        var confidence = SaveIdentityConfidence.Medium;
        var kind = SaveIdentityKind.SaveFile;

        if (!string.IsNullOrWhiteSpace(input.UserConfirmedFingerprint))
        {
            if (string.Equals(input.UserConfirmedFingerprint, fingerprint, StringComparison.Ordinal))
            {
                status = SaveIdentityStatus.Verified;
                confidence = SaveIdentityConfidence.Verified;
                kind = SaveIdentityKind.UserConfirmed;
                evidence.Add(new SaveEvidence(
                    SaveEvidenceType.UserConfirmed,
                    SaveEvidenceSource.User,
                    fingerprint,
                    null,
                    SaveIdentityConfidence.High,
                    "用户已确认该稳定文件身份。"));
                explanation.Add("用户确认 + 稳定文件元数据，达到 VERIFIED。");
            }
            else
            {
                status = SaveIdentityStatus.Conflict;
                conflicts.Add("用户确认的存档指纹与当前文件证据不一致。");
                explanation.Add("身份冲突：不得自动选择任一存档。");
            }
        }

        if (status != SaveIdentityStatus.Verified)
        {
            explanation.Add("缺少游戏内唯一 ID / 世界 ID，最高只能到 CANDIDATE。");
        }

        return new SaveIdentityResolution(
            status,
            confidence,
            fingerprint,
            kind,
            sessionKey,
            process.Build,
            process.PluginVersion,
            evidence,
            missing.Distinct().ToArray(),
            conflicts,
            explanation,
            IsAmbiguous: false,
            SnapshotEligible: false);
    }

    private static SaveEvidence FileMetadataEvidence(SaveFileSnapshot file, SaveIdentityConfidence confidence) => new(
        SaveEvidenceType.SaveFileMetadata,
        SaveEvidenceSource.File,
        file.HasStableMetadata
            ? SaveIdentityFingerprint.Sha256($"file|{file.VolumeSerial}|{file.FileId}")
            : SaveIdentityFingerprint.Sha256($"path|{file.Path}"),
        file.SizeBytes.ToString(System.Globalization.CultureInfo.InvariantCulture),
        confidence,
        file.HasStableMetadata
            ? "存档文件稳定元数据（卷序列号 + FileId）。"
            : "仅有文件路径/大小，不能作为稳定身份。");

    private static (SaveFileSnapshot? File, bool Ambiguous) SelectActiveFile(IReadOnlyList<SaveFileSnapshot> files)
    {
        if (files.Count == 0)
        {
            return (null, false);
        }

        var locked = files.Where(file => file.IsLocked).ToList();
        if (locked.Count == 1)
        {
            return (locked[0], false);
        }

        if (locked.Count > 1)
        {
            return (null, true);
        }

        if (files.Count == 1)
        {
            return (files[0], false);
        }

        return (files.OrderByDescending(file => file.LastWriteUtc).First(), true);
    }

    private static IReadOnlyList<SaveEvidenceType> AddSaveFileMissing(
        List<SaveEvidenceType> missing,
        IReadOnlyList<SaveFileSnapshot> files)
    {
        if (files.Count == 0)
        {
            missing.Add(SaveEvidenceType.SaveFileMetadata);
        }

        return missing.Distinct().ToArray();
    }

    private static IReadOnlyList<SaveEvidenceType> AllStrongTypes() => new[]
    {
        SaveEvidenceType.GameInternalSaveId,
        SaveEvidenceType.WorldId,
        SaveEvidenceType.SaveFileMetadata,
        SaveEvidenceType.SaveFileHash,
    };

    private static string? BuildSessionKey(GameProcessEvidence process)
    {
        if (process.ProcessId is null)
        {
            return null;
        }

        var started = process.ProcessStartTime?.ToUniversalTime().ToString("O") ?? "unknown";
        var build = string.IsNullOrWhiteSpace(process.Build) ? "unknown" : process.Build;
        return $"{process.ProcessId}:{started}:{build}";
    }
}
