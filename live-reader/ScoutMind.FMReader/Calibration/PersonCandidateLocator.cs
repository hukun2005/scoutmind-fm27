using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 只读 Person 候选定位器（路线 A 的最小实现）。
///
/// 流程：指针有效性 → 对象头可读 → vtable 属于游戏模块 → 逐字段观测 → 姓名/生日校验。
/// 任何一步失败都返回明确状态，不抛异常到调用方；**永不返回 Verified**。
/// </summary>
public sealed class PersonCandidateLocator
{
    private readonly IMemorySource _memory;
    private readonly PersonCandidateProbe _probe;

    /// <summary>创建定位器。</summary>
    /// <param name="memory">只读内存源。</param>
    public PersonCandidateLocator(IMemorySource memory)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
        _probe = new PersonCandidateProbe(memory);
    }

    /// <summary>定位一个 Person 指针。</summary>
    /// <param name="person">Person 指针。</param>
    /// <param name="candidate">候选布局。</param>
    /// <returns>候选结果。</returns>
    public PersonCandidate Locate(ulong person, PersonLayoutCandidate candidate)
    {
        ArgumentNullException.ThrowIfNull(candidate);

        if (person == 0)
        {
            return Failure(candidate, 0, PersonCandidateStatus.InvalidPointer, "null_person");
        }

        ulong vtable;
        try
        {
            vtable = _memory.Pointer(person);
        }
        catch (MemoryUnreadableException)
        {
            return Failure(candidate, person, PersonCandidateStatus.UnreadableMemory, "unreadable_object_header");
        }

        if (vtable == 0)
        {
            return Failure(candidate, person, PersonCandidateStatus.InvalidPointer, "zero_vtable");
        }

        if (!_memory.InModule(vtable))
        {
            return Failure(candidate, person, PersonCandidateStatus.InvalidObject, "vtable_not_in_module");
        }

        var snapshot = _probe.Observe(person, candidate);
        return FromSnapshot(snapshot, candidate);
    }

    private static PersonCandidate FromSnapshot(PersonCandidateSnapshot snapshot, PersonLayoutCandidate candidate)
    {
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        var dateField = snapshot.Fields.First(field => field.Kind == CandidateFieldKind.DateOfBirth);

        // 约定：候选顺序为 [first, second, common]，与 PERO_FIRST/SECOND/COMMON 一致。
        var first = ValidValue(names, 0);
        var second = ValidValue(names, 1);
        var common = ValidValue(names, 2);

        var display = !string.IsNullOrWhiteSpace(common)
            ? common
            : string.Join(" ", new[] { first, second }.Where(value => !string.IsNullOrWhiteSpace(value))).Trim();

        if (string.IsNullOrWhiteSpace(display))
        {
            var status = names.Any(field => field.FailureReason == "invalid_name_characters")
                ? PersonCandidateStatus.InvalidName
                : PersonCandidateStatus.NameNotFound;
            var reason = status == PersonCandidateStatus.InvalidName ? "invalid_name_characters" : "name_not_found";
            return new PersonCandidate(
                candidate.CandidateId,
                snapshot.PersonPointer,
                status,
                null,
                first,
                second,
                common,
                0,
                0,
                0,
                snapshot.Fields,
                reason);
        }

        if (dateField.FailureReason == "unreadable_date")
        {
            return new PersonCandidate(candidate.CandidateId, snapshot.PersonPointer,
                PersonCandidateStatus.DateOfBirthNotFound, display, first, second, common, 0, 0, 0,
                snapshot.Fields, "date_not_found");
        }

        if (!dateField.DateValid)
        {
            return new PersonCandidate(candidate.CandidateId, snapshot.PersonPointer,
                PersonCandidateStatus.InvalidDateOfBirth, display, first, second, common,
                ParseRaw(dateField.RawValue), 0, 0, snapshot.Fields, "invalid_date");
        }

        var (year, dayOfYear) = ParseDecoded(dateField.DecodedValue);

        return new PersonCandidate(
            candidate.CandidateId,
            snapshot.PersonPointer,
            PersonCandidateStatus.Candidate,
            display,
            first,
            second,
            common,
            ParseRaw(dateField.RawValue),
            year,
            dayOfYear,
            snapshot.Fields,
            null);
    }

    private static string? ValidValue(IReadOnlyList<PersonFieldObservation> names, int index) =>
        index < names.Count && names[index].StringValid ? names[index].DecodedValue : null;

    private static uint ParseRaw(string? raw) =>
        raw is not null && raw.StartsWith("0x", StringComparison.Ordinal)
        && uint.TryParse(raw.AsSpan(2), System.Globalization.NumberStyles.HexNumber, null, out var value)
            ? value
            : 0;

    private static (int Year, int DayOfYear) ParseDecoded(string? decoded)
    {
        if (string.IsNullOrWhiteSpace(decoded))
        {
            return (0, 0);
        }

        var year = 0;
        var dayOfYear = 0;
        foreach (var part in decoded.Split(' ', StringSplitOptions.RemoveEmptyEntries))
        {
            if (part.Length < 2)
            {
                continue;
            }

            if (part[0] == 'y' && int.TryParse(part.AsSpan(1), out var parsedYear))
            {
                year = parsedYear;
            }
            else if (part[0] == 'd' && int.TryParse(part.AsSpan(1), out var parsedDay))
            {
                dayOfYear = parsedDay;
            }
        }

        return (year, dayOfYear);
    }

    private static PersonCandidate Failure(
        PersonLayoutCandidate candidate,
        ulong person,
        PersonCandidateStatus status,
        string reason) =>
        new(candidate.CandidateId, person, status, null, null, null, null, 0, 0, 0,
            Array.Empty<PersonFieldObservation>(), reason);
}
