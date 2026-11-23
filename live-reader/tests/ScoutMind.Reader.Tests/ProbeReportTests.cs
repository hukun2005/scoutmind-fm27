using System.Text.Json;
using ScoutMind.Contracts;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;

namespace ScoutMind.Reader.Tests;

/// <summary>probe 结构化报告：UID 摘要、哨兵样本与扫描就绪度必须原样来自引擎报告。</summary>
public static class ProbeReportTests
{
    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Case("报告包含 UID 分类摘要与哨兵样本，且不硬编码数字", () =>
        {
            var report = CreateReport(validUids: 57, sentinelUids: 14, total: 71);
            var probe = new ProbeResult(true, 0, 1234, "ok", null);
            var json = ProbeReportWriter.Serialize("0.1.0", probe, report, DateTimeOffset.UtcNow);
            using var document = JsonDocument.Parse(json);
            var root = document.RootElement;

            Assert.Equal("scoutmind.probe.diagnostics.v1", root.GetProperty("schema").GetString(), "报告结构版本");
            Assert.True(root.GetProperty("available").GetBoolean(), "native 后端应有报告");
            Assert.True(root.GetProperty("scan_readiness").GetBoolean(), "scan_readiness 来自 report.ScanAllowed");
            var summary = root.GetProperty("uid_diagnostics");
            Assert.Equal(71, summary.GetProperty("totalObjects").GetInt32(), "对象总数来自真实探测");
            Assert.Equal(57, summary.GetProperty("validUids").GetInt32(), "合法 UID 数");
            Assert.Equal(14, summary.GetProperty("sentinelUids").GetInt32(), "哨兵 UID 数");
            var sentinels = root.GetProperty("report").GetProperty("probes")[0].GetProperty("objectIds")
                .GetProperty("sentinelSamples");
            Assert.Equal(14, sentinels.GetArrayLength(), "哨兵样本必须完整输出");
            Assert.Equal(14, root.GetProperty("sentinel_samples").GetArrayLength(), "顶层哨兵样本与报告一致");
            Assert.Equal(14, root.GetProperty("sample_count").GetInt32(), "样本数与报告一致");
        });

        harness.Case("外部扫描器没有报告时如实标记 available=false", () =>
        {
            var probe = new ProbeResult(true, 0, 10, "external", null);
            var json = ProbeReportWriter.Serialize("0.1.0", probe, null, DateTimeOffset.UtcNow);
            using var document = JsonDocument.Parse(json);
            Assert.False(document.RootElement.GetProperty("available").GetBoolean(), "没有报告时不能伪造");
            Assert.Equal(JsonValueKind.Null, document.RootElement.GetProperty("uid_diagnostics").ValueKind, "摘要为空");
        });

        harness.Case("报告写入文件时创建父目录", () =>
        {
            var root = Path.Combine(Path.GetTempPath(), "scoutmind-probe-" + Guid.NewGuid().ToString("N"));
            var path = Path.Combine(root, "nested", "probe.json");
            try
            {
                var written = ProbeReportWriter.Write(
                    path,
                    "0.1.0",
                    new ProbeResult(true, 0, 5, "ok", null),
                    CreateReport(validUids: 2, sentinelUids: 1, total: 3),
                    DateTimeOffset.UtcNow);
                Assert.True(File.Exists(written), "报告文件应存在");
                Assert.True(written.EndsWith("probe.json", StringComparison.Ordinal), "路径应保留文件名");
            }
            finally
            {
                if (Directory.Exists(root))
                {
                    Directory.Delete(root, recursive: true);
                }
            }
        });
    }

    private static DiagnosticReport CreateReport(int validUids, int sentinelUids, int total)
    {
        var samples = Enumerable.Range(0, sentinelUids)
            .Select(index => new ObjectIdSample(
                ObjectAddress: (ulong)(0x1000 + index),
                DbAddress: 0x2000,
                UidAddress: 0x3000,
                RawUid: 0xFFFFFFFF,
                Status: "sentinel",
                Reason: "sentinel_uid",
                Name: $"Sentinel {index + 1}",
                Ca: 100,
                Pa: 120,
                ContractReadable: true,
                FreeAgentCandidate: true))
            .ToList();
        var ids = new ObjectIdDiagnostics(
            CandidateCount: total,
            UniqueObjectCount: total,
            DuplicateObjectAddressCount: 0,
            ReadableDbCount: total,
            ReadableUidCount: total,
            ValidUidCount: validUids,
            ZeroUidCount: 0,
            SentinelUidCount: sentinelUids,
            DuplicateUidCount: 0,
            UnreadableUidCount: 0,
            FreeAgentCandidateCount: sentinelUids,
            Samples: samples,
            SentinelSamples: samples);
        var integrity = new ProbeOutcome(
            "integrity",
            ProbeStatus.Passed,
            total,
            new[] { new FieldCheck("uid_applicability", CheckStatus.Passed, "ok") },
            "integrity probe")
        {
            ObjectIds = ids,
        };
        return new DiagnosticReport(
            GeneratedAt: ScoutMindJson.FormatTimestamp(DateTimeOffset.UtcNow),
            EngineVersion: "1.0.0",
            GameBuild: "26620374",
            PluginVersion: "27.1.0+2505117",
            AppId: "4530370",
            LayoutName: "FM27_1",
            LayoutStatus: FieldStatus.Verified,
            Probes: new[] { integrity },
            Fields: Array.Empty<FieldVerification>(),
            Overall: OverallStatus.Verified,
            ScanAllowed: true,
            Summary: "ok",
            Diagnostics: Array.Empty<string>(),
            Limitations: Array.Empty<string>());
    }
}
