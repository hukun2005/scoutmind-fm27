using System.Globalization;
using System.Text;

namespace ScoutMind.Reader.Tests;

/// <summary>
/// 测试用的假扫描器：通过 <c>--fake-scanner &lt;mode&gt;</c> 参数启动，供 ScannerAdapter 真实地
/// 启动、超时、终止与校验。它只写文件与 stdout/stderr，不接触游戏。
/// </summary>
public static class FakeScanner
{
    /// <summary>假扫描器的模式参数。</summary>
    public const string ModeArgument = "--fake-scanner";

    /// <summary>「我启动了」标记文件路径的环境变量。</summary>
    public const string MarkerEnvironmentVariable = "SCOUTMIND_TEST_MARKER";

    /// <summary>子进程写 PID 的文件路径环境变量。</summary>
    public const string PidFileEnvironmentVariable = "SCOUTMIND_TEST_PID_FILE";

    /// <summary>判断本次进程启动是否是假扫描器调用。</summary>
    /// <param name="args">进程参数。</param>
    /// <returns>是假扫描器调用时返回 <c>true</c>。</returns>
    public static bool IsFakeScannerInvocation(string[] args) => args.Length >= 2 && args[0] == ModeArgument;

    /// <summary>执行假扫描器模式。</summary>
    /// <param name="args">进程参数，<c>args[1]</c> 为模式名。</param>
    /// <returns>进程退出码。</returns>
    public static async Task<int> RunAsync(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
        var mode = args[1];
        switch (mode)
        {
            case "mark":
                await WriteMarkerAsync().ConfigureAwait(false);
                return 0;

            case "probe-ok":
                Console.Out.Write("{\"probe\":\"ok\"}");
                return 0;

            case "probe-fail":
                Console.Error.Write("probe 自检失败：模拟错误");
                return 3;

            case "sleep":
                await WritePidAsync().ConfigureAwait(false);
                Thread.Sleep(TimeSpan.FromSeconds(30));
                return 0;

            case "scan-ok":
                Console.Out.Write(ScanOkJson);
                return 0;

            case "scan-invalid-json":
                Console.Out.Write("这不是 JSON {{{");
                return 0;

            case "scan-missing-schema":
                Console.Out.Write("{\"players\":[]}");
                return 0;

            case "scan-fail":
                Console.Error.Write("扫描器内部错误：模拟失败");
                return 2;

            default:
                Console.Error.Write($"未知的假扫描器模式：{mode}");
                return 90;
        }
    }

    /// <summary>合法的扫描协议输出，含中文告警与一条球员记录。</summary>
    private const string ScanOkJson = """
        {
          "schema_version": "1.0",
          "source": "external",
          "game": {"version": "27.1.0", "build": "26620374", "app_id": "4530370"},
          "scan": {
            "scan_id": "test-scan-0001",
            "observed_at": "2026-11-18T03:00:00Z",
            "game_date": "2027-03-01",
            "user_club_uid": "1001"
          },
          "coverage": {"players": true, "transfers": true, "finances": false},
          "warnings": ["测试扫描器输出，不是真实 FM27 数据"],
          "clubs": [],
          "players": [{"record_id": "p-1", "save_local_uid": "1", "name": "Test Player"}],
          "transfers": []
        }
        """;

    private static async Task WriteMarkerAsync()
    {
        var path = Environment.GetEnvironmentVariable(MarkerEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(path))
        {
            await File.WriteAllTextAsync(path, "started").ConfigureAwait(false);
        }
    }

    private static async Task WritePidAsync()
    {
        var path = Environment.GetEnvironmentVariable(PidFileEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(path))
        {
            await File.WriteAllTextAsync(path, Environment.ProcessId.ToString(CultureInfo.InvariantCulture))
                .ConfigureAwait(false);
        }
    }
}
