using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>Person 候选布局与只读字段观测的单元测试（全部使用模拟内存）。</summary>
internal static class PersonLayoutCandidateTests
{
    public static void Run(TestHarness harness)
    {
        harness.Run("候选布局：27.1 / 26620374 且初始未验证", CandidateDefaults);
        harness.Run("候选字段：有效指针 + Unicode 姓名 + 合法生日", ValidCandidate);
        harness.Run("候选字段：空指针记录 zero_pointer 且不抛异常", ZeroPointer);
        harness.Run("候选字段：指针槽不可读记录 unreadable_pointer_slot", UnreadablePointerSlot);
        harness.Run("候选字段：未对齐指针记录 implausible_pointer", ImplausiblePointer);
        harness.Run("候选字段：指针目标不可读记录 unreadable_pointer_target", UnreadablePointerTarget);
        harness.Run("候选字段：乱码姓名记录 invalid_name_characters", GarbageName);
        harness.Run("候选字段：空姓名记录 empty_string", EmptyName);
        harness.Run("候选字段：非法生日记录 invalid_date", InvalidDate);
        harness.Run("候选字段：四个候选偏移分别记录", SeparateOffsets);
        harness.Run("候选字段：同一对象重复读取稳定", StableRepeatedRead);
        harness.Run("候选字段：Person 为 0 时整体 Rejected", NullPerson);
        harness.Run("候选字段：读取中断后不得 Verified", InterruptedReadIsNotVerified);
    }

    private static void CandidateDefaults()
    {
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        TestHarness.Equal("27.1", candidate.GameVersion, "游戏版本");
        TestHarness.Equal("26620374", candidate.BuildNumber, "构建号");
        TestHarness.Equal(3, candidate.NameOffsetCandidates.Count, "姓名候选数量");
        TestHarness.Equal(0x88u, candidate.DateOfBirthOffsetCandidate, "生日候选偏移");
        TestHarness.True(candidate.VerificationStatus != CandidateVerificationStatus.Verified, "候选阶段不得是 Verified");
        TestHarness.True(candidate.Confidence == 0, "候选阶段置信度保持 0");
    }

    private static void ValidCandidate()
    {
        var (memory, candidate, person) = BuildValid("José Mário", 2000, 100);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);

        TestHarness.Equal(4, snapshot.Fields.Count, "三个姓名候选 + 一个生日候选");
        TestHarness.True(
            snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).All(field => field.StringValid),
            "Unicode 姓名应全部有效");
        TestHarness.True(
            snapshot.Fields.Single(field => field.Kind == CandidateFieldKind.DateOfBirth).DateValid,
            "生日应有效");
        TestHarness.Equal(CandidateVerificationStatus.StructurallyValid, snapshot.Status, "结构校验通过");
        TestHarness.True(snapshot.Status != CandidateVerificationStatus.Verified, "结构校验不等于人工 Verified");
        TestHarness.Equal(person, snapshot.PersonPointer, "Person 指针应原样记录");
    }

    private static void ZeroPointer()
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        const ulong person = 0x1100_0000;
        foreach (var offset in candidate.NameOffsetCandidates)
        {
            memory.WritePointer(person + offset, 0);
        }

        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, (2001u << 16) | 50u);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);

        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "zero_pointer"), "应记录 zero_pointer");
        TestHarness.True(names.All(field => !field.PointerValid), "空指针不算有效指针");
        TestHarness.Equal(CandidateVerificationStatus.Unverified, snapshot.Status, "生日有效但姓名缺失仍是 Unverified");
    }

    private static void UnreadablePointerSlot()
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        const ulong person = 0x1100_0000;
        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, (2001u << 16) | 50u);

        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "unreadable_pointer_slot"), "应记录 unreadable_pointer_slot");
    }

    private static void ImplausiblePointer()
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        const ulong person = 0x1100_0000;
        foreach (var offset in candidate.NameOffsetCandidates)
        {
            memory.WritePointer(person + offset, 0x1200_0001); // 未 8 字节对齐
        }

        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, (2001u << 16) | 50u);

        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "implausible_pointer"), "应记录 implausible_pointer");
    }

    private static void UnreadablePointerTarget()
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        const ulong person = 0x1100_0000;
        foreach (var offset in candidate.NameOffsetCandidates)
        {
            memory.WritePointer(person + offset, 0x1300_0000 + offset); // 目标无字节
        }

        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, (2001u << 16) | 50u);

        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "unreadable_pointer_target"), "应记录 unreadable_pointer_target");
    }

    private static void GarbageName()
    {
        var (memory, candidate, person) = BuildValid("12345", 2000, 100);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "invalid_name_characters"), "纯数字姓名应判为乱码");
        TestHarness.True(names.All(field => !field.StringValid), "乱码不算有效字符串");
    }

    private static void EmptyName()
    {
        var (memory, candidate, person) = BuildValid(string.Empty, 2000, 100);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var names = snapshot.Fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
        TestHarness.True(names.All(field => field.FailureReason == "empty_string"), "空姓名应记录 empty_string");
    }

    private static void InvalidDate()
    {
        var (memory, candidate, person) = BuildValid("Test Player", 0, 0);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var date = snapshot.Fields.Single(field => field.Kind == CandidateFieldKind.DateOfBirth);
        TestHarness.True(!date.DateValid, "非法生日不应有效");
        TestHarness.Equal("invalid_date", date.FailureReason, "失败原因");
        TestHarness.Equal("0x00000000", date.RawValue, "仍保留原始值");
    }

    private static void SeparateOffsets()
    {
        var (memory, candidate, person) = BuildValid("Test Player", 2000, 100);
        var snapshot = new PersonCandidateProbe(memory).Observe(person, candidate);
        var offsets = snapshot.Fields.Select(field => field.Offset).ToArray();
        TestHarness.True(offsets.Contains(0x50u), "应包含 0x50");
        TestHarness.True(offsets.Contains(0x58u), "应包含 0x58");
        TestHarness.True(offsets.Contains(0x60u), "应包含 0x60");
        TestHarness.True(offsets.Contains(0x88u), "应包含 0x88");
    }

    private static void StableRepeatedRead()
    {
        var (memory, candidate, person) = BuildValid("Test Player", 2000, 100);
        var probe = new PersonCandidateProbe(memory);
        var first = probe.Observe(person, candidate);
        var second = probe.Observe(person, candidate);

        TestHarness.Equal(first.Status, second.Status, "状态应稳定");
        TestHarness.Equal(first.Fields.Count, second.Fields.Count, "字段数量应稳定");
        for (var index = 0; index < first.Fields.Count; index++)
        {
            TestHarness.Equal(first.Fields[index].Offset, second.Fields[index].Offset, "偏移应稳定");
            TestHarness.Equal(first.Fields[index].IsValid, second.Fields[index].IsValid, "有效性应稳定");
        }
    }

    private static void InterruptedReadIsNotVerified()
    {
        var (memory, candidate, person) = BuildValid("Interrupted Player", 1999, 60);
        var interrupted = new InterruptingMemory(memory, readsBeforeFailure: 2);

        PersonCandidateSnapshot? snapshot = null;
        var threw = false;
        try
        {
            snapshot = new PersonCandidateProbe(interrupted).Observe(person, candidate);
        }
        catch (MemoryUnreadableException)
        {
            threw = true;
        }

        TestHarness.True(threw || snapshot is not null, "读取中断必须返回失败或异常，而不是成功快照");
        if (snapshot is not null)
        {
            TestHarness.True(
                snapshot.Status != CandidateVerificationStatus.Verified,
                "读取中断不得产生 Verified");
        }
    }

    /// <summary>在读取若干次后模拟失败的内存源。</summary>
    private sealed class InterruptingMemory : IMemorySource
    {
        private readonly FakeMemory _inner;
        private int _remaining;

        public InterruptingMemory(FakeMemory inner, int readsBeforeFailure)
        {
            _inner = inner;
            _remaining = readsBeforeFailure;
        }

        public IReadOnlyList<MemoryRegion> Regions => _inner.Regions;

        public bool InModule(ulong address) => _inner.InModule(address);

        public bool IsReadable(ulong address, int length) => Allow() && _inner.IsReadable(address, length);

        public byte Byte(ulong address) => Allow() ? _inner.Byte(address) : throw new MemoryUnreadableException(address);

        public ushort UInt16(ulong address) => Allow() ? _inner.UInt16(address) : throw new MemoryUnreadableException(address);

        public uint UInt32(ulong address) => Allow() ? _inner.UInt32(address) : throw new MemoryUnreadableException(address);

        public ulong Pointer(ulong address) => Allow() ? _inner.Pointer(address) : throw new MemoryUnreadableException(address);

        public string? NestedString(ulong address) => Allow() ? _inner.NestedString(address) : null;

        public string? IndirectString(ulong address) => Allow() ? _inner.IndirectString(address) : null;

        private bool Allow() => _remaining-- > 0;
    }

    private static void NullPerson()
    {
        var (memory, candidate, _) = BuildValid("Test Player", 2000, 100);
        var snapshot = new PersonCandidateProbe(memory).Observe(0, candidate);
        TestHarness.Equal(CandidateVerificationStatus.Rejected, snapshot.Status, "空 Person 应 Rejected");
        TestHarness.True(snapshot.Fields.All(field => field.FailureReason == "null_person"), "所有字段记录 null_person");
    }

    private static (FakeMemory Memory, PersonLayoutCandidate Candidate, ulong Person) BuildValid(
        string name,
        int year,
        int dayOfYear)
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        const ulong person = 0x1100_0000;

        foreach (var offset in candidate.NameOffsetCandidates)
        {
            var target = 0x1200_0000 + offset;
            memory.WritePointer(person + offset, target);
            memory.Write(target, new byte[] { 0x41 });
            memory.WriteNestedString(person + offset, name);
        }

        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, ((uint)year << 16) | (uint)dayOfYear);
        return (memory, candidate, person);
    }
}
