using ScoutMind.FMReader.Calibration;

namespace ScoutMind.FMReader.Tests;

/// <summary>Person 候选定位器的单元测试（全部使用模拟内存）。</summary>
internal static class PersonCandidateLocatorTests
{
    private const ulong Person = 0x1100_0000;
    private const ulong Vtable = 0x1500_0000;

    public static void Run(TestHarness harness)
    {
        harness.Run("定位器：合法对象返回 Candidate 且姓名/生日正确", ValidCandidate);
        harness.Run("定位器：空指针返回 InvalidPointer", NullPointer);
        harness.Run("定位器：对象头不可读返回 UnreadableMemory", UnreadableHeader);
        harness.Run("定位器：vtable 不在模块内返回 InvalidObject", InvalidObject);
        harness.Run("定位器：姓名槽为空返回 NameNotFound", NameNotFound);
        harness.Run("定位器：乱码姓名返回 InvalidName", InvalidName);
        harness.Run("定位器：生日不可读返回 DateOfBirthNotFound", DateOfBirthNotFound);
        harness.Run("定位器：生日非法返回 InvalidDateOfBirth", InvalidDateOfBirth);
        harness.Run("定位器：Unicode 多词姓名可正确拼接", UnicodeMultiWord);
        harness.Run("定位器：永不返回 Verified", NeverVerified);
        harness.Run("定位器：同一对象重复定位稳定", StableRepeatedLocate);
    }

    private static void ValidCandidate()
    {
        var memory = Build();
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);

        TestHarness.Equal(PersonCandidateStatus.Candidate, result.Status, "合法对象应为 Candidate");
        TestHarness.Equal("José Mário", result.DisplayName, "common 为空时拼接 first + second");
        TestHarness.Equal("José", result.FirstName, "名");
        TestHarness.Equal("Mário", result.SecondName, "姓");
        TestHarness.Equal(2000u << 16 | 100u, result.DateOfBirthRaw, "生日原始值");
        TestHarness.Equal(2000, result.DateOfBirthYear, "生日年份");
        TestHarness.Equal(100, result.DateOfBirthDayOfYear, "年内序日");
        TestHarness.True(result.IsCandidate, "IsCandidate 应为 true");
    }

    private static void NullPointer()
    {
        var result = new PersonCandidateLocator(new FakeMemory()).Locate(0, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.InvalidPointer, result.Status, "空指针状态");
        TestHarness.Equal("null_person", result.FailureReason, "失败原因");
    }

    private static void UnreadableHeader()
    {
        var memory = new FakeMemory();
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.UnreadableMemory, result.Status, "对象头不可读");
        TestHarness.Equal("unreadable_object_header", result.FailureReason, "失败原因");
    }

    private static void InvalidObject()
    {
        var memory = new FakeMemory();
        memory.WritePointer(Person, 0x1); // 不在模块内
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.InvalidObject, result.Status, "vtable 非法");
        TestHarness.Equal("vtable_not_in_module", result.FailureReason, "失败原因");
    }

    private static void NameNotFound()
    {
        var memory = Build(firstName: string.Empty, secondName: string.Empty, common: string.Empty);
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.NameNotFound, result.Status, "姓名缺失");
        TestHarness.Equal("name_not_found", result.FailureReason, "失败原因");
    }

    private static void InvalidName()
    {
        var memory = Build(firstName: "12345", secondName: "67890", common: "12345");
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.InvalidName, result.Status, "乱码姓名");
        TestHarness.Equal("invalid_name_characters", result.FailureReason, "失败原因");
    }

    private static void DateOfBirthNotFound()
    {
        var memory = Build(includeDate: false);
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.DateOfBirthNotFound, result.Status, "生日不可读");
        TestHarness.Equal("date_not_found", result.FailureReason, "失败原因");
    }

    private static void InvalidDateOfBirth()
    {
        var memory = Build(dateOfBirthRaw: 0);
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.InvalidDateOfBirth, result.Status, "生日非法");
        TestHarness.Equal("invalid_date", result.FailureReason, "失败原因");
        TestHarness.Equal(0u, result.DateOfBirthRaw, "仍保留原始值");
    }

    private static void UnicodeMultiWord()
    {
        var memory = Build(firstName: "Jean-Pierre", secondName: "O'Connor", common: string.Empty);
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(PersonCandidateStatus.Candidate, result.Status, "Unicode/多词姓名应通过");
        TestHarness.Equal("Jean-Pierre O'Connor", result.DisplayName, "拼接结果");
    }

    private static void NeverVerified()
    {
        var memory = Build();
        var result = new PersonCandidateLocator(memory).Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.True(result.Status != PersonCandidateStatus.Verified, "定位器不得返回 Verified");
    }

    private static void StableRepeatedLocate()
    {
        var memory = Build();
        var locator = new PersonCandidateLocator(memory);
        var first = locator.Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        var second = locator.Locate(Person, PersonLayoutCandidate.Fm27_1_20261125);
        TestHarness.Equal(first.Status, second.Status, "状态稳定");
        TestHarness.Equal(first.DisplayName, second.DisplayName, "姓名稳定");
        TestHarness.Equal(first.DateOfBirthRaw, second.DateOfBirthRaw, "生日稳定");
    }

    private static FakeMemory Build(
        string firstName = "José",
        string secondName = "Mário",
        string common = "",
        bool includeDate = true,
        uint dateOfBirthRaw = (2000u << 16) | 100u)
    {
        var memory = new FakeMemory();
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        memory.WritePointer(Person, Vtable);

        var names = new[] { firstName, secondName, common };
        for (var index = 0; index < candidate.NameOffsetCandidates.Count; index++)
        {
            var offset = candidate.NameOffsetCandidates[index];
            var target = 0x1200_0000 + offset;
            memory.WritePointer(Person + offset, target);
            memory.Write(target, new byte[] { 0x41 });
            memory.WriteNestedString(Person + offset, names[index]);
        }

        if (includeDate)
        {
            memory.WriteUInt32(Person + candidate.DateOfBirthOffsetCandidate, dateOfBirthRaw);
        }

        return memory;
    }
}
