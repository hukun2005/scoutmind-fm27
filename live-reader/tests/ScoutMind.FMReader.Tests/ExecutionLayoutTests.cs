using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Tests;

/// <summary>TASK-005：诊断布局与执行布局的一致性。</summary>
internal static class ExecutionLayoutTests
{
    /// <summary>测试用布局：把 CA 偏移改掉，模拟"ScoutMind 更新了布局但上游没跟上"。</summary>
    private sealed class DivergedLayout : LayoutBase
    {
        public DivergedLayout()
            : base("FM27_1_TEST", 27, 1, Table(), FieldStatus.Pending, "测试用")
        {
            Require("PLAO_CA");
        }

        private static Dictionary<string, uint> Table()
        {
            var table = FM27_0_Layout.OffsetsTable();
            table["PLAO_CA"] = 0x999; // 与上游不同
            return table;
        }
    }

    public static void Run(TestHarness harness)
    {
        harness.Run("执行布局：FM27_1 与上游 Fields.FM27 的偏移完全一致", () =>
        {
            var layout = new FM27_1_Layout();
            var differences = LayoutConsistency.Compare(layout);
            TestHarness.True(differences.Count == 0,
                "不一致：" + string.Join("、", differences.Take(3).Select(item => $"{item.Field} {item.Diagnostic:X}≠{item.Execution:X}")));
        });

        harness.Run("执行布局：读取上游布局不修改任何值", () =>
        {
            var before = LayoutConsistency.ReadExecutionLayout();
            var layout = new FM27_1_Layout();
            _ = LayoutConsistency.Compare(layout);
            var after = LayoutConsistency.ReadExecutionLayout();
            TestHarness.True(before.Count == after.Count, "字段数不应变化");
            TestHarness.True(before.All(item => after.TryGetValue(item.Key, out var value) && value == item.Value), "值不应变化");
        });

        harness.Run("执行布局：偏移被改掉时能发现差异", () =>
        {
            var differences = LayoutConsistency.Compare(new DivergedLayout());
            TestHarness.True(differences.Count == 1, "应恰好发现 1 个差异");
            TestHarness.Equal("PLAO_CA", differences[0].Field, "差异字段");
            TestHarness.Equal(0x999u, differences[0].Diagnostic, "诊断布局值");
        });

        harness.Run("执行布局：一致时 scope 不应用任何字段", () =>
        {
            using var scope = UpstreamLayoutScope.Apply(new FM27_1_Layout());
            TestHarness.Equal(0, scope.AppliedFields, "一致时不应写上游");
        });

        harness.Run("执行布局：不一致时 scope 临时应用并在 Dispose 后恢复", () =>
        {
            var original = LayoutConsistency.ReadExecutionLayout()["PLAO_CA"];
            int applied;
            using (var scope = UpstreamLayoutScope.Apply(new DivergedLayout()))
            {
                applied = scope.AppliedFields;
                TestHarness.Equal(0x999u, LayoutConsistency.ReadExecutionLayout()["PLAO_CA"], "扫描期间上游应使用新值");
            }

            TestHarness.Equal(1, applied, "应应用 1 个字段");
            TestHarness.Equal(original, LayoutConsistency.ReadExecutionLayout()["PLAO_CA"], "Dispose 后必须恢复原值");
        });

        harness.Run("执行布局：未知构建没有布局，扫描前就被拒绝", () =>
        {
            var resolver = new LayoutResolver();
            TestHarness.Equal<string?>(null, resolver.Resolve("12345678")?.Name, "未登记构建必须没有布局");
        });
    }
}
