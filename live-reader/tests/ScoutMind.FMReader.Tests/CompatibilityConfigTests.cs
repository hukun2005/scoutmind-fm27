using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>TASK-010：三份兼容性配置必须一致。</summary>
internal static class CompatibilityConfigTests
{
    private const string GateJson = """
    {
      "layouts": [
        { "layout": "FM27_1", "app_id": "4530370", "build": "26620374", "plugin_version": "27.1.0+2505117", "status": "verified" },
        { "layout": "FM27_0", "app_id": "4530370", "build": "26577676", "plugin_version": "27.0.1+2503222", "status": "candidate" }
      ]
    }
    """;

    private static string RegistryJson(string layout = "FM27_1", string plugin = "27.1.0+2505117", bool withFields = true) => $$"""
    {
      "builds": [
        {
          "build": "26620374",
          "layout": "{{layout}}",
          "status": "verified",
          "plugin_version": "{{plugin}}",
          "verified_fields": [{{(withFields ? "\"PLAO_CA\"" : "")}}]
        },
        {
          "build": "26577676",
          "layout": "FM27_0",
          "status": "candidate",
          "plugin_version": "27.0.1+2503222",
          "verified_fields": []
        }
      ]
    }
    """;

    public static void Run(TestHarness harness)
    {
        harness.Run("兼容配置：仓库里的两份 JSON 与解析器一致", () =>
        {
            var issues = new CompatibilityConfig().Validate();
            TestHarness.True(issues.Count == 0,
                "冲突：" + CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：布局 ID 不一致时报告冲突", () =>
        {
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(GateJson),
                CompatibilityConfig.ParseRegistry(RegistryJson(layout: "FM27_9")));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "layout_id_mismatch"), CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：插件版本不一致时报告冲突", () =>
        {
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(GateJson),
                CompatibilityConfig.ParseRegistry(RegistryJson(plugin: "27.2.0+1")));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "plugin_version_mismatch"), CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：verified 但没有任何已核对字段 → 冲突", () =>
        {
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(GateJson),
                CompatibilityConfig.ParseRegistry(RegistryJson(withFields: false)));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "verified_without_fields"), CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：AppId 不是 FM27 → 冲突", () =>
        {
            var gate = """
            { "layouts": [ { "layout": "FM27_1", "app_id": "999", "build": "26620374", "plugin_version": "27.1.0+2505117", "status": "candidate" } ] }
            """;
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(gate),
                CompatibilityConfig.ParseRegistry(RegistryJson(withFields: false)));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "wrong_app_id"), CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：闸门有、注册表没有的构建 → 冲突", () =>
        {
            var registry = """{ "builds": [] }""";
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(GateJson),
                CompatibilityConfig.ParseRegistry(registry));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "missing_registration"), CompatibilityConfig.Describe(issues));
        });

        harness.Run("兼容配置：重复构建条目 → 冲突", () =>
        {
            var gate = """
            { "layouts": [
              { "layout": "FM27_1", "app_id": "4530370", "build": "26620374", "plugin_version": "27.1.0+2505117", "status": "candidate" },
              { "layout": "FM27_0", "app_id": "4530370", "build": "26620374", "plugin_version": "27.1.0+2505117", "status": "candidate" }
            ] }
            """;
            var config = new CompatibilityConfig(
                CompatibilityConfig.ParseGate(gate),
                CompatibilityConfig.ParseRegistry(RegistryJson(withFields: false)));
            var issues = config.Validate();
            TestHarness.True(issues.Any(issue => issue.Code == "duplicate_gate_build"), CompatibilityConfig.Describe(issues));
        });
    }
}
