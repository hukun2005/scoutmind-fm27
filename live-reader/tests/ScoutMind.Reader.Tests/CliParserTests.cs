using ScoutMind.Contracts;

namespace ScoutMind.Reader.Tests;

/// <summary>命令行解析用例：合法组合被正确解析，未知输入一律报错。</summary>
public static class CliParserTests
{
    /// <summary>注册并执行命令行用例。</summary>
    /// <param name="harness">测试框架。</param>
    /// <returns>表示执行完成的任务。</returns>
    public static async Task RunAsync(TestHarness harness)
    {
        harness.Case("world-date --diagnostics 解析验证日期与状态文件", () =>
        {
            var parsed = CliCommandParser.Parse(new[]
            {
                "world-date", "--diagnostics", "--verify", "2026-11-06",
                "--state", @"C:\out\date-state.json", "--json",
            });

            Assert.True(parsed.Ok, "合法参数应解析成功");
            var options = parsed.Options!;
            Assert.Equal(CliCommand.WorldDate, options.Command, "子命令应为 world-date");
            Assert.True(options.Diagnostics, "应识别 --diagnostics");
            Assert.Equal<DateOnly?>(new DateOnly(2026, 11, 6), options.VerificationDate, "应解析 --verify");
            Assert.Equal(@"C:\out\date-state.json", options.StatePath, "应解析 --state");
            Assert.True(options.Json, "应识别 --json");
        });

        harness.Case("world-date --verify 必须为合法日期，且仅 world-date 支持诊断选项", () =>
        {
            Assert.False(
                CliCommandParser.Parse(new[] { "world-date", "--verify" }).Ok,
                "--verify 缺少值必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "world-date", "--verify", "2026-13-01" }).Ok,
                "非法日期必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "world-date", "--diagnostics", "--diagnostics" }).Ok,
                "重复 --diagnostics 必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "scan", "--diagnostics" }).Ok,
                "scan 不接受 --diagnostics");
            Assert.False(
                CliCommandParser.Parse(new[] { "world-date", "--state" }).Ok,
                "--state 缺少值必须失败");
        });

        harness.Case("scan --output 与 --timeout 被正确解析", () =>
        {
            var parsed = CliCommandParser.Parse(
                new[] { "scan", "--output", @"C:\out", "--timeout", "90", "--json" });

            Assert.True(parsed.Ok, "合法参数应解析成功");
            var options = parsed.Options!;
            Assert.Equal(CliCommand.Scan, options.Command, "子命令应为 scan");
            Assert.Equal(@"C:\out", options.OutputDirectory, "输出目录应被解析");
            Assert.Equal<int?>(90, options.TimeoutSeconds, "超时应被解析");
            Assert.True(options.Json, "应识别 --json");
        });

        harness.Case("probe --report 解析为报告路径，且仅 probe 接受该选项", () =>
        {
            var parsed = CliCommandParser.Parse(new[] { "probe", "--report", @"C:\out\probe.json", "--json" });
            Assert.True(parsed.Ok, "合法参数应解析成功");
            Assert.Equal(CliCommand.Probe, parsed.Options!.Command, "子命令应为 probe");
            Assert.Equal(@"C:\out\probe.json", parsed.Options.ReportPath, "报告路径应被解析");

            Assert.False(CliCommandParser.Parse(new[] { "probe", "--report" }).Ok, "--report 缺少值必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "probe", "--report", "a", "--report", "b" }).Ok,
                "重复 --report 必须失败");
            Assert.False(CliCommandParser.Parse(new[] { "scan", "--report", "a" }).Ok, "scan 不接受 --report");
        });

        harness.Case("未知子命令与未知选项 → 解析失败", () =>
        {
            var unknownCommand = CliCommandParser.Parse(new[] { "frobnicate" });
            Assert.False(unknownCommand.Ok, "未知子命令必须失败");
            Assert.Contains(unknownCommand.Error, "未知子命令", "错误应说明未知子命令");

            var unknownOption = CliCommandParser.Parse(new[] { "status", "--verbose" });
            Assert.False(unknownOption.Ok, "未知选项必须失败");
            Assert.Contains(unknownOption.Error, "不支持参数", "错误应说明不支持的参数");

            var scanOptionOnStatus = CliCommandParser.Parse(new[] { "status", "--timeout", "10" });
            Assert.False(scanOptionOnStatus.Ok, "status 不接受 --timeout");
        });

        harness.Case("选项缺少值或值非法 → 解析失败", () =>
        {
            Assert.False(CliCommandParser.Parse(new[] { "scan", "--output" }).Ok, "--output 缺少值必须失败");
            Assert.False(CliCommandParser.Parse(new[] { "scan", "--output", "--json" }).Ok, "--output 值不能是选项");
            Assert.False(CliCommandParser.Parse(new[] { "scan", "--timeout", "abc" }).Ok, "超时不是数字必须失败");
            Assert.False(CliCommandParser.Parse(new[] { "scan", "--timeout", "0" }).Ok, "超时为零必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "scan", "--timeout", "10", "--timeout", "20" }).Ok,
                "重复选项必须失败");
        });

        harness.Case("compatibility 只接受 list，且缺少子命令时报错", () =>
        {
            var list = CliCommandParser.Parse(new[] { "compatibility", "list" });
            Assert.True(list.Ok, "compatibility list 应合法");
            Assert.Equal(CliCommand.CompatibilityList, list.Options!.Command, "子命令应为兼容清单");

            Assert.False(CliCommandParser.Parse(new[] { "compatibility" }).Ok, "缺少 list 必须失败");
            Assert.False(CliCommandParser.Parse(new[] { "compatibility", "add" }).Ok, "未知子命令必须失败");
            Assert.False(CliCommandParser.Parse(Array.Empty<string>()).Ok, "缺少子命令必须失败");
        });

        harness.Case("pointer-scan 与 date-locate 的参数校验", () =>
        {
            var scan = CliCommandParser.Parse(new[] { "pointer-scan", "--target", "0x24F9F1840F0" });
            Assert.True(scan.Ok, "合法目标地址应通过");
            Assert.Equal(CliCommand.PointerScan, scan.Options!.Command, "子命令应为指针扫描");
            Assert.Equal(0x24F9F1840F0UL, scan.Options.TargetAddress, "目标地址应被解析");
            Assert.False(CliCommandParser.Parse(new[] { "pointer-scan" }).Ok, "缺少 --target 必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "pointer-scan", "--target", "24F9F1840F0" }).Ok,
                "缺少 0x 前缀必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "pointer-scan", "--target", "0x24F9F1840F0", "--window", "4" }).Ok,
                "窗口过小必须失败");

            var locate = CliCommandParser.Parse(new[] { "date-locate", "--max-mb", "4096" });
            Assert.True(locate.Ok, "date-locate 合法用法应通过");
            Assert.Equal(CliCommand.DateLocate, locate.Options!.Command, "子命令应为世界日期定位");
            Assert.Equal(4096, locate.Options.MaxScanMb, "预算应被解析");
            Assert.False(
                CliCommandParser.Parse(new[] { "date-locate", "--max-mb", "0" }).Ok,
                "预算为零必须失败");
        });
        harness.Case("date-discovery 必须提供 --expect 且日期格式受限", () =>
        {
            var ok = CliCommandParser.Parse(new[] { "date-discovery", "--expect", "2026-10-23" });
            Assert.True(ok.Ok, "合法用法应通过");
            Assert.Equal(CliCommand.DateDiscovery, ok.Options!.Command, "子命令应为日期候选发现");
            Assert.Equal(new DateOnly(2026, 10, 23), ok.Options.ExpectedDate, "期望日期应被解析");

            Assert.False(CliCommandParser.Parse(new[] { "date-discovery" }).Ok, "缺少 --expect 必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "date-discovery", "--expect", "2026-13-40" }).Ok,
                "非法日期必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "date-discovery", "--expect", "23/10/2026" }).Ok,
                "非 yyyy-MM-dd 必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "date-discovery", "--expect", "2026-10-23", "--expect", "2026-10-24" }).Ok,
                "重复 --expect 必须失败");
            Assert.False(
                CliCommandParser.Parse(new[] { "status", "--expect", "2026-10-23" }).Ok,
                "status 不接受 --expect");
        });

        harness.Case("--help 被识别为帮助命令", () =>
        {
            Assert.Equal(CliCommand.Help, CliCommandParser.Parse(new[] { "--help" }).Options!.Command, "--help 应为帮助");
            Assert.Equal(CliCommand.Help, CliCommandParser.Parse(new[] { "status", "--help" }).Options!.Command, "任意位置 --help 优先");
        });

        harness.Case("参数模板按引号切分", () =>
        {
            var arguments = CommandLineSplitter.Split("--scan --output \"{output}\" --save \"默认 存档\"");
            Assert.Equal(5, arguments.Count, "应切分为 5 个参数");
            Assert.Equal("{output}", arguments[2], "引号包裹的占位符应完整保留");
            Assert.Equal("默认 存档", arguments[4], "含空格的引号参数应作为一个整体");

            Assert.Throws<FormatException>(
                () => CommandLineSplitter.Split("--scan \"unclosed"),
                "未闭合引号必须报错");
        });

        await harness.CaseAsync("未知参数使 CLI 以 64 退出", async () =>
        {
            var stdout = new StringWriter();
            var stderr = new StringWriter();
            var cli = new Cli(stdout, stderr, AppContext.BaseDirectory);

            var code = await cli.RunAsync(new[] { "--bogus" }, CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ExitCodes.UsageError, code, "用法错误应返回 64");
            Assert.Contains(stderr.ToString(), "参数错误", "错误说明应写入 stderr");
            Assert.Contains(stderr.ToString(), "用法", "用法应随错误一起打印到 stderr");
            Assert.Equal(string.Empty, stdout.ToString(), "用法错误不应污染 stdout");
        }).ConfigureAwait(false);

        await harness.CaseAsync("--help 以 0 退出并打印用法", async () =>
        {
            var stdout = new StringWriter();
            var cli = new Cli(stdout, new StringWriter(), AppContext.BaseDirectory);

            var code = await cli.RunAsync(new[] { "--help" }, CancellationToken.None).ConfigureAwait(false);

            Assert.Equal(ExitCodes.Success, code, "帮助应返回 0");
            Assert.Contains(stdout.ToString(), "status", "用法应列出 status 子命令");
            Assert.Contains(stdout.ToString(), "64", "用法应列出退出码");
        }).ConfigureAwait(false);

        harness.Case("状态到退出码的映射", () =>
        {
            Assert.Equal(ExitCodes.NotFound, Cli.MapState(ReaderState.NotFound), "NotFound → 2");
            Assert.Equal(ExitCodes.Incompatible, Cli.MapState(ReaderState.Unsupported), "Unsupported → 3");
            Assert.Equal(ExitCodes.Incompatible, Cli.MapState(ReaderState.Unknown), "Unknown → 3");
            Assert.Equal(ExitCodes.ProbeFailed, Cli.MapState(ReaderState.ProbeFailed), "ProbeFailed → 4");
            Assert.Equal(ExitCodes.Success, Cli.MapState(ReaderState.Compatible), "Compatible → 0");
            Assert.Equal(ExitCodes.Success, Cli.MapState(ReaderState.ScanCompleted), "ScanCompleted → 0");
        });
    }
}

