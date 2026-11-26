using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 本次校准运行现场检测到的环境信息。
///
/// 这些值只能来自本次运行；不得用历史记录直接作为通过依据。
/// </summary>
/// <param name="ProcessId">目标进程 ID。</param>
/// <param name="ProcessName">目标进程名（不含路径）。</param>
/// <param name="GameVersion">游戏版本（如 <c>27.1</c>）。</param>
/// <param name="BuildNumber">Steam 构建号。</param>
/// <param name="PluginVersion">game_plugin.dll 版本。</param>
/// <param name="GateStatus">版本闸门状态文本。</param>
/// <param name="AllowScan">闸门是否允许扫描/读取。</param>
/// <param name="AccessDenied">是否因权限被拒绝。</param>
public sealed record CalibrationEnvironment(
    int? ProcessId,
    string? ProcessName,
    string? GameVersion,
    string? BuildNumber,
    string? PluginVersion,
    string? GateStatus,
    bool AllowScan,
    bool AccessDenied)
{
    /// <summary>无法检测环境时使用（所有字段为未知）。</summary>
    public static CalibrationEnvironment Unknown { get; } =
        new(null, null, null, null, null, null, false, false);
}

/// <summary>校准选项。</summary>
/// <param name="ReadCount">同一对象重复读取次数（至少 2 次才做稳定性判断）。</param>
/// <param name="SampleCount">跨区域抽样数量。</param>
/// <param name="LocateLimit">堆扫描最多定位的对象数（用于跨区域抽样）。</param>
/// <param name="MaxOffset">候选偏移扫描上限。</param>
/// <param name="IncludeOffsetSweep">是否附带旧的偏移扫描结果。</param>
/// <param name="DryRun">只检测环境，不读取球员对象。</param>
public sealed record PersonCalibrationOptions(
    int ReadCount = 3,
    int SampleCount = 24,
    int LocateLimit = 240,
    uint MaxOffset = 0x400,
    bool IncludeOffsetSweep = true,
    bool DryRun = false);

/// <summary>一次读取的原始观测。</summary>
/// <param name="ReadIndex">从 1 开始的读取序号。</param>
/// <param name="Snapshot">该次读取的候选快照。</param>
public sealed record CalibrationReadEvidence(int ReadIndex, PersonCandidateSnapshot Snapshot);

/// <summary>一个样本的多次读取与稳定性结论。</summary>
/// <param name="SampleIndex">样本序号。</param>
/// <param name="PersonPointer">Person 指针（仅本机诊断使用，脱敏输出会移除）。</param>
/// <param name="Reads">逐次读取证据。</param>
/// <param name="Stable">多次读取是否一致。</param>
/// <param name="StabilityNotes">不一致点（仅记录字段与原因码，不含地址值）。</param>
public sealed record CalibrationSampleEvidence(
    int SampleIndex,
    ulong PersonPointer,
    IReadOnlyList<CalibrationReadEvidence> Reads,
    bool Stable,
    IReadOnlyList<string> StabilityNotes)
{
    /// <summary>第一次读取的快照。</summary>
    public PersonCandidateSnapshot First => Reads[0].Snapshot;
}

/// <summary>某个偏移在抽样球员中的姓名候选统计。</summary>
/// <param name="Offset">候选偏移。</param>
/// <param name="Readable">可解码出非空字符串的样本数。</param>
/// <param name="NameLike">像人名的样本数。</param>
/// <param name="Distinct">去重后的姓名数量。</param>
/// <param name="Samples">最多 5 个示例。</param>
public sealed record CalibrationOffsetSweepRow(
    uint Offset,
    int Readable,
    int NameLike,
    int Distinct,
    IReadOnlyList<string> Samples);

/// <summary>校准报告（JSON 与 Markdown 共用同一份数据）。</summary>
public sealed class PersonCalibrationReport
{
    /// <summary>Schema 版本。</summary>
    public string SchemaVersion { get; init; } = "1.0";

    /// <summary>候选标识。</summary>
    public string CandidateId { get; init; } = string.Empty;

    /// <summary>本次运行检测到的游戏版本。</summary>
    public string GameVersion { get; init; } = "unknown";

    /// <summary>本次运行检测到的构建号。</summary>
    public string BuildNumber { get; init; } = "unknown";

    /// <summary>本次运行检测到的环境。</summary>
    public CalibrationEnvironment Environment { get; init; } = CalibrationEnvironment.Unknown;

    /// <summary>校准时间戳。</summary>
    public DateTimeOffset CalibrationTimestamp { get; init; }

    /// <summary>姓名候选偏移。</summary>
    public IReadOnlyList<uint> NameFieldOffsets { get; init; } = Array.Empty<uint>();

    /// <summary>出生日期候选偏移。</summary>
    public uint DateOfBirthOffset { get; init; }

    /// <summary>定位到的对象总数。</summary>
    public int LocatedTotal { get; init; }

    /// <summary>实际抽样的对象数。</summary>
    public int Sampled { get; init; }

    /// <summary>抽样策略说明。</summary>
    public string SamplingStrategy { get; init; } = "even_stride";

    /// <summary>每个样本的读取次数。</summary>
    public int ReadCount { get; init; }

    /// <summary>是否为 dry-run（未读取对象）。</summary>
    public bool DryRun { get; init; }

    /// <summary>逐样本证据。</summary>
    public IReadOnlyList<CalibrationSampleEvidence> Samples { get; init; } =
        Array.Empty<CalibrationSampleEvidence>();

    /// <summary>旧的偏移扫描结果（仅作为参考，不作为 Verified 依据）。</summary>
    public IReadOnlyList<CalibrationOffsetSweepRow> OffsetSweep { get; init; } =
        Array.Empty<CalibrationOffsetSweepRow>();

    /// <summary>失败原因码计数。</summary>
    public IReadOnlyDictionary<string, int> FailureReasonCounts { get; init; } =
        new Dictionary<string, int>(StringComparer.Ordinal);

    /// <summary>姓名与生日都通过内部校验的样本数。</summary>
    public int StructurallyValidCount { get; init; }

    /// <summary>姓名有效样本数。</summary>
    public int NameValidCount { get; init; }

    /// <summary>生日有效样本数。</summary>
    public int DateValidCount { get; init; }

    /// <summary>多次读取不稳定的样本数。</summary>
    public int UnstableCount { get; init; }

    /// <summary>置信度：结构校验上限 0.5，不稳定或无样本时为 0。</summary>
    public double Confidence { get; init; }

    /// <summary>候选状态；本阶段最高只到 StructurallyValid / Unstable。</summary>
    public CandidateVerificationStatus VerificationStatus { get; init; } = CandidateVerificationStatus.Unverified;

    /// <summary>结论与限制说明。</summary>
    public string Conclusion { get; init; } = string.Empty;
}

/// <summary>
/// 只读 Person 校准引擎。
///
/// 安全边界：只经 <see cref="IMemorySource"/> 读取；不写内存、不改保护属性、不注入；
/// 单个样本失败只记录原因，绝不中断整次校准。
/// </summary>
public sealed class PersonCalibrationEngine
{
    private readonly IMemorySource _memory;
    private readonly PersonCandidateProbe _probe;

    /// <summary>创建校准引擎。</summary>
    /// <param name="memory">只读内存源。</param>
    public PersonCalibrationEngine(IMemorySource memory)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
        _probe = new PersonCandidateProbe(memory);
    }

    /// <summary>
    /// 跨区域等距抽样：把输入按顺序分成若干桶，取每个桶的中点。
    ///
    /// 这样不会像"取前 N 个"那样集中在堆扫描的起始区域。
    /// </summary>
    /// <param name="items">已定位对象。</param>
    /// <param name="count">目标样本数。</param>
    /// <returns>抽样结果（顺序与输入一致）。</returns>
    public static IReadOnlyList<T> SelectEvenly<T>(IReadOnlyList<T> items, int count)
    {
        ArgumentNullException.ThrowIfNull(items);
        if (items.Count == 0 || count <= 0)
        {
            return Array.Empty<T>();
        }

        if (items.Count <= count)
        {
            return items.ToArray();
        }

        var selected = new List<T>(count);
        for (var index = 0; index < count; index++)
        {
            var bucketStart = (int)((long)index * items.Count / count);
            var bucketEnd = (int)((long)(index + 1) * items.Count / count);
            var midpoint = bucketStart + Math.Max(0, (bucketEnd - bucketStart) / 2);
            selected.Add(items[Math.Min(midpoint, items.Count - 1)]);
        }

        return selected;
    }

    /// <summary>执行校准。</summary>
    /// <param name="candidate">候选布局。</param>
    /// <param name="locatedPersons">已定位的 Person 指针（顺序即堆扫描顺序）。</param>
    /// <param name="environment">本次运行检测到的环境。</param>
    /// <param name="options">校准选项。</param>
    /// <param name="timestamp">校准时间戳；默认当前时间。</param>
    /// <returns>校准报告。</returns>
    public PersonCalibrationReport Run(
        PersonLayoutCandidate candidate,
        IReadOnlyList<ulong> locatedPersons,
        CalibrationEnvironment environment,
        PersonCalibrationOptions? options = null,
        DateTimeOffset? timestamp = null)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        ArgumentNullException.ThrowIfNull(locatedPersons);
        ArgumentNullException.ThrowIfNull(environment);

        var settings = options ?? new PersonCalibrationOptions();
        var sampled = SelectEvenly(locatedPersons, Math.Max(0, settings.SampleCount));

        if (settings.DryRun)
        {
            return BuildReport(candidate, environment, timestamp, sampled.Count, settings, sampled, true,
                Array.Empty<CalibrationSampleEvidence>(),
                Array.Empty<CalibrationOffsetSweepRow>(),
                new Dictionary<string, int>(StringComparer.Ordinal),
                0, 0, 0, 0, 0, CandidateVerificationStatus.Unverified,
                "dry-run：只检测环境，未读取任何球员对象。");
        }

        var readCount = Math.Max(2, settings.ReadCount);
        var samples = new List<CalibrationSampleEvidence>(sampled.Count);
        foreach (var (person, index) in sampled.Select((value, position) => (value, position)))
        {
            samples.Add(ObserveSample(index, person, candidate, readCount));
        }

        var failureReasons = new Dictionary<string, int>(StringComparer.Ordinal);
        var structurallyValid = 0;
        var nameValid = 0;
        var dateValid = 0;
        foreach (var sample in samples)
        {
            var first = sample.First;
            var names = first.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
            var hasName = names.Any(field => field.StringValid);
            var dateField = first.Fields.First(field => field.Kind == CandidateFieldKind.DateOfBirth);
            if (hasName)
            {
                nameValid++;
            }

            if (dateField.DateValid)
            {
                dateValid++;
            }

            if (hasName && dateField.DateValid)
            {
                structurallyValid++;
            }

            foreach (var field in first.Fields)
            {
                if (field.FailureReason is { } reason)
                {
                    failureReasons[reason] = failureReasons.GetValueOrDefault(reason) + 1;
                }
            }
        }

        var unstable = samples.Count(sample => !sample.Stable);
        var sweep = settings.IncludeOffsetSweep && sampled.Count > 0
            ? BuildOffsetSweep(sampled, settings.MaxOffset)
            : Array.Empty<CalibrationOffsetSweepRow>();

        var status = samples.Count == 0
            ? CandidateVerificationStatus.Unverified
            : unstable > 0
                ? CandidateVerificationStatus.Unstable
                : structurallyValid == samples.Count
                    ? CandidateVerificationStatus.StructurallyValid
                    : CandidateVerificationStatus.Unverified;

        var confidence = unstable > 0 || samples.Count == 0
            ? 0
            : Math.Round(0.5 * structurallyValid / samples.Count, 2);

        var conclusion = samples.Count == 0
            ? "未定位到可用样本；请确认游戏已加载存档且版本闸门允许扫描。"
            : $"抽样 {samples.Count}/{locatedPersons.Count}：姓名有效 {nameValid}，生日有效 {dateValid}，"
              + $"结构校验通过 {structurallyValid}，不稳定 {unstable}。"
              + "结构校验通过不等于人工核对；本报告不构成 Mark(Verified) 依据。";

        return BuildReport(candidate, environment, timestamp, locatedPersons.Count, settings, sampled, false,
            samples, sweep, failureReasons, structurallyValid, nameValid, dateValid, unstable,
            confidence, status, conclusion);
    }

    private CalibrationSampleEvidence ObserveSample(
        int index,
        ulong person,
        PersonLayoutCandidate candidate,
        int readCount)
    {
        var reads = new List<CalibrationReadEvidence>(readCount);
        for (var read = 1; read <= readCount; read++)
        {
            reads.Add(new CalibrationReadEvidence(read, _probe.Observe(person, candidate)));
        }

        var notes = new List<string>();
        for (var position = 1; position < reads.Count; position++)
        {
            Compare(reads[position - 1].Snapshot, reads[position].Snapshot, position + 1, notes);
        }

        return new CalibrationSampleEvidence(index, person, reads, notes.Count == 0, notes);
    }

    private static void Compare(
        PersonCandidateSnapshot previous,
        PersonCandidateSnapshot current,
        int readIndex,
        List<string> notes)
    {
        if (previous.PersonPointer != current.PersonPointer)
        {
            notes.Add($"read{readIndex}_person_pointer_changed");
        }

        if (previous.Status != current.Status)
        {
            notes.Add($"read{readIndex}_status_changed");
        }

        if (previous.Fields.Count != current.Fields.Count)
        {
            notes.Add($"read{readIndex}_field_count_changed");
            return;
        }

        for (var index = 0; index < previous.Fields.Count; index++)
        {
            var before = previous.Fields[index];
            var after = current.Fields[index];
            var label = $"0x{before.Offset:X}";
            if (before.Offset != after.Offset)
            {
                notes.Add($"read{readIndex}_field_{label}_offset_changed");
                continue;
            }

            if (!string.Equals(before.RawValue, after.RawValue, StringComparison.Ordinal))
            {
                notes.Add($"read{readIndex}_field_{label}_raw_changed");
            }

            if (!string.Equals(before.DecodedValue, after.DecodedValue, StringComparison.Ordinal))
            {
                notes.Add($"read{readIndex}_field_{label}_decoded_changed");
            }

            if (before.IsValid != after.IsValid)
            {
                notes.Add($"read{readIndex}_field_{label}_validity_changed");
            }

            if (!string.Equals(before.FailureReason, after.FailureReason, StringComparison.Ordinal))
            {
                notes.Add($"read{readIndex}_field_{label}_failure_reason_changed");
            }
        }
    }

    private IReadOnlyList<CalibrationOffsetSweepRow> BuildOffsetSweep(IReadOnlyList<ulong> persons, uint maxOffset)
    {
        var rows = new List<CalibrationOffsetSweepRow>();
        for (var offset = 0u; offset <= maxOffset; offset += 8)
        {
            var readable = 0;
            var nameLike = 0;
            var distinct = new HashSet<string>(StringComparer.Ordinal);
            var samples = new List<string>();
            foreach (var person in persons)
            {
                string? value;
                try
                {
                    value = _memory.NestedString(person + offset);
                }
                catch (MemoryUnreadableException)
                {
                    continue;
                }

                if (string.IsNullOrWhiteSpace(value))
                {
                    continue;
                }

                readable++;
                var plausible = value.Length is >= 2 and <= 40
                                && value.All(ch => char.IsLetter(ch) || ch is ' ' or '\'' or '-' or '.');
                if (!plausible)
                {
                    continue;
                }

                nameLike++;
                distinct.Add(value);
                if (samples.Count < 5)
                {
                    samples.Add(value);
                }
            }

            if (readable > 0)
            {
                rows.Add(new CalibrationOffsetSweepRow(offset, readable, nameLike, distinct.Count, samples));
            }
        }

        return rows;
    }

    private static PersonCalibrationReport BuildReport(
        PersonLayoutCandidate candidate,
        CalibrationEnvironment environment,
        DateTimeOffset? timestamp,
        int locatedTotal,
        PersonCalibrationOptions settings,
        IReadOnlyList<ulong> sampled,
        bool dryRun,
        IReadOnlyList<CalibrationSampleEvidence> samples,
        IReadOnlyList<CalibrationOffsetSweepRow> sweep,
        IReadOnlyDictionary<string, int> failureReasons,
        int structurallyValid,
        int nameValid,
        int dateValid,
        int unstable,
        double confidence,
        CandidateVerificationStatus status,
        string conclusion) =>
        new()
        {
            SchemaVersion = "1.0",
            CandidateId = candidate.CandidateId,
            GameVersion = environment.GameVersion ?? "unknown",
            BuildNumber = environment.BuildNumber ?? "unknown",
            Environment = environment,
            CalibrationTimestamp = timestamp ?? DateTimeOffset.Now,
            NameFieldOffsets = candidate.NameOffsetCandidates,
            DateOfBirthOffset = candidate.DateOfBirthOffsetCandidate,
            LocatedTotal = locatedTotal,
            Sampled = dryRun ? 0 : sampled.Count,
            SamplingStrategy = "even_stride",
            ReadCount = dryRun ? 0 : Math.Max(2, settings.ReadCount),
            DryRun = dryRun,
            Samples = samples,
            OffsetSweep = sweep,
            FailureReasonCounts = failureReasons,
            StructurallyValidCount = structurallyValid,
            NameValidCount = nameValid,
            DateValidCount = dateValid,
            UnstableCount = unstable,
            Confidence = confidence,
            VerificationStatus = status,
            Conclusion = conclusion,
        };
}
