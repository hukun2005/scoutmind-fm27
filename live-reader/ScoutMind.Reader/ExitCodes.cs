namespace ScoutMind.Reader;

/// <summary>
/// 命令行退出码。与 <c>docs/LIVE_READER.md</c> 保持一致，脚本与代理依赖这些值。
/// </summary>
public static class ExitCodes
{
    /// <summary>成功。</summary>
    public const int Success = 0;

    /// <summary>未找到 FM27（Steam 安装与进程都不存在）。</summary>
    public const int NotFound = 2;

    /// <summary>构建或版本不受支持 / 无法确定，读取被拒绝。</summary>
    public const int Incompatible = 3;

    /// <summary>probe 失败，或状态未达到可 probe 的阶段。</summary>
    public const int ProbeFailed = 4;

    /// <summary>扫描失败（扫描器崩溃、超时、输出不符合协议或写入失败）。</summary>
    public const int ScanFailed = 5;

    /// <summary>用法或配置错误（未知参数、未配置扫描器、兼容清单不可用）。</summary>
    public const int UsageError = 64;
}
