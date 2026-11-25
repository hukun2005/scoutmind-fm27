using System.Globalization;
using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.FMReader.Tests;

/// <summary>真实内存校准引擎的单元测试（跨区域抽样、稳定性、脱敏输出）。</summary>
internal static class PersonCalibrationEngineTests
{
    private static readonly CalibrationEnvironment Environment =
        new(72012, "fm", "27.1", "26620374", "27.1", "Verified", true, false);

    public static void Run(TestHarness harness)
    {
        harness.Run("校准抽样：跨区域等距且不重复", SelectEvenlyCoversWholeRange);
        harness.Run("校准抽样：样本数不少于总数时全部返回", SelectEvenlyKeepsAll);
        harness.Run("校准引擎：姓名与生日稳定时结构校验通过且不 Verified", StableRunIsStructurallyValid);
        harness.Run("校准引擎：同一对象读取变化时标记 Unstable", UnstableReadIsDetected);
        harness.Run("校准引擎：dry-run 不读取任何样本", DryRunHasNoSamples);
        harness.Run("校准 JSON：默认脱敏且包含 Schema 字段", JsonIsSanitizedByDefault);
        harness.Run("校准 JSON：本机模式保留 Person 指针", JsonCanIncludePointers);
        harness.Run("校准 Markdown：包含候选与状态且不含地址", MarkdownIsSanitized);
    }

    private static void SelectEvenlyCoversWholeRange()
    {
        var items = Enumerable.Range(0, 100).ToList();
        var sampled = PersonCalibrationEngine.SelectEvenly(items, 4);

        TestHarness.Equal(4, sampled.Count, "抽样数量");
        TestHarness.Equal(4, sampled.Distinct().Count(), "样本不重复");
        TestHarness.True(sampled[0] < 25, "第一个样本应来自前四分之一");
        TestHarness.True(sampled[3] > 74, "最后一个样本应来自后四分之一");
    }

    private static void SelectEvenlyKeepsAll()
    {
        var items = new List<int> { 1, 2, 3 };
        var sampled = PersonCalibrationEngine.SelectEvenly(items, 10);
        TestHarness.Equal(3, sampled.Count, "样本数不少于总数时全部返回");
    }

    private static void StableRunIsStructurallyValid()
    {
        var memory = new FakeMemory();
        var persons = new List<ulong>();
        var names = new[] { "Alpha", "Bravo", "Charlie", "Delta" };
        for (var index = 0; index < 4; index++)
        {
            var person = 0x1100_0000UL + (ulong)(index * 0x1000);
            WritePerson(memory, person, names[index], "Player", null, 1990 + index, 40);
            persons.Add(person);
        }

        var report = new PersonCalibrationEngine(memory).Run(
            PersonLayoutCandidate.Fm27_1_20261125,
            persons,
            Environment,
            new PersonCalibrationOptions(3, 4, 8, 0, false, false),
            DateTimeOffset.Parse("2026-11-25T10:00:00+08:00", CultureInfo.InvariantCulture));

        TestHarness.Equal(4, report.Sampled, "抽样数量");
        TestHarness.Equal(0, report.UnstableCount, "不应有不稳定样本");
        TestHarness.Equal(4, report.StructurallyValidCount, "全部结构校验通过");
        TestHarness.Equal(CandidateVerificationStatus.StructurallyValid, report.VerificationStatus, "状态");
        TestHarness.True(report.VerificationStatus != CandidateVerificationStatus.Verified, "不得自动 Verified");
        TestHarness.True(report.Confidence is > 0 and <= 0.5, "置信度受结构上限约束");
        TestHarness.Equal("26620374", report.BuildNumber, "构建号来自本次环境");
    }

    private static void UnstableReadIsDetected()
    {
        var memory = new FakeMemory();
        const ulong person = 0x1100_0000;
        WritePerson(memory, person, "Dominic", "Calvert-Lewin", null, 1997, 75);

        var mutating = new MutatingMemory(memory, person + 0x50);
        var report = new PersonCalibrationEngine(mutating).Run(
            PersonLayoutCandidate.Fm27_1_20261125,
            new[] { person },
            Environment,
            new PersonCalibrationOptions(2, 1, 1, 0, false, false));

        TestHarness.Equal(1, report.UnstableCount, "应检测到不稳定");
        TestHarness.Equal(CandidateVerificationStatus.Unstable, report.VerificationStatus, "状态应为 Unstable");
        TestHarness.Equal(0d, report.Confidence, "不稳定时置信度为 0");
        var notes = string.Join(" ", report.Samples[0].StabilityNotes);
        TestHarness.Contains(notes, "decoded_changed", "应记录姓名变化");
    }

    private static void DryRunHasNoSamples()
    {
        var memory = new FakeMemory();
        var report = new PersonCalibrationEngine(memory).Run(
            PersonLayoutCandidate.Fm27_1_20261125,
            Array.Empty<ulong>(),
            Environment,
            new PersonCalibrationOptions(3, 4, 8, 0, false, true));

        TestHarness.True(report.DryRun, "应标记 dry-run");
        TestHarness.Equal(0, report.Sampled, "dry-run 不抽样");
        TestHarness.Equal(0, report.Samples.Count, "dry-run 无样本");
        TestHarness.Equal(CandidateVerificationStatus.Unverified, report.VerificationStatus, "状态");
    }

    private static void JsonIsSanitizedByDefault()
    {
        var report = BuildStableReport(out var person);
        var json = PersonCalibrationReportWriter.ToJson(report);

        TestHarness.Contains(json, "\"schema_version\": \"1.0\"", "包含 Schema 版本");
        TestHarness.Contains(json, "\"raw_read_evidence\"", "包含原始读取证据");
        TestHarness.Contains(json, "\"verification_status\"", "包含验证状态");
        TestHarness.Contains(json, "\"mark_verified\": false", "明确未 Mark(Verified)");
        TestHarness.Contains(json, "<redacted>", "姓名原始指针应被脱敏");
        TestHarness.True(!json.Contains($"0x{person:X}", StringComparison.Ordinal), "默认输出不得包含 Person 指针");
        TestHarness.True(!json.Contains("0x1200", StringComparison.Ordinal), "默认输出不得包含姓名指针");
        TestHarness.True(!json.Contains("D:\\", StringComparison.Ordinal), "不得包含本机安装路径");
    }

    private static void JsonCanIncludePointers()
    {
        var report = BuildStableReport(out var person);
        var json = PersonCalibrationReportWriter.ToJson(report, includePointers: true);
        TestHarness.Contains(json, $"0x{person:X}", "本机模式保留 Person 指针");
    }

    private static void MarkdownIsSanitized()
    {
        var report = BuildStableReport(out var person);
        var markdown = PersonCalibrationReportWriter.ToMarkdown(report);

        TestHarness.Contains(markdown, "FM27 Person 校准报告", "标题");
        TestHarness.Contains(markdown, PersonLayoutCandidate.Fm27_1_20261125.CandidateId, "候选标识");
        TestHarness.Contains(markdown, "0x50", "姓名偏移");
        TestHarness.Contains(markdown, "StructurallyValid", "验证状态");
        TestHarness.True(!markdown.Contains($"0x{person:X}", StringComparison.Ordinal), "Markdown 不得包含 Person 指针");
    }

    private static PersonCalibrationReport BuildStableReport(out ulong person)
    {
        var memory = new FakeMemory();
        person = 0x1100_0000;
        WritePerson(memory, person, "Dominic", "Calvert-Lewin", null, 1997, 75);
        return new PersonCalibrationEngine(memory).Run(
            PersonLayoutCandidate.Fm27_1_20261125,
            new[] { person },
            Environment,
            new PersonCalibrationOptions(3, 1, 1, 0, false, false));
    }

    private static void WritePerson(
        FakeMemory memory,
        ulong person,
        string first,
        string second,
        string? common,
        int year,
        int dayOfYear)
    {
        var candidate = PersonLayoutCandidate.Fm27_1_20261125;
        var values = new[] { first, second, common };
        for (var index = 0; index < candidate.NameOffsetCandidates.Count; index++)
        {
            var offset = candidate.NameOffsetCandidates[index];
            var value = values[index];
            var target = 0x1200_0000UL + person + offset;
            memory.WritePointer(person + offset, target);
            memory.Write(target, new byte[] { 0x41 });
            if (value is not null)
            {
                memory.WriteNestedString(person + offset, value);
            }
        }

        memory.WriteUInt32(person + candidate.DateOfBirthOffsetCandidate, ((uint)year << 16) | (uint)dayOfYear);
    }

    /// <summary>在第二次读取时改变指定字段的嵌套字符串，用来验证稳定性检测。</summary>
    private sealed class MutatingMemory : IMemorySource
    {
        private readonly FakeMemory _inner;
        private readonly ulong _watch;
        private int _calls;

        public MutatingMemory(FakeMemory inner, ulong watch)
        {
            _inner = inner;
            _watch = watch;
        }

        public IReadOnlyList<MemoryRegion> Regions => _inner.Regions;

        public bool InModule(ulong address) => _inner.InModule(address);

        public bool IsReadable(ulong address, int length) => _inner.IsReadable(address, length);

        public byte Byte(ulong address) => _inner.Byte(address);

        public ushort UInt16(ulong address) => _inner.UInt16(address);

        public uint UInt32(ulong address) => _inner.UInt32(address);

        public ulong Pointer(ulong address) => _inner.Pointer(address);

        public string? NestedString(ulong address)
        {
            if (address == _watch && ++_calls > 1)
            {
                return "Changed Name";
            }

            return _inner.NestedString(address);
        }

        public string? IndirectString(ulong address) => _inner.IndirectString(address);
    }
}
