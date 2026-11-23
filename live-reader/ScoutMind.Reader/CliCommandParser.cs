using System.Globalization;

namespace ScoutMind.Reader;

/// <summary>已支持的子命令。</summary>
public enum CliCommand
{
    /// <summary>打印用法。</summary>
    Help,

    /// <summary>输出当前检测状态。</summary>
    Status,

    /// <summary>执行外部扫描器自检。</summary>
    Probe,

    /// <summary>执行一次扫描并落盘。</summary>
    Scan,

    /// <summary>轻量读取游戏日期（不启动完整扫描）。</summary>
    Date,

    /// <summary>列出兼容清单条目。</summary>
    CompatibilityList,
}

/// <summary>
/// 解析后的命令行选项。<see cref="Json"/> 为真时，stdout 只输出单个 JSON 对象。
/// </summary>
/// <param name="Command">子命令。</param>
/// <param name="Json">是否输出机器可读 JSON。</param>
/// <param name="OutputDirectory">扫描输出目录（仅 scan）。</param>
/// <param name="TimeoutSeconds">扫描超时秒数（仅 scan）。</param>
/// <param name="Engine">扫描后端：<c>native</c> 内置引擎或 <c>external</c> 外部扫描器；为空时自动选择。</param>
/// <param name="ReportPath">probe 结构化诊断报告的输出路径（仅 probe）。</param>
public sealed record CliOptions(
    CliCommand Command,
    bool Json,
    string? OutputDirectory,
    int? TimeoutSeconds,
    string? Engine = null,
    string? ReportPath = null);

/// <summary>
/// 命令行解析结果。失败时 <see cref="Error"/> 为面向用户的中文说明，调用方应以退出码 64 结束。
/// </summary>
/// <param name="Ok">解析是否成功。</param>
/// <param name="Options">成功时的选项。</param>
/// <param name="Error">失败原因。</param>
public sealed record CliParseResult(bool Ok, CliOptions? Options, string? Error)
{
    /// <summary>构造成功结果。</summary>
    /// <param name="options">解析出的选项。</param>
    /// <returns>成功结果。</returns>
    public static CliParseResult Success(CliOptions options) => new(true, options, null);

    /// <summary>构造失败结果。</summary>
    /// <param name="error">中文错误说明。</param>
    /// <returns>失败结果。</returns>
    public static CliParseResult Failure(string error) => new(false, null, error);
}

/// <summary>
/// 严格解析命令行：任何未知子命令、未知选项、缺失或非法的选项值都会失败，
/// 绝不被静默忽略。
/// </summary>
public static class CliCommandParser
{
    /// <summary>解析参数数组。</summary>
    /// <param name="args">进程参数（不含程序名）。</param>
    /// <returns>解析结果。</returns>
    public static CliParseResult Parse(IReadOnlyList<string> args)
    {
        ArgumentNullException.ThrowIfNull(args);

        var json = false;
        CliCommand? command = null;
        string? outputDirectory = null;
        int? timeoutSeconds = null;
        string? engine = null;
        string? reportPath = null;
        var index = 0;

        while (index < args.Count)
        {
            var argument = args[index];
            if (string.IsNullOrWhiteSpace(argument))
            {
                return CliParseResult.Failure("存在空参数，请检查命令行。");
            }

            if (argument is "--help" or "-h" or "help")
            {
                return CliParseResult.Success(new CliOptions(CliCommand.Help, json, null, null));
            }

            if (argument == "--json")
            {
                json = true;
                index++;
                continue;
            }

            if (command is null)
            {
                switch (argument)
                {
                    case "status":
                        command = CliCommand.Status;
                        index++;
                        break;
                    case "probe":
                        command = CliCommand.Probe;
                        index++;
                        break;
                    case "scan":
                        command = CliCommand.Scan;
                        index++;
                        break;
                    case "date":
                        command = CliCommand.Date;
                        index++;
                        break;
                    case "compatibility":
                        if (index + 1 >= args.Count || args[index + 1] != "list")
                        {
                            return CliParseResult.Failure("compatibility 只支持子命令 list（示例：compatibility list --json）。");
                        }

                        command = CliCommand.CompatibilityList;
                        index += 2;
                        break;
                    default:
                        return CliParseResult.Failure(
                            $"未知子命令：{argument}。可用子命令：status、probe、scan、compatibility list。");
                }

                continue;
            }

            if (command is CliCommand.Probe or CliCommand.Scan && argument == "--engine")
            {
                if (engine is not null)
                {
                    return CliParseResult.Failure("选项 --engine 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --engine 需要一个值（native 或 external）。");
                }

                var requested = args[index + 1].Trim().ToLowerInvariant();
                if (requested is not ("native" or "external"))
                {
                    return CliParseResult.Failure($"选项 --engine 只接受 native 或 external，实际为：{args[index + 1]}。");
                }

                engine = requested;
                index += 2;
                continue;
            }

            if (command == CliCommand.Probe && argument == "--report")
            {
                if (reportPath is not null)
                {
                    return CliParseResult.Failure("选项 --report 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --report 需要一个文件路径。");
                }

                var reportTarget = args[index + 1];
                if (string.IsNullOrWhiteSpace(reportTarget) || reportTarget.StartsWith("--", StringComparison.Ordinal))
                {
                    return CliParseResult.Failure("选项 --report 需要一个非空文件路径。");
                }

                reportPath = reportTarget;
                index += 2;
                continue;
            }

            if (command == CliCommand.Scan)
            {
                switch (argument)
                {
                    case "--output":
                        if (outputDirectory is not null)
                        {
                            return CliParseResult.Failure("选项 --output 重复指定。");
                        }

                        if (index + 1 >= args.Count)
                        {
                            return CliParseResult.Failure("选项 --output 需要一个目录值。");
                        }

                        var directory = args[index + 1];
                        if (string.IsNullOrWhiteSpace(directory) || directory.StartsWith("--", StringComparison.Ordinal))
                        {
                            return CliParseResult.Failure("选项 --output 需要一个非空目录值。");
                        }

                        outputDirectory = directory;
                        index += 2;
                        continue;

                    case "--timeout":
                        if (timeoutSeconds is not null)
                        {
                            return CliParseResult.Failure("选项 --timeout 重复指定。");
                        }

                        if (index + 1 >= args.Count)
                        {
                            return CliParseResult.Failure("选项 --timeout 需要一个秒数。");
                        }

                        if (!int.TryParse(args[index + 1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var seconds)
                            || seconds <= 0)
                        {
                            return CliParseResult.Failure($"选项 --timeout 需要正整数秒数，实际为：{args[index + 1]}。");
                        }

                        timeoutSeconds = seconds;
                        index += 2;
                        continue;

                    default:
                        return CliParseResult.Failure($"scan 不支持参数：{argument}。");
                }
            }

            return CliParseResult.Failure($"{ToDisplayName(command.Value)} 不支持参数：{argument}。");
        }

        if (command is null)
        {
            return CliParseResult.Failure("缺少子命令。可用子命令：status、probe、scan、compatibility list。");
        }

        return CliParseResult.Success(new CliOptions(command.Value, json, outputDirectory, timeoutSeconds, engine, reportPath));
    }

    private static string ToDisplayName(CliCommand command) => command switch
    {
        CliCommand.Status => "status",
        CliCommand.Probe => "probe",
        CliCommand.Scan => "scan",
        CliCommand.CompatibilityList => "compatibility list",
        _ => "help",
    };
}
