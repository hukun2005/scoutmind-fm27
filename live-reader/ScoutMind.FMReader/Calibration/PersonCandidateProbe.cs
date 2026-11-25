using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// Person 候选字段的只读观测器。
///
/// 安全边界：只经 <see cref="IMemorySource"/> 读取；不写内存、不改保护属性、不注入。
/// 任一字段读取失败都只记录失败原因，不抛到调用方，也不中断其它候选字段。
/// </summary>
public sealed class PersonCandidateProbe
{
    private const ulong MinimumUserPointer = 0x10000;

    private readonly IMemorySource _memory;

    /// <summary>创建观测器。</summary>
    /// <param name="memory">只读内存源。</param>
    public PersonCandidateProbe(IMemorySource memory)
    {
        _memory = memory ?? throw new ArgumentNullException(nameof(memory));
    }

    /// <summary>观测一个 Person 指针在给定候选布局下的每个字段。</summary>
    /// <param name="person">Person 指针。</param>
    /// <param name="candidate">候选布局。</param>
    /// <returns>逐字段观测结果。</returns>
    public PersonCandidateSnapshot Observe(ulong person, PersonLayoutCandidate candidate)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        var fields = new List<PersonFieldObservation>(candidate.NameOffsetCandidates.Count + 1);

        if (person == 0)
        {
            foreach (var offset in candidate.NameOffsetCandidates)
            {
                fields.Add(NullPerson(CandidateFieldKind.NestedName, offset));
            }

            fields.Add(NullPerson(CandidateFieldKind.DateOfBirth, candidate.DateOfBirthOffsetCandidate));
            return new PersonCandidateSnapshot(
                candidate.CandidateId,
                0,
                fields,
                CandidateVerificationStatus.Rejected,
                "Person 指针为 0");
        }

        foreach (var offset in candidate.NameOffsetCandidates)
        {
            fields.Add(ObserveName(person, offset));
        }

        fields.Add(ObserveDateOfBirth(person, candidate.DateOfBirthOffsetCandidate));

        var nameValid = fields.Any(field => field.Kind == CandidateFieldKind.NestedName && field.StringValid);
        var dateValid = fields.First(field => field.Kind == CandidateFieldKind.DateOfBirth).DateValid;
        var objectReadable = fields.Any(field => field.FailureReason is not ("unreadable_pointer_slot" or "unreadable_date"));

        var status = !objectReadable
            ? CandidateVerificationStatus.Rejected
            : nameValid && dateValid
                ? CandidateVerificationStatus.StructurallyValid
                : CandidateVerificationStatus.Unverified;

        var note = status switch
        {
            CandidateVerificationStatus.Rejected => "对象完全不可读",
            CandidateVerificationStatus.StructurallyValid => "姓名与出生日期均通过内部校验；仍需人工核对后才能 Verified",
            _ => nameValid ? "姓名有效但出生日期无效" : dateValid ? "出生日期有效但姓名不可读" : "姓名与出生日期均未通过校验",
        };

        return new PersonCandidateSnapshot(candidate.CandidateId, person, fields, status, note);
    }

    private PersonFieldObservation ObserveName(ulong person, uint offset)
    {
        const CandidateFieldKind kind = CandidateFieldKind.NestedName;
        const string readType = "nested_string(ptr→ptr→utf8@inner+4)";

        ulong pointer;
        try
        {
            pointer = _memory.Pointer(person + offset);
        }
        catch (MemoryUnreadableException)
        {
            return new(kind, offset, readType, null, null, false, false, false, "unreadable_pointer_slot");
        }

        if (pointer == 0)
        {
            return new(kind, offset, readType, "0x0", null, false, false, false, "zero_pointer");
        }

        if (pointer < MinimumUserPointer || (pointer & 0x7) != 0)
        {
            return new(kind, offset, readType, $"0x{pointer:X}", null, false, false, false, "implausible_pointer");
        }

        if (!_memory.IsReadable(pointer, 1))
        {
            return new(kind, offset, readType, $"0x{pointer:X}", null, false, false, false, "unreadable_pointer_target");
        }

        string? value;
        try
        {
            value = _memory.NestedString(person + offset);
        }
        catch (MemoryUnreadableException)
        {
            return new(kind, offset, readType, $"0x{pointer:X}", null, true, false, false, "unreadable_string");
        }

        if (string.IsNullOrWhiteSpace(value))
        {
            return new(kind, offset, readType, $"0x{pointer:X}", null, true, false, false, "empty_string");
        }

        var valid = IsPlausibleName(value);
        return new(
            kind,
            offset,
            readType,
            $"0x{pointer:X}",
            value,
            true,
            valid,
            false,
            valid ? null : "invalid_name_characters");
    }

    private PersonFieldObservation ObserveDateOfBirth(ulong person, uint offset)
    {
        const CandidateFieldKind kind = CandidateFieldKind.DateOfBirth;
        const string readType = "u32(fm_date: year=hi16, day_of_year=lo9)";

        uint raw;
        try
        {
            raw = _memory.UInt32(person + offset);
        }
        catch (MemoryUnreadableException)
        {
            return new(kind, offset, readType, null, null, false, false, false, "unreadable_date");
        }

        var (year, dayOfYear) = FmDate.Decode(raw);
        var valid = year is >= 1900 and <= 2100 && dayOfYear is >= 1 and <= 366;
        return new(
            kind,
            offset,
            readType,
            $"0x{raw:X8}",
            valid ? $"y{year} d{dayOfYear}" : null,
            false,
            false,
            valid,
            valid ? null : "invalid_date");
    }

    private static PersonFieldObservation NullPerson(CandidateFieldKind kind, uint offset) => new(
        kind,
        offset,
        kind == CandidateFieldKind.NestedName ? "nested_string(ptr→ptr→utf8@inner+4)" : "u32(fm_date)",
        null,
        null,
        false,
        false,
        false,
        "null_person");

    /// <summary>姓名合理性：非空、长度合理、只含字母与常见分隔符，且至少一个字母。</summary>
    /// <param name="value">解码后的字符串。</param>
    /// <returns>合理时为 <c>true</c>。</returns>
    private static bool IsPlausibleName(string value)
    {
        if (value.Length is < 1 or > 64)
        {
            return false;
        }

        var hasLetter = false;
        foreach (var ch in value)
        {
            if (char.IsLetter(ch))
            {
                hasLetter = true;
                continue;
            }

            if (ch is ' ' or '\'' or '-' or '.')
            {
                continue;
            }

            return false;
        }

        return hasLetter;
    }
}
