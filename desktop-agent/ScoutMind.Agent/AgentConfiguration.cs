using System.Text.Json;
using ScoutMind.Contracts;

namespace ScoutMind.Agent;

/// <summary>
/// 代理启动时解析出的运行配置：生效的 <see cref="AgentConfig"/>、读取器绝对路径与队列目录。
/// </summary>
/// <param name="Config">生效配置。</param>
/// <param name="ReaderPath">读取器可执行文件（或 .dll）绝对路径；未找到时为空字符串。</param>
/// <param name="QueueDirectory">本地队列根目录（scans / pending / sent）。</param>
/// <param name="Diagnostics">加载过程中的说明，例如 agent.json 缺失或环境变量覆盖。</param>
public sealed record AgentRuntimeConfiguration(
    AgentConfig Config,
    string ReaderPath,
    string QueueDirectory,
    List<string> Diagnostics);

/// <summary>
/// 加载 <c>agent.json</c> 并解析读取器路径与队列目录。
/// 读取器默认取代理同目录的 <c>ScoutMind.LiveReader.exe</c>，找不到时退回同目录的
/// <c>ScoutMind.LiveReader.dll</c>（开发期 <c>dotnet run</c> 使用）。
/// </summary>
public static class AgentConfiguration
{
    /// <summary>配置文件名，位于可执行文件同目录。</summary>
    public const string ConfigFileName = "agent.json";

    /// <summary>覆盖配置文件路径的环境变量。</summary>
    public const string ConfigPathEnvironmentVariable = "SCOUTMIND_AGENT_CONFIG";

    /// <summary>覆盖读取器路径的环境变量。</summary>
    public const string ReaderPathEnvironmentVariable = "SCOUTMIND_READER_PATH";

    /// <summary>覆盖后端地址的环境变量。</summary>
    public const string BackendBaseUrlEnvironmentVariable = "SCOUTMIND_BACKEND_URL";

    /// <summary>覆盖后端 Token 的环境变量。</summary>
    public const string ApiTokenEnvironmentVariable = "SCOUTMIND_API_TOKEN";

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>加载配置。</summary>
    /// <param name="baseDirectory">可执行文件所在目录。</param>
    /// <returns>运行配置与诊断。</returns>
    public static AgentRuntimeConfiguration Load(string baseDirectory)
    {
        var diagnostics = new List<string>();
        var config = LoadConfigFile(baseDirectory, diagnostics);
        config = ApplyEnvironmentOverrides(config, diagnostics);

        var readerPath = ResolveReaderPath(config, baseDirectory, diagnostics);
        var queueDirectory = ResolveQueueDirectory(config, baseDirectory);

        return new AgentRuntimeConfiguration(config, readerPath, queueDirectory, diagnostics);
    }

    private static AgentConfig LoadConfigFile(string baseDirectory, List<string> diagnostics)
    {
        var overridePath = Environment.GetEnvironmentVariable(ConfigPathEnvironmentVariable);
        var configPath = string.IsNullOrWhiteSpace(overridePath)
            ? Path.Combine(baseDirectory, ConfigFileName)
            : Path.GetFullPath(overridePath.Trim());

        if (!File.Exists(configPath))
        {
            diagnostics.Add($"未找到 {ConfigFileName}（{configPath}），使用默认配置。");
            return new AgentConfig();
        }

        try
        {
            var json = File.ReadAllText(configPath);
            var loaded = JsonSerializer.Deserialize<AgentConfig>(json, Options);
            if (loaded is null)
            {
                diagnostics.Add($"{configPath} 内容为空，使用默认配置。");
                return new AgentConfig();
            }

            diagnostics.Add($"已加载配置：{configPath}");
            return loaded;
        }
        catch (JsonException ex)
        {
            diagnostics.Add($"{configPath} 不是合法 JSON：{ex.Message}；使用默认配置。");
            return new AgentConfig();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            diagnostics.Add($"读取 {configPath} 失败：{ex.Message}；使用默认配置。");
            return new AgentConfig();
        }
    }

    private static AgentConfig ApplyEnvironmentOverrides(AgentConfig config, List<string> diagnostics)
    {
        var backendUrl = Environment.GetEnvironmentVariable(BackendBaseUrlEnvironmentVariable);
        var apiToken = Environment.GetEnvironmentVariable(ApiTokenEnvironmentVariable);
        var readerPath = Environment.GetEnvironmentVariable(ReaderPathEnvironmentVariable);

        if (!string.IsNullOrWhiteSpace(backendUrl))
        {
            diagnostics.Add($"后端地址被环境变量 {BackendBaseUrlEnvironmentVariable} 覆盖。");
        }

        if (!string.IsNullOrWhiteSpace(apiToken))
        {
            diagnostics.Add($"后端 Token 被环境变量 {ApiTokenEnvironmentVariable} 覆盖。");
        }

        if (!string.IsNullOrWhiteSpace(readerPath))
        {
            diagnostics.Add($"读取器路径被环境变量 {ReaderPathEnvironmentVariable} 覆盖。");
        }

        return new AgentConfig
        {
            ReaderPath = string.IsNullOrWhiteSpace(readerPath) ? config.ReaderPath : readerPath.Trim(),
            ScannerPath = config.ScannerPath,
            ProbeArguments = config.ProbeArguments,
            ScanArgumentsTemplate = config.ScanArgumentsTemplate,
            TimeoutSeconds = config.TimeoutSeconds,
            BackendBaseUrl = string.IsNullOrWhiteSpace(backendUrl) ? config.BackendBaseUrl : backendUrl.Trim(),
            ApiToken = string.IsNullOrWhiteSpace(apiToken) ? config.ApiToken : apiToken.Trim(),
            SaveName = config.SaveName,
            QueueDirectory = config.QueueDirectory,
        };
    }

    private static string ResolveReaderPath(AgentConfig config, string baseDirectory, List<string> diagnostics)
    {
        var candidates = new List<string>();
        var fromEnvironment = Environment.GetEnvironmentVariable(ReaderPathEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(fromEnvironment))
        {
            candidates.Add(fromEnvironment.Trim());
        }

        if (!string.IsNullOrWhiteSpace(config.ReaderPath))
        {
            candidates.Add(config.ReaderPath.Trim());
        }

        candidates.Add(Path.Combine(baseDirectory, "ScoutMind.LiveReader.exe"));
        candidates.Add(Path.Combine(baseDirectory, "ScoutMind.LiveReader.dll"));

        foreach (var candidate in candidates)
        {
            string fullPath;
            try
            {
                fullPath = Path.GetFullPath(candidate);
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
            {
                diagnostics.Add($"读取器候选路径非法（{candidate}）：{ex.Message}");
                continue;
            }

            if (File.Exists(fullPath))
            {
                return fullPath;
            }
        }

        diagnostics.Add("未找到读取器：请把 ScoutMind.LiveReader.exe 放在代理同目录，或在 agent.json 中填写 readerPath。");
        return string.Empty;
    }

    private static string ResolveQueueDirectory(AgentConfig config, string baseDirectory)
    {
        if (string.IsNullOrWhiteSpace(config.QueueDirectory))
        {
            return Path.Combine(baseDirectory, "queue");
        }

        var candidate = config.QueueDirectory.Trim();
        return Path.IsPathFullyQualified(candidate) ? candidate : Path.Combine(baseDirectory, candidate);
    }
}
