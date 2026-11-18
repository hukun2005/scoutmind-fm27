using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// <see cref="ScannerConfig"/> 的加载结果与诊断。
/// </summary>
/// <param name="Config">生效配置；缺少 scanner.json 时为默认值（路径可能为空）。</param>
/// <param name="Diagnostics">加载过程中的说明，例如 scanner.json 不存在或格式非法。</param>
public sealed record ScannerConfigLoad(ScannerConfig Config, List<string> Diagnostics);

/// <summary>
/// 从可执行文件同目录的 <c>scanner.json</c> 加载外部扫描器配置，并允许用环境变量
/// <c>SCOUTMIND_SCANNER_PATH</c> 覆盖扫描器路径（便于测试与临时切换）。
/// </summary>
public static class ScannerConfigLoader
{
    /// <summary>覆盖扫描器路径的环境变量名。</summary>
    public const string ScannerPathEnvironmentVariable = "SCOUTMIND_SCANNER_PATH";

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>加载配置。</summary>
    /// <param name="baseDirectory">可执行文件所在目录。</param>
    /// <returns>生效配置与诊断。</returns>
    public static ScannerConfigLoad Load(string baseDirectory)
    {
        var diagnostics = new List<string>();
        var configPath = Path.Combine(baseDirectory, ReaderInfo.ScannerConfigFileName);
        ScannerConfig config = new();

        if (File.Exists(configPath))
        {
            try
            {
                var json = File.ReadAllText(configPath);
                var loaded = JsonSerializer.Deserialize<ScannerConfig>(json, Options);
                if (loaded is null)
                {
                    diagnostics.Add($"scanner.json 内容为空，使用默认配置：{configPath}");
                }
                else
                {
                    config = loaded;
                    diagnostics.Add($"已加载扫描器配置：{configPath}");
                }
            }
            catch (JsonException ex)
            {
                diagnostics.Add($"scanner.json 不是合法 JSON（{configPath}）：{ex.Message}，使用默认配置。");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                diagnostics.Add($"读取 scanner.json 失败（{configPath}）：{ex.Message}，使用默认配置。");
            }
        }
        else
        {
            diagnostics.Add($"未找到 scanner.json（{configPath}），使用默认配置；未配置扫描器时无法执行 probe 与 scan。");
        }

        var overridePath = Environment.GetEnvironmentVariable(ScannerPathEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            config = new ScannerConfig
            {
                ScannerPath = overridePath.Trim(),
                ProbeArguments = config.ProbeArguments,
                ScanArgumentsTemplate = config.ScanArgumentsTemplate,
                TimeoutSeconds = config.TimeoutSeconds,
                BackendBaseUrl = config.BackendBaseUrl,
                ApiToken = config.ApiToken,
                SaveName = config.SaveName,
            };
            diagnostics.Add($"扫描器路径被环境变量 {ScannerPathEnvironmentVariable} 覆盖：{config.ScannerPath}");
        }

        return new ScannerConfigLoad(config, diagnostics);
    }
}
