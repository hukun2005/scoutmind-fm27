namespace ScoutMind.Agent;

/// <summary>
/// 代理进程退出码。读取器的退出码（2/3/4/5）会原样透传，代理自身只新增同步与配置相关编码。
/// </summary>
public static class AgentExitCodes
{
    /// <summary>成功。</summary>
    public const int Success = 0;

    /// <summary>后端同步失败（网络、认证或后端拒绝）。扫描结果已保留在本地队列。</summary>
    public const int SyncFailed = 6;

    /// <summary>命令行用法错误。</summary>
    public const int UsageError = 64;

    /// <summary>配置错误（找不到读取器、agent.json 非法等）。</summary>
    public const int ConfigurationError = 65;
}
