namespace ScoutMind.Contracts;

/// <summary>
/// 扫描请求。命令行上可覆盖输出目录、超时与扫描器路径，未给出时回落到 <see cref="ScannerConfig"/>。
/// </summary>
/// <param name="OutputDirectory">扫描产物（信封 JSON、stdout/stderr、meta 边车）的输出目录。</param>
/// <param name="TimeoutSeconds">扫描超时秒数；小于等于 0 时使用配置中的超时。</param>
/// <param name="ScannerPath">扫描器可执行文件路径覆盖；为 <c>null</c> 时使用配置值。</param>
public sealed record ScanRequest(
    string OutputDirectory,
    int TimeoutSeconds,
    string? ScannerPath);

/// <summary>
/// 一次扫描的结果。<see cref="State"/> 只会是 <see cref="ReaderState.ScanCompleted"/>
/// 或 <see cref="ReaderState.ProbeFailed"/>；后者表示必须拒绝后续读取。
/// </summary>
/// <param name="State">成功为 <see cref="ReaderState.ScanCompleted"/>，失败为 <see cref="ReaderState.ProbeFailed"/>。</param>
/// <param name="ScanId">扫描标识（GUID），同时作为后端的幂等键。</param>
/// <param name="StartedAt">开始时间（UTC）。</param>
/// <param name="FinishedAt">结束时间（UTC）。</param>
/// <param name="ExitCode">扫描器进程退出码；进程未能启动时为 <c>null</c>。</param>
/// <param name="OutputFile">落盘的信封 JSON 路径；失败时为 <c>null</c>。</param>
/// <param name="StdoutFile">扫描器 stdout 捕获文件路径。</param>
/// <param name="StderrFile">扫描器 stderr 捕获文件路径。</param>
/// <param name="PlayersCount">本次扫描得到的球员记录数（来自扫描器输出，不做补全）。</param>
/// <param name="TransfersCount">本次扫描得到的转会记录数。</param>
/// <param name="Warnings">检测与扫描阶段收集的告警。</param>
/// <param name="FailureReason">失败原因；成功时为 <c>null</c>。</param>
public sealed record ScanResult(
    ReaderState State,
    string ScanId,
    DateTimeOffset StartedAt,
    DateTimeOffset FinishedAt,
    int? ExitCode,
    string? OutputFile,
    string? StdoutFile,
    string? StderrFile,
    int PlayersCount,
    int TransfersCount,
    List<string> Warnings,
    string? FailureReason);

/// <summary>
/// 一次 probe（外部扫描器自检）的结果。probe 只验证扫描器能否在当前构建上启动并通过自检，
/// 不会写入游戏进程。
/// </summary>
/// <param name="Passed">是否通过。</param>
/// <param name="ExitCode">扫描器进程退出码；进程未能启动时为 <c>null</c>。</param>
/// <param name="DurationMs">probe 耗时（毫秒）。</param>
/// <param name="Output">扫描器 stdout 的截断副本（最多若干 KB），用于诊断。</param>
/// <param name="FailureReason">失败原因；成功时为 <c>null</c>。</param>
public sealed record ProbeResult(
    bool Passed,
    int? ExitCode,
    long DurationMs,
    string? Output,
    string? FailureReason);
