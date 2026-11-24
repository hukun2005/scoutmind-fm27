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

    /// <summary>日期候选发现：在有限预算内寻找与人工提供的游戏内日期一致的编码。</summary>
    DateDiscovery,

    /// <summary>指针扫描：寻找指向目标区间的指针，用于定位稳定引用链。</summary>
    PointerScan,

    /// <summary>按结构签名定位世界日期（不依赖绝对地址）。</summary>
    DateLocate,

    /// <summary>打印上游扫描器解析的模块边界与扫描区域数量。</summary>
    ModuleInfo,

    /// <summary>从模块边界出发做静态根日期扫描。</summary>
    StaticDateScan,

    /// <summary>按模块 RVA + 偏移链直接读取日期。</summary>
    DateRead,

    /// <summary>启发式解析当前世界日期（签名 + 最新日期 + 稳定性）。</summary>
    WorldDate,

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
/// <param name="ExpectedDate">人工提供的游戏内日期（仅 date-discovery）。</param>
/// <param name="MaxScanMb">候选发现/指针扫描的最大扫描 MiB。</param>
/// <param name="TargetAddress">指针扫描的目标地址（仅 pointer-scan）。</param>
/// <param name="WindowBytes">目标区间长度（仅 pointer-scan）。</param>
/// <param name="MaxDepth">静态根扫描的最大跳数（仅 static-date-scan）。</param>
/// <param name="Rva">模块内静态指针槽位的 RVA（仅 date-read）。</param>
/// <param name="FieldOffset">日期字段相对目标对象的偏移（仅 date-read）。</param>
public sealed record CliOptions(
    CliCommand Command,
    bool Json,
    string? OutputDirectory,
    int? TimeoutSeconds,
    string? Engine = null,
    string? ReportPath = null,
    DateOnly? ExpectedDate = null,
    int? MaxScanMb = null,
    ulong? TargetAddress = null,
    int? WindowBytes = null,
    int? MaxDepth = null,
    ulong? Rva = null,
    int? FieldOffset = null);

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
        DateOnly? expectedDate = null;
        int? maxScanMb = null;
        ulong? targetAddress = null;
        int? windowBytes = null;
        int? maxDepth = null;
        ulong? rva = null;
        int? fieldOffset = null;
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
                    case "date-discovery":
                        command = CliCommand.DateDiscovery;
                        index++;
                        break;
                    case "pointer-scan":
                        command = CliCommand.PointerScan;
                        index++;
                        break;
                    case "date-locate":
                        command = CliCommand.DateLocate;
                        index++;
                        break;
                    case "module-info":
                        command = CliCommand.ModuleInfo;
                        index++;
                        break;
                    case "static-date-scan":
                        command = CliCommand.StaticDateScan;
                        index++;
                        break;
                    case "date-read":
                        command = CliCommand.DateRead;
                        index++;
                        break;
                    case "world-date":
                        command = CliCommand.WorldDate;
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

            if (command is CliCommand.DateDiscovery or CliCommand.StaticDateScan && argument == "--expect")
            {
                if (expectedDate is not null)
                {
                    return CliParseResult.Failure("选项 --expect 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --expect 需要一个日期（yyyy-MM-dd）。");
                }

                if (!DateOnly.TryParseExact(
                        args[index + 1],
                        "yyyy-MM-dd",
                        CultureInfo.InvariantCulture,
                        DateTimeStyles.None,
                        out var parsedDate))
                {
                    return CliParseResult.Failure(
                        $"选项 --expect 需要 yyyy-MM-dd 格式的日期，实际为：{args[index + 1]}。");
                }

                expectedDate = parsedDate;
                index += 2;
                continue;
            }

            if (command is CliCommand.DateDiscovery or CliCommand.PointerScan or CliCommand.DateLocate or CliCommand.StaticDateScan or CliCommand.WorldDate && argument == "--max-mb")
            {
                if (maxScanMb is not null)
                {
                    return CliParseResult.Failure("选项 --max-mb 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --max-mb 需要一个 MiB 数值。");
                }

                if (!int.TryParse(args[index + 1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var megabytes)
                    || megabytes < 1
                    || megabytes > 8192)
                {
                    return CliParseResult.Failure(
                        $"选项 --max-mb 需要 1..8192 的整数，实际为：{args[index + 1]}。");
                }

                maxScanMb = megabytes;
                index += 2;
                continue;
            }

            if (command == CliCommand.PointerScan && argument == "--target")
            {
                if (targetAddress is not null)
                {
                    return CliParseResult.Failure("选项 --target 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --target 需要一个十六进制地址（例如 0x24F9F1840F0）。");
                }

                var text = args[index + 1].Trim();
                if (!text.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
                    || !ulong.TryParse(
                        text.AsSpan(2),
                        NumberStyles.HexNumber,
                        CultureInfo.InvariantCulture,
                        out var address))
                {
                    return CliParseResult.Failure(
                        $"选项 --target 需要 0x 开头的十六进制地址，实际为：{args[index + 1]}。");
                }

                targetAddress = address;
                index += 2;
                continue;
            }

            if (command == CliCommand.PointerScan && argument == "--window")
            {
                if (windowBytes is not null)
                {
                    return CliParseResult.Failure("选项 --window 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --window 需要一个字节数（例如 4096）。");
                }

                if (!int.TryParse(args[index + 1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var window)
                    || window < 8
                    || window > 1 << 24)
                {
                    return CliParseResult.Failure(
                        $"选项 --window 需要 8..16777216 的整数，实际为：{args[index + 1]}。");
                }

                windowBytes = window;
                index += 2;
                continue;
            }

            if (command == CliCommand.StaticDateScan && argument == "--depth")
            {
                if (maxDepth is not null)
                {
                    return CliParseResult.Failure("选项 --depth 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --depth 需要一个 1 或 2 的跳数。");
                }

                if (!int.TryParse(args[index + 1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var depth)
                    || depth is < 1 or > 2)
                {
                    return CliParseResult.Failure($"选项 --depth 需要 1 或 2，实际为：{args[index + 1]}。");
                }

                maxDepth = depth;
                index += 2;
                continue;
            }

            if (command == CliCommand.DateRead && argument == "--rva")
            {
                if (rva is not null)
                {
                    return CliParseResult.Failure("选项 --rva 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --rva 需要一个十六进制 RVA（例如 0x5CE040）。");
                }

                var text = args[index + 1].Trim();
                if (!text.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
                    || !ulong.TryParse(text.AsSpan(2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var parsedRva))
                {
                    return CliParseResult.Failure($"选项 --rva 需要 0x 开头的十六进制值，实际为：{args[index + 1]}。");
                }

                rva = parsedRva;
                index += 2;
                continue;
            }

            if (command == CliCommand.DateRead && argument == "--field")
            {
                if (fieldOffset is not null)
                {
                    return CliParseResult.Failure("选项 --field 重复指定。");
                }

                if (index + 1 >= args.Count)
                {
                    return CliParseResult.Failure("选项 --field 需要十六进制偏移（例如 0x1E4）。");
                }

                var fieldText = args[index + 1].Trim();
                if (!fieldText.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
                    || !int.TryParse(fieldText.AsSpan(2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var parsedField))
                {
                    return CliParseResult.Failure($"选项 --field 需要 0x 开头的十六进制值，实际为：{args[index + 1]}。");
                }

                fieldOffset = parsedField;
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
            return CliParseResult.Failure(
                "缺少子命令。可用子命令：status、probe、scan、date、date-discovery、compatibility list。");
        }

        if (command == CliCommand.PointerScan && targetAddress is null)
        {
            return CliParseResult.Failure("pointer-scan 需要 --target <0x地址>。");
        }

        if (command == CliCommand.DateRead && (rva is null || fieldOffset is null))
        {
            return CliParseResult.Failure("date-read 需要 --rva <0x偏移> 与 --field <0x字段偏移>。");
        }

        if (command is CliCommand.DateDiscovery or CliCommand.StaticDateScan && expectedDate is null)
        {
            return CliParseResult.Failure(
                "date-discovery 需要 --expect <yyyy-MM-dd>：以游戏内显示的日期作为比对基准，不能猜测。");
        }

        return CliParseResult.Success(
            new CliOptions(command.Value, json, outputDirectory, timeoutSeconds, engine, reportPath, expectedDate, maxScanMb, targetAddress, windowBytes, maxDepth, rva, fieldOffset));
    }

    private static string ToDisplayName(CliCommand command) => command switch
    {
        CliCommand.Status => "status",
        CliCommand.Probe => "probe",
        CliCommand.Scan => "scan",
        CliCommand.Date => "date",
        CliCommand.DateDiscovery => "date-discovery",
        CliCommand.PointerScan => "pointer-scan",
        CliCommand.DateLocate => "date-locate",
        CliCommand.ModuleInfo => "module-info",
        CliCommand.StaticDateScan => "static-date-scan",
        CliCommand.DateRead => "date-read",
        CliCommand.WorldDate => "world-date",
        CliCommand.CompatibilityList => "compatibility list",
        _ => "help",
    };
}















