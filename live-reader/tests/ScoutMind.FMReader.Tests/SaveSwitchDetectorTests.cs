using ScoutMind.FMReader.Discovery;

namespace ScoutMind.FMReader.Tests;

/// <summary>存档切换检测：阈值确认、短暂失败不误判、PID 不变也必须识别切换。</summary>
public static class SaveSwitchDetectorTests
{
    private static readonly DateTime Start = new(2026, 11, 24, 10, 0, 0, DateTimeKind.Utc);

    private const string SaveA = "si:v1:file:aaaa";
    private const string SaveB = "si:v1:file:bbbb";

    /// <summary>注册并执行用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Run("切换：未运行时状态为 NotRunning", () =>
        {
            var detector = new SaveSwitchDetector();
            var decision = detector.Observe(Observe(process: false));

            TestHarness.Equal(SaveSwitchState.NotRunning, decision.State, "未运行");
            TestHarness.Equal(SaveSwitchEvent.None, decision.Event, "首次未运行不应产生退出事件");
            TestHarness.True(!decision.PauseTasks, "没有会话可暂停");
        });

        harness.Run("切换：首次载入存档产生 SaveLoaded", () =>
        {
            var detector = new SaveSwitchDetector();
            var decision = detector.Observe(Observe(SaveA, "100:start:26620374"));

            TestHarness.Equal(SaveSwitchState.Stable, decision.State, "应为稳定");
            TestHarness.Equal(SaveSwitchEvent.SaveLoaded, decision.Event, "应报告首次载入");
            TestHarness.True(!decision.PauseTasks, "首次载入无需暂停");
        });

        harness.Run("切换：同一存档保存只报告 SaveSaved，不暂停", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374", fileVersion: "hash-1"));
            var decision = detector.Observe(Observe(SaveA, "100:start:26620374", fileVersion: "hash-2"));

            TestHarness.Equal(SaveSwitchEvent.SaveSaved, decision.Event, "内容版本变化应识别为保存");
            TestHarness.True(!decision.PauseTasks, "保存不得暂停采集");
            TestHarness.True(!decision.InvalidatePreviousSession, "保存不得失效会话");
        });

        harness.Run("切换：指纹变化需连续两次确认，首次只暂停", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));

            var suspected = detector.Observe(Observe(SaveB, "100:start:26620374"));
            TestHarness.Equal(SaveSwitchState.Suspected, suspected.State, "首次变化只能疑似");
            TestHarness.Equal(SaveSwitchEvent.SwitchSuspected, suspected.Event, "应报告疑似");
            TestHarness.True(suspected.PauseTasks, "疑似时必须暂停");
            TestHarness.True(suspected.CancelPendingImports, "疑似时必须取消未提交导入");
            TestHarness.True(!suspected.InvalidatePreviousSession, "疑似时不得直接失效旧会话");

            var confirmed = detector.Observe(Observe(SaveB, "100:start:26620374"));
            TestHarness.Equal(SaveSwitchState.Confirmed, confirmed.State, "连续一致后应确认");
            TestHarness.Equal(SaveSwitchEvent.SaveSwitched, confirmed.Event, "应报告切换");
            TestHarness.True(confirmed.InvalidatePreviousSession, "确认后旧会话必须失效");
            TestHarness.Equal(SaveA, confirmed.PreviousFingerprint, "应给出旧指纹");
            TestHarness.Equal(SaveB, confirmed.CurrentFingerprint, "应给出新指纹");
        });

        harness.Run("切换：PID 不变也必须识别存档切换", () =>
        {
            var detector = new SaveSwitchDetector(confirmThreshold: 1);
            detector.Observe(Observe(SaveA, "100:start:26620374"));
            var decision = detector.Observe(Observe(SaveB, "100:start:26620374"));

            TestHarness.Equal(SaveSwitchEvent.SaveSwitched, decision.Event, "PID 相同不构成同一存档");
        });

        harness.Run("切换：短暂读取失败不认定为切换", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));

            var unstable = detector.Observe(Observe(fingerprint: null, resolved: false, session: "100:start:26620374"));
            TestHarness.Equal(SaveSwitchEvent.EvidenceUnstable, unstable.Event, "应报告证据不稳定");
            TestHarness.Equal(SaveSwitchState.Suspected, unstable.State, "应暂停但不定性");
            TestHarness.True(!unstable.InvalidatePreviousSession, "读取失败不得失效会话");

            var recovered = detector.Observe(Observe(SaveA, "100:start:26620374"));
            TestHarness.Equal(SaveSwitchState.Stable, recovered.State, "恢复后应回到稳定");
            TestHarness.True(!recovered.PauseTasks, "恢复后应允许继续");
        });

        harness.Run("切换：游戏重启载入同一存档不算切换", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));
            var decision = detector.Observe(Observe(SaveA, "200:start2:26620374"));

            TestHarness.Equal(SaveSwitchEvent.ProcessRestarted, decision.Event, "应识别为进程重启");
            TestHarness.Equal(SaveSwitchState.Stable, decision.State, "同一存档仍是稳定");
            TestHarness.True(decision.InvalidatePreviousSession, "旧进程会话仍应失效");
            TestHarness.True(!decision.PauseTasks, "同一存档无需暂停采集");
        });

        harness.Run("切换：游戏重启载入另一存档直接确认切换", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));
            var decision = detector.Observe(Observe(SaveB, "200:start2:26620374"));

            TestHarness.Equal(SaveSwitchEvent.SaveSwitched, decision.Event, "重启后换存档应确认切换");
            TestHarness.True(decision.InvalidatePreviousSession, "旧会话必须失效");
        });

        harness.Run("切换：游戏退出必须暂停并失效会话", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));
            var decision = detector.Observe(Observe(process: false));

            TestHarness.Equal(SaveSwitchState.NotRunning, decision.State, "应为未运行");
            TestHarness.Equal(SaveSwitchEvent.ProcessExited, decision.Event, "应报告退出");
            TestHarness.True(decision.PauseTasks, "退出时必须暂停");
            TestHarness.True(decision.CancelPendingImports, "退出时必须取消未提交导入");
            TestHarness.True(decision.InvalidatePreviousSession, "退出时必须失效会话");
        });

        harness.Run("切换：冲突时不自动选择任一存档", () =>
        {
            var detector = new SaveSwitchDetector();
            detector.Observe(Observe(SaveA, "100:start:26620374"));
            var decision = detector.Observe(Observe(SaveB, "100:start:26620374", conflict: true));

            TestHarness.Equal(SaveSwitchState.Conflict, decision.State, "冲突状态");
            TestHarness.Equal(SaveSwitchEvent.ConflictDetected, decision.Event, "应报告冲突");
            TestHarness.True(decision.PauseTasks, "冲突时必须暂停");
            TestHarness.True(!decision.InvalidatePreviousSession, "冲突时不得自动选边");
        });
    }

    private static SaveObservation Observe(
        string? fingerprint = null,
        string? session = null,
        bool process = true,
        bool resolved = true,
        bool conflict = false,
        string? fileVersion = null) => new(
        Start,
        process,
        session,
        fingerprint,
        resolved,
        conflict,
        fileVersion,
        "26620374");
}
