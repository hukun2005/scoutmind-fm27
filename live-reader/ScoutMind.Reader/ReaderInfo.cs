namespace ScoutMind.Reader;

/// <summary>
/// 读取器的固定标识。版本号同时写入扫描信封与导入任务，便于追溯数据来源。
/// </summary>
public static class ReaderInfo
{
    /// <summary>读取器版本，必须与项目文件中的 <c>Version</c> 一致。</summary>
    public const string Version = "0.1.0";

    /// <summary>数据协议版本，与 <c>docs/DATA_PROTOCOL.md</c> 保持一致。</summary>
    public const string SchemaVersion = "1.0";

    /// <summary>数据来源标记，写入扫描信封的 <c>source</c> 字段。</summary>
    public const string Source = "fm27_live_reader";

    /// <summary>产品名，用于命令行标题与诊断信息。</summary>
    public const string Product = "ScoutMind 实时读取器";

    /// <summary>兼容清单文件名，位于可执行文件同目录。</summary>
    public const string CompatibilityFileName = "compatibility.json";

    /// <summary>扫描器配置文件名，位于可执行文件同目录，可选。</summary>
    public const string ScannerConfigFileName = "scanner.json";

    /// <summary>覆盖兼容清单路径的环境变量名，便于测试与多版本共存。</summary>
    public const string CompatibilityFileEnvironmentVariable = "SCOUTMIND_COMPATIBILITY_FILE";
}
