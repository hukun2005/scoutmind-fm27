using System.Globalization;

namespace ScoutMind.Agent;

/// <summary>代理支持的子命令。</summary>
public enum AgentCommand
{
    /// <summary>打印用法。</summary>
    Help,

    /// <summary>查询读取器状态。</summary>
    Status,

    /// <summary>执行一次扫描，可选立即同步。</summary>
    Scan,

    /// <summary>按固定间隔重复「扫描 + 同步」。</summary>
    Watch,

    /// <summary>按游戏日期自动采集：同日重复扫描只隔离，不重复导入。</summary>
    Auto,

    /// <summary>同步本地待上传的扫描结果。</summary>
    Sync,

    /// <summary>打印生效配置。</summary>
    ConfigShow,
}

/// <summary>
/// 解析后的代理命令行选项。
/// </summary>
/// <param name="Command">子命令。</param>
/// <param name="Json">是否以 JSON 输出（目前用于 status）。</param>
/// <param name="Sync">scan 后是否立即同步。</param>
/// <param name="IntervalMinutes">watch 的间隔分钟数。</param>
/// <param name="FilePath">sync 指定的单个文件。</param>
public sealed record AgentOptions(
    AgentCommand Command,
    bool Json,
    bool Sync,
    int? IntervalMinutes,
    string? FilePath);

/// <summary>
/// 代理命令行解析结果；失败时 <see cref="Error"/> 为中文说明。
/// </summary>
/// <param name="Ok">是否成功。</param>
/// <param name="Options">成功时的选项。</param>
/// <param name="Error">失败原因。</param>
public sealed record AgentParseResult(bool Ok, AgentOptions? Options, string? Error)
{
    /// <summary>构造成功结果。</summary>
    /// <param name="options">选项。</param>
    /// <returns>成功结果。</returns>
    public static AgentParseResult Success(AgentOptions options) => new(true, options, null);

    /// <summary>构造失败结果。</summary>
    /// <param name="error">中文错误说明。</param>
    /// <returns>失败结果。</returns>
    public static AgentParseResult Failure(string error) => new(false, null, error);
}

/// <summary>
/// 严格解析代理命令行：未知子命令、未知选项、缺失值与非法数字都直接失败。
/// </summary>
public static class AgentCommandLine
{
    /// <summary>解析参数。</summary>
    /// <param name="args">进程参数（不含程序名）。</param>
    /// <returns>解析结果。</returns>
    public static AgentParseResult Parse(IReadOnlyList<string> args)
    {
        ArgumentNullException.ThrowIfNull(args);

        var json = false;
        var sync = false;
        int? intervalMinutes = null;
        string? filePath = null;
        AgentCommand? command = null;
        var index = 0;

        while (index < args.Count)
        {
            var argument = args[index];
            if (string.IsNullOrWhiteSpace(argument))
            {
                return AgentParseResult.Failure("存在空参数，请检查命令行。");
            }

            if (argument is "--help" or "-h" or "help")
            {
                return AgentParseResult.Success(new AgentOptions(AgentCommand.Help, json, false, null, null));
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
                        command = AgentCommand.Status;
                        index++;
                        break;
                    case "scan":
                        command = AgentCommand.Scan;
                        index++;
                        break;
                    case "watch":
                        command = AgentCommand.Watch;
                        index++;
                        break;
                    case "auto":
                        command = AgentCommand.Auto;
                        index++;
                        break;
                    case "sync":
                        command = AgentCommand.Sync;
                        index++;
                        break;
                    case "config":
                        if (index + 1 >= args.Count || args[index + 1] != "show")
                        {
                            return AgentParseResult.Failure("config 只支持子命令 show（示例：config show）。");
                        }

                        command = AgentCommand.ConfigShow;
                        index += 2;
                        break;
                    default:
                        return AgentParseResult.Failure(
                            $"未知子命令：{argument}。可用子命令：status、scan、watch、auto、sync、config show。");
                }

                continue;
            }

            var consumed = TryConsumeOption(args, index, command.Value, ref sync, ref intervalMinutes, ref filePath, out var error);
            if (error is not null)
            {
                return AgentParseResult.Failure(error);
            }

            if (consumed <= 0)
            {
                return AgentParseResult.Failure($"{ToDisplayName(command.Value)} 不支持参数：{argument}。");
            }

            index += consumed;
        }

        if (command is null)
        {
            return AgentParseResult.Failure("缺少子命令。可用子命令：status、scan、watch、sync、config show。");
        }

        if (command is AgentCommand.Watch or AgentCommand.Auto && intervalMinutes is null)
        {
            return AgentParseResult.Failure("watch/auto 需要 --interval-minutes <分钟>。");
        }

        return AgentParseResult.Success(new AgentOptions(command.Value, json, sync, intervalMinutes, filePath));
    }

    private static int TryConsumeOption(
        IReadOnlyList<string> args,
        int index,
        AgentCommand command,
        ref bool sync,
        ref int? intervalMinutes,
        ref string? filePath,
        out string? error)
    {
        error = null;
        var argument = args[index];

        if (argument == "--sync" && command == AgentCommand.Scan)
        {
            sync = true;
            return 1;
        }

        if (argument == "--interval-minutes" && command is AgentCommand.Watch or AgentCommand.Auto)
        {
            if (intervalMinutes is not null)
            {
                error = "选项 --interval-minutes 重复指定。";
                return 0;
            }

            if (!TryReadValue(args, index, out var value, out error))
            {
                return 0;
            }

            if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var minutes) || minutes <= 0)
            {
                error = $"选项 --interval-minutes 需要正整数分钟，实际为：{value}。";
                return 0;
            }

            intervalMinutes = minutes;
            return 2;
        }

        if (argument == "--file" && command == AgentCommand.Sync)
        {
            if (filePath is not null)
            {
                error = "选项 --file 重复指定。";
                return 0;
            }

            if (!TryReadValue(args, index, out var value, out error))
            {
                return 0;
            }

            filePath = value;
            return 2;
        }

        return 0;
    }

    private static bool TryReadValue(IReadOnlyList<string> args, int index, out string value, out string? error)
    {
        error = null;
        if (index + 1 >= args.Count)
        {
            value = string.Empty;
            error = $"选项 {args[index]} 需要一个值。";
            return false;
        }

        value = args[index + 1];
        if (string.IsNullOrWhiteSpace(value) || value.StartsWith("--", StringComparison.Ordinal))
        {
            error = $"选项 {args[index]} 需要一个非空值。";
            return false;
        }

        return true;
    }

    private static string ToDisplayName(AgentCommand command) => command switch
    {
        AgentCommand.Status => "status",
        AgentCommand.Scan => "scan",
        AgentCommand.Watch => "watch",
    AgentCommand.Auto => "auto",
        AgentCommand.Sync => "sync",
        AgentCommand.ConfigShow => "config show",
        _ => "help",
    };
}
