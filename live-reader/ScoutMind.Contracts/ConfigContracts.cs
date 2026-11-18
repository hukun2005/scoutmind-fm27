namespace ScoutMind.Contracts;

/// <summary>
/// 外部扫描器配置。读取器从不内置偏移量，所有扫描工作都委托给这个外部可执行文件。
/// 参数模板中的占位符在运行时替换：<c>{output}</c>（输出目录）、<c>{scanId}</c>、<c>{saveName}</c>。
/// </summary>
public sealed class ScannerConfig
{
    /// <summary>扫描器可执行文件的绝对路径；为空表示未配置，读取器会拒绝 probe 与 scan。</summary>
    public string ScannerPath { get; init; } = string.Empty;

    /// <summary>probe 参数列表，逐项传递，不经过 shell。</summary>
    public List<string> ProbeArguments { get; init; } = new();

    /// <summary>扫描参数模板，按引号规则切分为多个参数，例如 <c>--scan --output "{output}"</c>。</summary>
    public string ScanArgumentsTemplate { get; init; } = "--scan --output \"{output}\"";

    /// <summary>默认超时秒数；请求中未指定或小于等于 0 时使用。</summary>
    public int TimeoutSeconds { get; init; } = 120;

    /// <summary>后端基础地址，例如 <c>http://127.0.0.1:8000/api/v1</c>。</summary>
    public string BackendBaseUrl { get; init; } = "http://127.0.0.1:8000/api/v1";

    /// <summary>后端 API Token；配置后代理会带 <c>X-ScoutMind-Token</c> 请求头。</summary>
    public string? ApiToken { get; init; }

    /// <summary>存档名，仅用于模板占位符 <c>{saveName}</c> 与日志，不影响扫描内容。</summary>
    public string? SaveName { get; init; }
}

/// <summary>
/// 桌面代理配置（<c>agent.json</c>）。字段集合与 <see cref="ScannerConfig"/> 一致，
/// 额外包含代理自身的读取器路径与队列目录；两份结构分别对应两个 JSON 文件，因此字段重复声明。
/// </summary>
public sealed class AgentConfig
{
    /// <summary>读取器可执行文件路径；为空时使用代理同目录下的 <c>ScoutMind.LiveReader.exe</c>。</summary>
    public string? ReaderPath { get; init; }

    /// <summary>扫描器可执行文件的绝对路径（透传给读取器的一次性配置）。</summary>
    public string ScannerPath { get; init; } = string.Empty;

    /// <summary>probe 参数列表，逐项传递，不经过 shell。</summary>
    public List<string> ProbeArguments { get; init; } = new();

    /// <summary>扫描参数模板，占位符规则同 <see cref="ScannerConfig.ScanArgumentsTemplate"/>。</summary>
    public string ScanArgumentsTemplate { get; init; } = "--scan --output \"{output}\"";

    /// <summary>单次扫描的超时秒数。</summary>
    public int TimeoutSeconds { get; init; } = 120;

    /// <summary>后端基础地址。</summary>
    public string BackendBaseUrl { get; init; } = "http://127.0.0.1:8000/api/v1";

    /// <summary>后端 API Token；为空表示后端未启用鉴权。</summary>
    public string? ApiToken { get; init; }

    /// <summary>存档名，用于日志与模板占位符。</summary>
    public string? SaveName { get; init; }

    /// <summary>本地队列目录（扫描产物、待同步文件、已同步归档）；为空时使用 <c>&lt;exe 目录&gt;/queue</c>。</summary>
    public string? QueueDirectory { get; init; }

    /// <summary>转换为读取器使用的扫描器配置，供 <c>probe</c> 与 <c>scan</c> 透传。</summary>
    /// <returns>字段一一对应的 <see cref="ScannerConfig"/> 实例。</returns>
    public ScannerConfig ToScannerConfig() => new()
    {
        ScannerPath = ScannerPath,
        ProbeArguments = new List<string>(ProbeArguments),
        ScanArgumentsTemplate = ScanArgumentsTemplate,
        TimeoutSeconds = TimeoutSeconds,
        BackendBaseUrl = BackendBaseUrl,
        ApiToken = ApiToken,
        SaveName = SaveName,
    };
}
