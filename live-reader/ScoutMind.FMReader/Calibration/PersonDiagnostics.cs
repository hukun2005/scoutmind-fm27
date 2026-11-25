using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Calibration;

/// <summary>只读诊断摘要（默认 dump 模式）。</summary>
/// <param name="ObservedAt">观测时间。</param>
/// <param name="Environment">本次运行环境。</param>
/// <param name="LayoutName">布局名称。</param>
/// <param name="LocatedCount">定位到的候选 Person 数。</param>
/// <param name="SampledCount">实际抽样数。</param>
/// <param name="ValidObjectCount">结构有效的抽样数。</param>
/// <param name="InvalidPointerCount">指针/结构失败的抽样数。</param>
/// <param name="NameReadCount">姓名读取成功的抽样数。</param>
/// <param name="DateOfBirthReadCount">生日读取成功的抽样数。</param>
/// <param name="AttributeLinkUniqueCount">属性记录唯一关联的抽样数。</param>
/// <param name="ConflictCount">存在多候选或身份冲突的抽样数。</param>
/// <param name="VerifiedCount">Verified 数量（本进程未持久化，固定为 0）。</param>
/// <param name="VerifiedNote">Verified 口径说明。</param>
/// <param name="LinkStatusCounts">关联状态分布。</param>
public sealed record PersonDiagnosticsSummary(
    DateTimeOffset ObservedAt,
    CalibrationEnvironment Environment,
    string LayoutName,
    int LocatedCount,
    int SampledCount,
    int ValidObjectCount,
    int InvalidPointerCount,
    int NameReadCount,
    int DateOfBirthReadCount,
    int AttributeLinkUniqueCount,
    int ConflictCount,
    int VerifiedCount,
    string VerifiedNote,
    IReadOnlyDictionary<string, int> LinkStatusCounts)
{
    /// <summary>姓名读取成功率。</summary>
    public double NameReadSuccessRate => Rate(NameReadCount);

    /// <summary>生日读取成功率。</summary>
    public double DateOfBirthReadSuccessRate => Rate(DateOfBirthReadCount);

    /// <summary>属性记录唯一关联成功率。</summary>
    public double AttributeLinkSuccessRate => Rate(AttributeLinkUniqueCount);

    private double Rate(int count) =>
        SampledCount == 0 ? 0 : Math.Round((double)count / SampledCount, 4);
}

/// <summary>
/// 只读诊断摘要收集器。
///
/// 只经 <see cref="IMemorySource"/> 读取，不做全量进程内存转储，不写任何数据。
/// </summary>
public sealed class PersonDiagnosticsCollector
{
    private readonly IMemorySource _memory;
    private readonly ILayout _layout;
    private readonly PersonCandidateProbe _probe;

    /// <summary>创建收集器。</summary>
    /// <param name="memory">只读内存源。</param>
    /// <param name="layout">布局。</param>
    public PersonDiagnosticsCollector(IMemorySource memory, ILayout layout)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
        _layout = layout ?? throw new ArgumentNullException(nameof(layout));
        _probe = new PersonCandidateProbe(memory);
    }

    /// <summary>收集摘要。</summary>
    /// <param name="located">已定位的球员记录。</param>
    /// <param name="candidate">候选布局。</param>
    /// <param name="environment">本次运行环境。</param>
    /// <param name="sampleCount">抽样数量（默认 60）。</param>
    /// <param name="observedAt">观测时间。</param>
    /// <returns>诊断摘要。</returns>
    public PersonDiagnosticsSummary Collect(
        IReadOnlyList<LocatedObject> located,
        PersonLayoutCandidate candidate,
        CalibrationEnvironment environment,
        int sampleCount = 60,
        DateTimeOffset? observedAt = null)
    {
        ArgumentNullException.ThrowIfNull(located);
        ArgumentNullException.ThrowIfNull(candidate);
        ArgumentNullException.ThrowIfNull(environment);

        var factsReader = new PlayerRecordFactsReader(_memory, _layout);
        var facts = located.Select(factsReader.Read).ToList();
        var indexes = PersonCalibrationEngine.SelectEvenly(
            Enumerable.Range(0, located.Count).ToList(),
            Math.Max(1, sampleCount));
        var linker = new AttributeRecordLinker();
        var statusCounts = new Dictionary<string, int>(StringComparer.Ordinal);
        var valid = 0;
        var invalid = 0;
        var nameRead = 0;
        var dobRead = 0;
        var linkUnique = 0;
        var conflicts = 0;

        foreach (var index in indexes)
        {
            var snapshot = _probe.Observe(located[index].Person, candidate);
            if (snapshot.PersonPointer == 0 || snapshot.Status == CandidateVerificationStatus.Rejected)
            {
                invalid++;
            }
            else
            {
                valid++;
            }

            if (snapshot.Fields.Any(field =>
                    field.Kind == CandidateFieldKind.NestedName && field.StringValid))
            {
                nameRead++;
            }

            if (snapshot.Fields.First(field => field.Kind == CandidateFieldKind.DateOfBirth).DateValid)
            {
                dobRead++;
            }

            var link = linker.Link(PersonIdentityFields.FromFacts(facts[index]), facts);
            var key = link.Status.ToString();
            statusCounts[key] = statusCounts.GetValueOrDefault(key) + 1;
            if (link.Status is AttributeLinkStatus.SingleCandidate or AttributeLinkStatus.VerifiedMatch)
            {
                linkUnique++;
            }

            if (link.Status is AttributeLinkStatus.MultipleCandidates or AttributeLinkStatus.ConflictingIdentity
                || link.Conflicts.Count > 0)
            {
                conflicts++;
            }
        }

        return new PersonDiagnosticsSummary(
            observedAt ?? DateTimeOffset.Now,
            environment,
            _layout.Name,
            located.Count,
            indexes.Count,
            valid,
            invalid,
            nameRead,
            dobRead,
            linkUnique,
            conflicts,
            0,
            "本命令不执行 Mark(Verified)，且进程内没有 Canonical Identity 持久化存储，因此 Verified 计数固定为 0。",
            statusCounts);
    }
}
