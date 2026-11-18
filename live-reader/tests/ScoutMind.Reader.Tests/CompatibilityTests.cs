using ScoutMind.Contracts;

namespace ScoutMind.Reader.Tests;

/// <summary>兼容性闸门用例：只有 verified 命中才允许读取。</summary>
public static class CompatibilityTests
{
    /// <summary>注册并执行兼容性用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Case("verified 条目命中 → Verified（映射为 Compatible）", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Verified)));
            var result = service.Evaluate(new CompatibilityInput("4530370", "26577676", "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Verified, result.Status, "已验证条目应返回 Verified");
            Assert.True(result.MatchedRule is not null, "命中时应记录匹配规则");
            Assert.Equal(ReaderState.Compatible, ReaderPipeline.MapCompatibilityStatus(result.Status), "Verified 才映射为 Compatible");
        });

        harness.Case("candidate 条目命中 → Candidate（映射为 Unknown，不自动兼容）", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Candidate)));
            var result = service.Evaluate(new CompatibilityInput("4530370", "26577676", "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Candidate, result.Status, "候选条目不得返回 Verified");
            Assert.Equal("候选兼容项，需本机 probe 验证", result.Reason, "候选条目的原因文本必须固定");
            Assert.Equal(ReaderState.Unknown, ReaderPipeline.MapCompatibilityStatus(result.Status), "Candidate 只能映射为 Unknown");
        });

        harness.Case("未收录的构建 → Rejected 且记录实际构建号", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Verified)));
            var result = service.Evaluate(new CompatibilityInput("4530370", "26620374", "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Rejected, result.Status, "未知构建必须判为不受支持");
            Assert.Equal("26620374", result.ObservedBuildId, "必须记录实际观测到的构建号");
            Assert.Contains(result.Reason, "26620374", "原因应包含实际构建号");
            Assert.Contains(result.Reason, "26577676", "原因应包含清单已知构建号");
            Assert.Equal(ReaderState.Unsupported, ReaderPipeline.MapCompatibilityStatus(result.Status), "Rejected 映射为 Unsupported");
        });

        harness.Case("插件版本不符 → Rejected 且记录两侧版本", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Verified, "27.0.1+2503222")));
            var result = service.Evaluate(new CompatibilityInput("4530370", "26577676", "27.1.0+2505117"));

            Assert.Equal(CompatibilityStatus.Rejected, result.Status, "插件版本不符必须拒绝");
            Assert.Equal("27.1.0+2505117", result.ObservedPluginProductVersion, "必须记录实际插件版本");
            Assert.Contains(result.Reason, "27.1.0+2505117", "原因应包含实际插件版本");
            Assert.Contains(result.Reason, "27.0.1+2503222", "原因应包含清单插件版本");
        });

        harness.Case("缺少 buildid → Candidate（映射为 Unknown）", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Verified)));
            var result = service.Evaluate(new CompatibilityInput("4530370", null, "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Candidate, result.Status, "缺少构建号时不得判定为兼容");
            Assert.Equal(ReaderState.Unknown, ReaderPipeline.MapCompatibilityStatus(result.Status), "缺少构建号应停在 Unknown");
        });

        harness.Case("未知 appId → Rejected", () =>
        {
            var service = new CompatibilityService(Manifest(Entry("26577676", CompatibilityStatus.Verified)));
            var result = service.Evaluate(new CompatibilityInput("999999", "26577676", "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Rejected, result.Status, "未知 appId 必须拒绝");
        });

        harness.Case("rejected 条目命中 → Rejected 并带说明", () =>
        {
            var service = new CompatibilityService(
                Manifest(Entry("26577676", CompatibilityStatus.Rejected, notes: "该构建会被反作弊拦截")));
            var result = service.Evaluate(new CompatibilityInput("4530370", "26577676", "27.0.1+2503222"));

            Assert.Equal(CompatibilityStatus.Rejected, result.Status, "rejected 条目必须拒绝");
            Assert.Contains(result.Reason, "该构建会被反作弊拦截", "原因应带条目说明");
        });

        harness.Case("清单加载：合法文件可读，非法 JSON 抛异常", () =>
        {
            using var workspace = new TempWorkspace();
            var validPath = workspace.Combine("compatibility.json");
            File.WriteAllText(validPath, """
                {
                  "schemaVersion": 1,
                  "entries": [
                    {
                      "appId": "4530370",
                      "buildId": "26577676",
                      "pluginProductVersion": "27.0.1+2503222",
                      "status": "candidate",
                      "notes": "候选",
                      "verifiedAt": null
                    }
                  ]
                }
                """);

            var manifest = CompatibilityService.LoadManifest(validPath);
            Assert.Equal(1, manifest.Entries.Count, "应加载 1 个条目");
            Assert.Equal(CompatibilityStatus.Candidate, manifest.Entries[0].Status, "status 应解析为小写枚举");

            var brokenPath = workspace.Combine("broken.json");
            File.WriteAllText(brokenPath, "{ not json ");
            Assert.Throws<CompatibilityManifestException>(
                () => CompatibilityService.LoadManifest(brokenPath),
                "非法 JSON 必须抛出清单异常");

            Assert.Throws<CompatibilityManifestException>(
                () => CompatibilityService.LoadManifest(workspace.Combine("missing.json")),
                "缺失清单必须抛出清单异常");
        });

        harness.Case("清单 schemaVersion 不受支持时抛异常", () =>
        {
            using var workspace = new TempWorkspace();
            var path = workspace.Combine("compatibility-v2.json");
            File.WriteAllText(path, "{\"schemaVersion\": 2, \"entries\": []}");

            var ex = Assert.Throws<CompatibilityManifestException>(
                () => CompatibilityService.LoadManifest(path),
                "未知 schemaVersion 必须拒绝");
            Assert.Contains(ex.Message, "schemaVersion", "异常应说明 schemaVersion 问题");
        });
    }

    private static CompatibilityManifest Manifest(params CompatibilityEntry[] entries) => new(1, entries.ToList());

    private static CompatibilityEntry Entry(
        string buildId,
        CompatibilityStatus status,
        string pluginProductVersion = "27.0.1+2503222",
        string? notes = null) =>
        new("4530370", buildId, pluginProductVersion, status, notes, null);
}
