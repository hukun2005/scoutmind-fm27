using System.Text.Json;

namespace ScoutMind.Agent;

/// <summary>读取器输出的一条身份证据（只含规范化哈希，不含原始内容）。</summary>
public sealed record SaveIdentityEvidence(
    string Type,
    string Source,
    string Hash,
    string? Version,
    string? Confidence,
    string? ObservedAt,
    string? Detail);

/// <summary>读取器身份诊断的完整可转发视图；仅用于上报，不代表后端结论。</summary>
public sealed record SaveIdentitySnapshot(
    string Status,
    string? Fingerprint,
    int FingerprintVersion,
    string? Kind,
    string? Confidence,
    string? SessionKey,
    string? GameBuild,
    string? PluginVersion,
    bool Ambiguous,
    bool SnapshotEligible,
    bool AutomaticSnapshotEnabled,
    IReadOnlyList<SaveIdentityEvidence> Evidence);

/// <summary>
/// 存档身份安全门判定。只有读取器明确给出 <c>status=verified</c>、<c>snapshot_eligible=true</c>
/// 且 <c>automatic_snapshot_enabled=true</c> 时才允许继续采集。
/// 本版本读取器恒返回 <c>snapshot_eligible=false</c>，因此这里必然 BLOCKED——这是有意为之：
/// 数据安全高于自动化便利，直到身份体系经过真实环境验收。
/// </summary>
/// <param name="Allowed">是否允许继续采集。</param>
/// <param name="Status">读取器给出的身份状态。</param>
/// <param name="Fingerprint">存档身份指纹。</param>
/// <param name="Kind">身份来源（save_file / game_internal / unresolved）。</param>
/// <param name="Confidence">可信度。</param>
/// <param name="SessionKey">会话键；用于检测同一进程内的存档切换。</param>
/// <param name="GameBuild">游戏构建号。</param>
/// <param name="SnapshotEligible">读取器是否判定该身份可参与自动快照评估。</param>
/// <param name="AutomaticSnapshotEnabled">自动快照总开关。</param>
/// <param name="Reasons">阻断原因。</param>
public sealed record SaveIdentityGate(
    bool Allowed,
    string Status,
    string? Fingerprint,
    string? Kind,
    string? Confidence,
    string? SessionKey,
    string? GameBuild,
    bool SnapshotEligible,
    bool AutomaticSnapshotEnabled,
    IReadOnlyList<string> Reasons)
{
    /// <summary>可上报给后端的完整身份视图；解析失败或 BLOCKED 时为 <c>null</c>。</summary>
    public SaveIdentitySnapshot? Snapshot { get; init; }

    /// <summary>构造 BLOCKED 判定。</summary>
    /// <param name="reasons">原因。</param>
    /// <returns>判定。</returns>
    public static SaveIdentityGate Blocked(params string[] reasons) =>
        new(false, "BLOCKED", null, null, null, null, null, false, false, reasons);

    /// <summary>身份 + 会话的复合键；任一缺失时为 <c>null</c>。</summary>
    public string? ChangeKey =>
        string.IsNullOrWhiteSpace(Fingerprint) || string.IsNullOrWhiteSpace(SessionKey)
            ? null
            : $"{Fingerprint}@{SessionKey}";
}

/// <summary>
/// 解析读取器 <c>save-identity --json</c> 的身份判定。
/// 代理层不重新计算身份，只消费读取器结论；解析失败、字段缺失、状态非 verified 一律 BLOCKED。
/// </summary>
public static class ReaderSaveIdentityGate
{
    private static readonly HashSet<string> StrongEvidenceTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "game_internal_save_id",
        "world_id",
        "save_file_metadata",
    };

    /// <summary>解析读取器输出。</summary>
    /// <param name="json">读取器 stdout。</param>
    /// <returns>判定。</returns>
    public static SaveIdentityGate Parse(string json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return SaveIdentityGate.Blocked("读取器没有输出存档身份诊断。");
        }

        try
        {
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return SaveIdentityGate.Blocked("存档身份诊断不是 JSON 对象。");
            }

            var status = ReadString(root, "status")?.ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(status))
            {
                return SaveIdentityGate.Blocked("存档身份诊断缺少 status。");
            }

            var identity = ReadObject(root, "identity");
            var session = ReadObject(root, "session");
            var fingerprint = identity is { } id ? ReadString(id, "fingerprint") : null;
            var kind = identity is { } id2 ? ReadString(id2, "kind") : null;
            var confidence = identity is { } id3 ? ReadString(id3, "confidence") : null;
            var sessionKey = session is { } se ? ReadString(se, "session_key") : null;
            var gameBuild = session is { } se2 ? ReadString(se2, "game_build") : null;

            var snapshotEligible = ReadBool(root, "snapshot_eligible");
            var automaticSnapshotEnabled = ReadBool(root, "automatic_snapshot_enabled");
            var snapshot = new SaveIdentitySnapshot(
                status,
                fingerprint,
                ReadInt(identity, "version") ?? 1,
                kind,
                confidence,
                sessionKey,
                gameBuild,
                session is { } se3 ? ReadString(se3, "plugin_version") : null,
                ReadBool(root, "ambiguous"),
                snapshotEligible,
                automaticSnapshotEnabled,
                ReadEvidence(root));

            var reasons = ReadStringArray(root, "conflicts");
            reasons.AddRange(ReadStringArray(root, "missing_evidence"));
            var explanation = ReadString(root, "explanation");
            if (!string.IsNullOrWhiteSpace(explanation))
            {
                reasons.Add(explanation);
            }

            if (!string.Equals(status, "verified", StringComparison.Ordinal))
            {
                if (reasons.Count == 0)
                {
                    reasons.Add(status switch
                    {
                        "conflict" => "存档身份存在冲突，已暂停自动采集。",
                        "invalidated" => "存档身份已失效，需要重新识别。",
                        "candidate" => "存档身份仅达到 candidate，未通过验证。",
                        "discovered" => "仅发现存档，尚未完成身份验证。",
                        _ => "未能确定当前 FM27 存档身份。",
                    });
                }

                return new SaveIdentityGate(false, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                    snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
            }

            if (string.IsNullOrWhiteSpace(fingerprint) || string.IsNullOrWhiteSpace(sessionKey))
            {
                reasons.Add("身份声称已验证，但缺少指纹或会话键：按 BLOCKED 处理。");
                return new SaveIdentityGate(false, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                    snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
            }

            if (!HasStrongEvidence(root))
            {
                reasons.Add("身份声称已验证，但缺少第一/第二优先级强证据：按 BLOCKED 处理。");
                return new SaveIdentityGate(false, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                    snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
            }

            if (!automaticSnapshotEnabled)
            {
                reasons.Add("自动快照在本版本保持关闭（automatic_snapshot_enabled=false）。");
                return new SaveIdentityGate(false, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                    snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
            }

            if (!snapshotEligible)
            {
                reasons.Add("存档身份尚未满足自动快照条件（snapshot_eligible=false）。");
                return new SaveIdentityGate(false, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                    snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
            }

            return new SaveIdentityGate(true, status, fingerprint, kind, confidence, sessionKey, gameBuild,
                snapshotEligible, automaticSnapshotEnabled, reasons) { Snapshot = snapshot };
        }
        catch (JsonException)
        {
            return SaveIdentityGate.Blocked("读取器存档身份诊断不是可解析的 JSON。");
        }
    }

    private static bool HasStrongEvidence(JsonElement root)
    {
        if (!root.TryGetProperty("evidence", out var evidence) || evidence.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        foreach (var item in evidence.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var type = ReadString(item, "type");
            if (type is not null && StrongEvidenceTypes.Contains(type))
            {
                return true;
            }
        }

        return false;
    }

    private static JsonElement? ReadObject(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object ? value : null;

    private static IReadOnlyList<SaveIdentityEvidence> ReadEvidence(JsonElement root)
    {
        var result = new List<SaveIdentityEvidence>();
        if (!root.TryGetProperty("evidence", out var evidence) || evidence.ValueKind != JsonValueKind.Array)
        {
            return result;
        }

        foreach (var item in evidence.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var type = ReadString(item, "type");
            var hash = ReadString(item, "hash");
            if (string.IsNullOrWhiteSpace(type) || string.IsNullOrWhiteSpace(hash))
            {
                continue;
            }

            result.Add(new SaveIdentityEvidence(
                type,
                ReadString(item, "source") ?? "unknown",
                hash,
                ReadString(item, "version"),
                ReadString(item, "confidence"),
                ReadString(item, "observed_at"),
                ReadString(item, "detail")));
        }

        return result;
    }

    private static int? ReadInt(JsonElement? root, string name) =>
        root is { } element
        && element.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.Number
        && value.TryGetInt32(out var parsed)
            ? parsed
            : null;

    private static string? ReadString(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static bool ReadBool(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static List<string> ReadStringArray(JsonElement root, string name)
    {
        var result = new List<string>();
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }

        foreach (var item in value.EnumerateArray())
        {
            var text = item.GetString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                result.Add(text);
            }
        }

        return result;
    }
}
