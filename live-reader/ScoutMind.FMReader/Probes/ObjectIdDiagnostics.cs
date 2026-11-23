namespace ScoutMind.FMReader.Probes;

/// <summary>Per-object OBJ_DUNI diagnostics; failures are not counted as duplicate UIDs.</summary>
public sealed record ObjectIdSample(
    ulong ObjectAddress,
    ulong DbAddress,
    uint? RawUid,
    string Status,
    string? Reason,
    string? Name);

/// <summary>Separates duplicate object addresses, unreadable DB/UIDs, zero/sentinel values and duplicate UIDs.</summary>
public sealed record ObjectIdDiagnostics(
    int CandidateCount,
    int UniqueObjectCount,
    int DuplicateObjectAddressCount,
    int ReadableDbCount,
    int ReadableUidCount,
    int ValidUidCount,
    int ZeroUidCount,
    int SentinelUidCount,
    int DuplicateUidCount,
    int UnreadableUidCount,
    IReadOnlyList<ObjectIdSample> Samples);
