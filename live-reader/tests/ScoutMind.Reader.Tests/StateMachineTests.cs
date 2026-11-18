using ScoutMind.Contracts;

namespace ScoutMind.Reader.Tests;

/// <summary>状态机用例：允许边、拒绝边与失败终态。</summary>
public static class StateMachineTests
{
    /// <summary>注册并执行状态机用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Case("状态机拒绝 NotFound → ScanCompleted", () =>
        {
            var machine = new StateMachine();
            Assert.False(machine.CanTransitionTo(ReaderState.ScanCompleted), "NotFound 不能直接跳到 ScanCompleted");
            Assert.Throws<InvalidStateTransitionException>(
                () => machine.TransitionTo(ReaderState.ScanCompleted),
                "非法迁移必须抛出异常");
            Assert.Equal(ReaderState.NotFound, machine.Current, "非法迁移不得改变当前状态");
        });

        harness.Case("状态机允许文档中的完整成功路径", () =>
        {
            var machine = new StateMachine();
            machine.TransitionTo(ReaderState.Detected);
            machine.TransitionTo(ReaderState.VersionIdentified);
            machine.TransitionTo(ReaderState.Compatible);
            machine.TransitionTo(ReaderState.ProbePassed);
            machine.TransitionTo(ReaderState.ScanCompleted);

            Assert.Equal(ReaderState.ScanCompleted, machine.Current, "应停在 ScanCompleted");
            Assert.Equal(5, machine.History.Count, "应记录 5 次迁移");
            Assert.True(machine.Diagnostics.Count >= 5, "每次迁移都应留下诊断");
        });

        harness.Case("状态机允许失败分支并保持终态", () =>
        {
            var machine = new StateMachine();
            machine.TransitionTo(ReaderState.Detected);
            machine.TransitionTo(ReaderState.Unsupported);

            Assert.True(StateMachine.IsFailureState(machine.Current), "Unsupported 应为失败状态");
            Assert.False(machine.CanTransitionTo(ReaderState.Compatible), "失败状态不得继续迁移");

            var ex = Assert.Throws<InvalidStateTransitionException>(
                () => machine.TransitionTo(ReaderState.Compatible),
                "从失败状态迁移必须抛出");
            Assert.Contains(ex.Message, "Unsupported", "异常信息应包含当前状态");
        });

        harness.Case("状态机拒绝跳跃与自迁移", () =>
        {
            var machine = new StateMachine();
            Assert.False(machine.CanTransitionTo(ReaderState.NotFound), "不允许自迁移");
            Assert.False(machine.CanTransitionTo(ReaderState.Compatible), "NotFound 不允许直达 Compatible");

            machine.TransitionTo(ReaderState.Detected);
            Assert.True(machine.TryTransitionTo(ReaderState.VersionIdentified, out var allowed), "Detected → VersionIdentified 合法");
            Assert.True(allowed is null, "合法迁移不应给出原因");

            Assert.False(machine.TryTransitionTo(ReaderState.Compatible, out var reason), "Detected → Compatible 非法");
            Assert.Contains(reason, "不允许迁移", "拒绝原因应说明不允许迁移");
            Assert.Equal(ReaderState.Detected, machine.Current, "TryTransitionTo 不得改变状态");
        });

        harness.Case("ScanCompleted 之后也是终态", () =>
        {
            var machine = new StateMachine();
            machine.TransitionTo(ReaderState.Detected);
            machine.TransitionTo(ReaderState.VersionIdentified);
            machine.TransitionTo(ReaderState.Compatible);
            machine.TransitionTo(ReaderState.ProbePassed);
            machine.TransitionTo(ReaderState.ScanCompleted);

            Assert.False(machine.CanTransitionTo(ReaderState.Detected), "ScanCompleted 不允许重新开始");
            Assert.False(StateMachine.IsFailureState(ReaderState.ScanCompleted), "ScanCompleted 不是失败状态");
        });

        harness.Case("probe 失败只能从 Compatible/ProbePassed 进入", () =>
        {
            var machine = new StateMachine();
            Assert.False(machine.CanTransitionTo(ReaderState.ProbeFailed), "NotFound 不能直接 ProbeFailed");

            var compatible = new StateMachine();
            compatible.TransitionTo(ReaderState.Detected);
            compatible.TransitionTo(ReaderState.VersionIdentified);
            compatible.TransitionTo(ReaderState.Compatible);
            compatible.TransitionTo(ReaderState.ProbeFailed);
            Assert.Equal(ReaderState.ProbeFailed, compatible.Current, "Compatible → ProbeFailed 合法");
        });
    }
}
