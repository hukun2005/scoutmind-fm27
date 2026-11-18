using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Tests;

/// <summary>进程识别与插件/AppId 读取。</summary>
internal static class LocatorTests
{
    public static void Run(TestHarness harness)
    {
        var root = Path.Combine(AppContext.BaseDirectory, "test-tmp", "locator");
        Directory.CreateDirectory(root);

        var fm27 = Path.Combine(root, "Football Manager 27");
        Directory.CreateDirectory(Path.Combine(fm27, "fm_Data"));
        File.WriteAllText(Path.Combine(fm27, "steam_appid.txt"), "4530370");
        var fm27Exe = Path.Combine(fm27, "fm.exe");
        File.WriteAllText(fm27Exe, "stub");

        var notFm27 = Path.Combine(root, "Other Game");
        Directory.CreateDirectory(notFm27);
        var otherExe = Path.Combine(notFm27, "fm.exe");
        File.WriteAllText(otherExe, "stub");

        harness.Run("进程识别：只接受带 fm_Data 的 fm.exe", () =>
        {
            var locator = new FmProcessLocator(() => new[]
            {
                new FmProcessDescriptor(100, "fm", otherExe, DateTime.UtcNow),
                new FmProcessDescriptor(200, "fm", fm27Exe, DateTime.UtcNow.AddMinutes(-5)),
            });
            var location = locator.Locate();
            TestHarness.Equal<int?>(200, location.ProcessId, "应选中带 fm_Data 的那个进程");
            TestHarness.Equal(fm27, location.InstallDirectory, "安装目录应为 Football Manager 27");
        });

        harness.Run("进程识别：多个 fm 取最近启动的", () =>
        {
            var second = Path.Combine(root, "Football Manager 27 b");
            Directory.CreateDirectory(Path.Combine(second, "fm_Data"));
            var secondExe = Path.Combine(second, "fm.exe");
            File.WriteAllText(secondExe, "stub");
            var locator = new FmProcessLocator(() => new[]
            {
                new FmProcessDescriptor(300, "fm", fm27Exe, DateTime.UtcNow.AddMinutes(-10)),
                new FmProcessDescriptor(301, "fm", secondExe, DateTime.UtcNow),
            });
            TestHarness.Equal<int?>(301, locator.Locate().ProcessId, "应选中最近启动的 fm.exe");
        });

        harness.Run("进程识别：非 fm 进程被忽略", () =>
        {
            var locator = new FmProcessLocator(() => new[]
            {
                new FmProcessDescriptor(400, "notepad", fm27Exe, DateTime.UtcNow),
            });
            TestHarness.Equal<int?>(null, locator.Locate().ProcessId, "非 fm 进程不应被选中");
        });

        harness.Run("进程识别：读不到路径时给出诊断而不是崩溃", () =>
        {
            var locator = new FmProcessLocator(() => new[]
            {
                new FmProcessDescriptor(500, "fm", null, DateTime.UtcNow),
            });
            var location = locator.Locate();
            TestHarness.Equal<int?>(null, location.ProcessId, "没有路径时不应选中");
            TestHarness.True(location.Diagnostics.Any(text => text.Contains("权限", StringComparison.Ordinal)),
                "应记录权限不足的诊断");
        });

        harness.Run("AppId：优先 steam_appid.txt，读不到时按目录名，无法确定则为 null", () =>
        {
            TestHarness.Equal<string?>("4530370", FmProcessLocator.ReadAppId(fm27), "应读到 steam_appid.txt");
            File.Delete(Path.Combine(fm27, "steam_appid.txt"));
            TestHarness.Equal<string?>("4530370", FmProcessLocator.ReadAppId(fm27), "目录名含 Football Manager 27 时应识别");
            TestHarness.Equal<string?>(null, FmProcessLocator.ReadAppId(notFm27), "无法确定时必须是 null");
        });

        harness.Run("插件：缺失时版本为 null，不猜", () =>
        {
            var (path, version) = FmProcessLocator.ReadPlugin(fm27);
            TestHarness.True(path?.EndsWith("game_plugin.dll", StringComparison.OrdinalIgnoreCase) == true, "应给出插件路径");
            TestHarness.Equal<string?>(null, version, "文件不存在时版本必须是 null");
        });
    }


}
