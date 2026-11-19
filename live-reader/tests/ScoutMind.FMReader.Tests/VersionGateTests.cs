using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>版本闸门：只有 verified 放行，candidate/unknown/unsupported 一律拒绝。</summary>
internal static class VersionGateTests
{
    private static readonly BuildEntry Verified = new(
        "FM27", "4530370", "99999999", "27.9.0+1", BuildStatus.Verified, "测试用已验证条目", Array.Empty<string>());

    private static readonly BuildEntry Candidate = new(
        "FM27", "4530370", "26620374", "27.1.0+2505117", BuildStatus.Candidate, "上游按 27.0 钉的偏移，未核对 27.1",
        Array.Empty<string>());

    private static readonly BuildEntry Unsupported = new(
        "FM26", "1", "11111111", "26.0.0", BuildStatus.Unsupported, "已知不兼容", Array.Empty<string>());

    public static void Run(TestHarness harness)
    {
        harness.Run("闸门：verified 且插件一致时放行", () =>
        {
            var gate = new VersionGate(new[] { Verified });
            var result = gate.Evaluate("4530370", "99999999", "27.9.0+1");
            TestHarness.True(result.AllowScan, "verified 条目应放行");
            TestHarness.Equal(BuildStatus.Verified, result.Status, "状态应为 Verified");
            TestHarness.Equal<string?>("FM27", result.Layout, "应给出布局名");
        });

        harness.Run("闸门：本机 27.1 candidate 必须拒绝（不因上游声称支持而放行）", () =>
        {
            var gate = new VersionGate(new[] { Candidate });
            var result = gate.Evaluate("4530370", "26620374", "27.1.0+2505117");
            TestHarness.True(!result.AllowScan, "candidate 必须拒绝");
            TestHarness.Equal(BuildStatus.Candidate, result.Status, "状态应为 Candidate");
            TestHarness.Contains(result.Message, "未验证", "拒绝原因要说明未验证");
        });

        harness.Run("闸门：未知构建拒绝", () =>
        {
            var gate = new VersionGate(new[] { Verified });
            var result = gate.Evaluate("4530370", "12345678", "27.2.0+1");
            TestHarness.True(!result.AllowScan, "未知构建必须拒绝");
            TestHarness.Contains(result.Message, "不在 ScoutMind 的已验证清单", "拒绝原因要说清楚");
        });

        harness.Run("闸门：没有构建号时拒绝而不是猜", () =>
        {
            var gate = new VersionGate(new[] { Verified });
            var result = gate.Evaluate("4530370", null, "27.9.0+1");
            TestHarness.True(!result.AllowScan, "没有构建号必须拒绝");
            TestHarness.Contains(result.Message, "构建号", "应提示缺构建号");
        });

        harness.Run("闸门：已验证构建但插件主次版本不一致时拒绝", () =>
        {
            var gate = new VersionGate(new[] { Verified });
            var result = gate.Evaluate("4530370", "99999999", "27.10.0+2");
            TestHarness.True(!result.AllowScan, "插件主次版本不一致必须拒绝");
            TestHarness.Contains(result.Message, "插件版本", "应提示插件版本不一致");
        });

        harness.Run("闸门：同一主次版本、仅修订号或构建后缀不同时放行", () =>
        {
            var gate = new VersionGate(new[] { Verified });
            TestHarness.True(gate.Evaluate("4530370", "99999999", "27.9.3+2").AllowScan,
                "27.9.3 与清单 27.9.0 属同一主次版本，应放行");
            TestHarness.True(gate.Evaluate("4530370", "99999999", "27.9").AllowScan,
                "FileVersion 常见写法 27.9 也应放行");
            TestHarness.True(VersionGate.SameMajorMinor("27.1.0+2505117", "27.1"), "27.1 与 27.1.0+后缀应视为一致");
            TestHarness.True(!VersionGate.SameMajorMinor("27.1", "27.2"), "27.1 与 27.2 必须不同");
        });

        harness.Run("闸门：unsupported 条目拒绝并给出原因", () =>
        {
            var gate = new VersionGate(new[] { Unsupported });
            var result = gate.Evaluate("1", "11111111", "26.0.0");
            TestHarness.True(!result.AllowScan, "unsupported 必须拒绝");
            TestHarness.Equal(BuildStatus.Unsupported, result.Status, "状态应为 Unsupported");
            TestHarness.Contains(result.Message, "已知不兼容", "应带上条目说明");
        });

        harness.Run("闸门：嵌入清单可解析且标注了本机构建", () =>
        {
            var gate = new VersionGate();
            TestHarness.True(gate.Entries.Count >= 1, "嵌入清单不应为空");
            var entry = gate.Entries.FirstOrDefault(item => item.Build == "26620374");
            TestHarness.True(entry is not null, "清单应包含本机构建 26620374");
            TestHarness.Equal(BuildStatus.Verified, entry!.Status, "本机 27.1 已在 2026-11-19 核对通过 → verified");
            TestHarness.Equal("27.1.0+2505117", entry.PluginVersion, "插件版本应记录下来");
        });

        harness.Run("闸门：清单损坏时按空清单处理（全部拒绝）", () =>
        {
            var gate = new VersionGate(Array.Empty<BuildEntry>());
            var result = gate.Evaluate("4530370", "26620374", "27.1.0+2505117");
            TestHarness.True(!result.AllowScan, "空清单必须拒绝一切构建");
        });
    }
}
