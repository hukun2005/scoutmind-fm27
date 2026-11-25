using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>只读诊断摘要收集器的单元测试。</summary>
internal static class PersonDiagnosticsTests
{
    private static readonly CalibrationEnvironment Environment =
        new(72012, "fm", "27.1", "26620374", "27.1", "Verified", true, false);

    public static void Run(TestHarness harness)
    {
        harness.Run("诊断摘要：完整样本的成功率为 1", CompleteSummary);
        harness.Run("诊断摘要：姓名缺失不默认为成功", MissingName);
        harness.Run("诊断摘要：同名同生日不同 UID 计入冲突", DuplicateConflict);
        harness.Run("诊断摘要：空输入不崩溃且成功率为 0", EmptySummary);
    }

    private static void CompleteSummary()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var names = new[] { "Alpha", "Bravo", "Charlie" };
        var records = Enumerable.Range(0, 3)
            .Select(index => FakeSave.WritePlayer(
                memory,
                layout,
                index,
                name: names[index],
                birthYear: 1990 + index,
                birthDoy: 40))
            .ToList();
        for (var index = 0; index < records.Count; index++)
        {
            AttachNamePointer(memory, layout, records[index], index);
        }

        var summary = new PersonDiagnosticsCollector(memory, layout).Collect(
            records,
            PersonLayoutCandidate.Fm27_1_20261125,
            Environment,
            5);

        TestHarness.Equal(3, summary.LocatedCount, "定位数量");
        TestHarness.Equal(3, summary.SampledCount, "抽样数量");
        TestHarness.Equal(3, summary.ValidObjectCount, "有效对象");
        TestHarness.Equal(0, summary.InvalidPointerCount, "无效指针");
        TestHarness.Equal(3, summary.NameReadCount, "姓名成功");
        TestHarness.Equal(3, summary.DateOfBirthReadCount, "生日成功");
        TestHarness.Equal(3, summary.AttributeLinkUniqueCount, "唯一关联");
        TestHarness.Equal(0, summary.ConflictCount, "冲突");
        TestHarness.Equal(1d, summary.NameReadSuccessRate, "姓名成功率");
        TestHarness.Equal(1d, summary.DateOfBirthReadSuccessRate, "生日成功率");
        TestHarness.Equal(1d, summary.AttributeLinkSuccessRate, "关联成功率");
        TestHarness.Equal(0, summary.VerifiedCount, "Verified 计数固定为 0");
    }

    private static void MissingName()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var record = FakeSave.WritePlayer(memory, layout, 0);
        memory.WritePointer(record.Person + layout["PERO_COMMON_NAME"], 0);

        var summary = new PersonDiagnosticsCollector(memory, layout).Collect(
            new[] { record },
            PersonLayoutCandidate.Fm27_1_20261125,
            Environment,
            1);

        TestHarness.Equal(0, summary.NameReadCount, "姓名缺失不应算成功");
        TestHarness.Equal(0d, summary.NameReadSuccessRate, "姓名成功率");
        TestHarness.Equal(1, summary.DateOfBirthReadCount, "生日仍可读");
        TestHarness.Equal(1, summary.AttributeLinkUniqueCount, "UID 仍可建立唯一关联");
    }

    private static void DuplicateConflict()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var first = FakeSave.WritePlayer(memory, layout, 0);
        var second = FakeSave.WritePlayer(memory, layout, 1);
        AttachNamePointer(memory, layout, first, 0);
        AttachNamePointer(memory, layout, second, 1);
        memory.WriteUInt32(first.Db + layout["OBJ_DUNI"], 9000);
        memory.WriteUInt32(second.Db + layout["OBJ_DUNI"], 9001);
        var records = new List<LocatedObject> { first, second };

        var summary = new PersonDiagnosticsCollector(memory, layout).Collect(
            records,
            PersonLayoutCandidate.Fm27_1_20261125,
            Environment,
            2);

        TestHarness.Equal(2, summary.ConflictCount, "两个目标都因同名不同 UID 产生冲突");
        TestHarness.True(summary.LinkStatusCounts.ContainsKey(nameof(AttributeLinkStatus.ConflictingIdentity)), "应记录冲突状态");
    }

    private static void EmptySummary()
    {
        var memory = new FakeMemory();
        var layout = new FM27_1_Layout();
        var summary = new PersonDiagnosticsCollector(memory, layout).Collect(
            Array.Empty<LocatedObject>(),
            PersonLayoutCandidate.Fm27_1_20261125,
            Environment,
            10);

        TestHarness.Equal(0, summary.LocatedCount, "定位数量");
        TestHarness.Equal(0, summary.SampledCount, "抽样数量");
        TestHarness.Equal(0d, summary.NameReadSuccessRate, "姓名成功率");
        TestHarness.Equal(0d, summary.AttributeLinkSuccessRate, "关联成功率");
    }

    private static void AttachNamePointer(FakeMemory memory, ILayout layout, LocatedObject record, int index)
    {
        var target = 0x1200_0000UL + (ulong)(index * 8);
        memory.WritePointer(record.Person + layout["PERO_COMMON_NAME"], target);
        memory.Write(target, new byte[] { 0x41 });
    }
}
