using System.Diagnostics;
using FMSuperScout;
using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Engine;

/// <summary>一次上游内存读取的结果：dump 文件路径与内容。</summary>
/// <param name="DumpPath">上游写出的 dump.json 路径。</param>
/// <param name="Json">dump 内容。</param>
/// <param name="Diagnostics">读取过程中的诊断。</param>
public sealed record UpstreamDump(string DumpPath, string Json, IReadOnlyList<string> Diagnostics);

/// <summary>上游内存读取的抽象，便于在没有真实游戏的机器上测试包装层。</summary>
public interface IUpstreamDumpProvider
{
    /// <summary>读取一次内存并返回 dump。</summary>
    /// <param name="workingDirectory">写 dump 的目录（会被清空/复用）。</param>
    /// <param name="timeout">超时。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>dump；失败时抛出 <see cref="UpstreamReadException"/>。</returns>
    Task<UpstreamDump> ReadAsync(string workingDirectory, TimeSpan timeout, CancellationToken cancellationToken);
}

/// <summary>上游读取失败（进程打不开、超时、dump 缺失等）。</summary>
public sealed class UpstreamReadException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="message">中文说明。</param>
    public UpstreamReadException(string message)
        : base(message)
    {
    }
}

/// <summary>
/// 调用上游 FMSuperScout 内核读一次内存：<c>Dumper.TryDump</c> 写 dump.json，再读回。
/// 只读：上游通过 ReadProcessMemory 读取，从不写入游戏进程（见上游 MemScan）。
/// </summary>
public sealed class FMSuperScoutDumpProvider : IUpstreamDumpProvider
{
    /// <inheritdoc />
    public async Task<UpstreamDump> ReadAsync(string workingDirectory, TimeSpan timeout, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(workingDirectory);
        Directory.CreateDirectory(workingDirectory);
        foreach (var stale in Directory.EnumerateFiles(workingDirectory, "dump*.json"))
        {
            TryDelete(stale);
        }

        var diagnostics = new List<string>();
        var previousOutDir = Environment.GetEnvironmentVariable("SCOUTMIND_FMREADER_OUTDIR");
        var previousInfo = Host.Info;
        var previousWarn = Host.Warn;
        var previousError = Host.Error;
        var log = new List<string>();

        Environment.SetEnvironmentVariable("SCOUTMIND_FMREADER_OUTDIR", workingDirectory);
        Host.Info = line => log.Add(line);
        Host.Warn = line => log.Add(line);
        Host.Error = line => log.Add(line);
        Host.Kind = "scoutmind-scanner";
        Host.Version = ReaderIdentity.Version;

        var stopwatch = Stopwatch.StartNew();
        try
        {
            var completed = await Task.Run(
                () =>
                {
                    using var game = FmProcessBridge.OpenSelected();
                    return Dumper.TryDump(game);
                },
                cancellationToken).ConfigureAwait(false);

            if (!completed)
            {
                throw new UpstreamReadException(
                    "上游内核拒绝了本次读取（可能已有另一个扫描在进行，或进程无法打开）。");
            }

            var dumpPath = Path.Combine(workingDirectory, "dump.json");
            if (!File.Exists(dumpPath))
            {
                throw new UpstreamReadException($"上游没有写出 {dumpPath}；可能是布局不匹配导致解析中止。");
            }

            var json = await File.ReadAllTextAsync(dumpPath, cancellationToken).ConfigureAwait(false);
            if (json.Length < 64)
            {
                throw new UpstreamReadException("上游写出的 dump 为空或过短，视为读取失败。");
            }

            diagnostics.Add($"上游读取耗时 {stopwatch.ElapsedMilliseconds} ms，dump {new FileInfo(dumpPath).Length} 字节。");
            diagnostics.AddRange(log.TakeLast(20));
            return new UpstreamDump(dumpPath, json, diagnostics);
        }
        finally
        {
            Environment.SetEnvironmentVariable("SCOUTMIND_FMREADER_OUTDIR", previousOutDir);
            Host.Info = previousInfo;
            Host.Warn = previousWarn;
            Host.Error = previousError;
            Dumper.ReleaseScan();
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 上一个 dump 删不掉不影响本次读取：TryDump 会覆盖写。
        }
    }
}

/// <summary>读取器身份（版本号），写入 dump 元数据与协议报文。</summary>
public static class ReaderIdentity
{
    /// <summary>读取器/引擎版本。</summary>
    public static string Version { get; } =
        typeof(ReaderIdentity).Assembly.GetName().Version?.ToString(3) ?? "0.1.0";
}

/// <summary>把上游 <c>GameProcess</c> 与进程定位桥接起来（上游类型是 internal，必须同程序集）。</summary>
internal static class FmProcessBridge
{
    /// <summary>打开定位到的 fm.exe；未运行时抛 <see cref="UpstreamReadException"/>。</summary>
    /// <returns>可用的游戏进程句柄。</returns>
    internal static GameProcess OpenSelected()
    {
        var location = new FmProcessLocator().Locate();
        if (location.ProcessId is null)
        {
            throw new UpstreamReadException("没有找到正在运行且带 fm_Data 的 fm.exe。请先启动 FM27 并加载存档。");
        }

        Process process;
        try
        {
            process = Process.GetProcessById(location.ProcessId.Value);
        }
        catch (ArgumentException)
        {
            throw new UpstreamReadException($"进程 {location.ProcessId} 已退出。");
        }

        try
        {
            return GameProcess.Open(process);
        }
        catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 5)
        {
            throw new UpstreamReadException(
                "无法打开 fm.exe（访问被拒绝）：FM27 可能以管理员身份运行。请用普通权限启动 FM27，或以同样权限运行读取器。");
        }
    }
}

/// <summary>
/// 基于 FMSuperScout 内核的只读扫描引擎。
///
/// 流程：定位进程 → 版本闸门（清单里只有 <c>verified</c> 才放行）→ 上游读取 → 协议映射。
/// 任何一步失败都返回失败结果，绝不回落到演示数据。
/// </summary>
public sealed class FMSuperScoutMemoryEngine : IFmScanEngine
{
    private const string DefaultAppId = "4530370";

    private readonly IFmProcessLocator _locator;
    private readonly VersionGate _gate;
    private readonly IUpstreamDumpProvider _dumpProvider;
    private readonly UpstreamDumpMapper _mapper;
    private readonly Func<GameIdentity, string?> _buildResolver;
    private readonly string _workingRoot;

    /// <summary>创建引擎。</summary>
    /// <param name="locator">进程定位器。</param>
    /// <param name="gate">版本闸门。</param>
    /// <param name="dumpProvider">上游读取实现。</param>
    /// <param name="mapper">协议映射。</param>
    /// <param name="workingRoot">临时目录根；默认在 <c>%TEMP%\scoutmind\fmreader</c>。</param>
    /// <param name="buildResolver">构建号解析（可注入，测试用）。</param>
    public FMSuperScoutMemoryEngine(
        IFmProcessLocator? locator = null,
        VersionGate? gate = null,
        IUpstreamDumpProvider? dumpProvider = null,
        UpstreamDumpMapper? mapper = null,
        string? workingRoot = null,
        Func<GameIdentity, string?>? buildResolver = null)
    {
        _locator = locator ?? new FmProcessLocator();
        _gate = gate ?? new VersionGate();
        _dumpProvider = dumpProvider ?? new FMSuperScoutDumpProvider();
        _mapper = mapper ?? new UpstreamDumpMapper();
        _workingRoot = workingRoot ?? Path.Combine(Path.GetTempPath(), "scoutmind", "fmreader");
        _buildResolver = buildResolver ?? SteamBuildResolver.Resolve;
    }

    /// <inheritdoc />
    public string Version => ReaderIdentity.Version;

    /// <inheritdoc />
    public Task<FmEngineStatus> GetStatusAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var location = _locator.Locate();
        var diagnostics = new List<string>(location.Diagnostics);
        // 游戏没启动时也要能判断版本：从 Steam 库目录反查安装目录，而不是直接放弃。
        var installDirectory = location.InstallDirectory;
        if (installDirectory is null)
        {
            installDirectory = SteamBuildResolver.FindInstallDirectory();
            if (installDirectory is not null)
            {
                diagnostics.Add($"进程未运行，但按 Steam 库定位到安装目录：{installDirectory}。");
            }
        }

        var (pluginPath, pluginVersion) = FmProcessLocator.ReadPlugin(installDirectory);
        var appId = FmProcessLocator.ReadAppId(installDirectory);
        var identity = new GameIdentity(Version: null, Build: null, AppId: appId);
        var build = _buildResolver(identity);
        var gate = _gate.Evaluate(appId, build, pluginVersion);
        diagnostics.Add(gate.Message);

        return Task.FromResult(new FmEngineStatus(
            ProcessId: location.ProcessId,
            ProcessPath: location.ProcessPath,
            InstallDirectory: installDirectory,
            AppId: appId,
            Build: build,
            PluginPath: pluginPath,
            PluginVersion: pluginVersion,
            AccessDenied: location.ProcessId is null && location.Diagnostics.Any(text => text.Contains("权限", StringComparison.Ordinal)),
            Diagnostics: diagnostics,
            Gate: gate,
            EngineVersion: Version));
    }

    /// <inheritdoc />
    public async Task<FmProbeResult> ProbeAsync(CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
        if (status.Gate is null || !status.Gate.AllowScan)
        {
            return new FmProbeResult(
                false,
                status.Gate?.Message ?? "版本闸门未给出结论，拒绝读取。",
                status,
                stopwatch.ElapsedMilliseconds);
        }

        if (status.ProcessId is null)
        {
            return new FmProbeResult(
                false,
                "FM27 未运行：请启动游戏并加载存档后再 probe。",
                status,
                stopwatch.ElapsedMilliseconds);
        }

        // 版本放行后仍要确认进程可打开：管理员权限、反作弊保护都会让读取失败。
        try
        {
            using var game = FmProcessBridge.OpenSelected();
            _ = game.Process.Id;
        }
        catch (UpstreamReadException ex)
        {
            return new FmProbeResult(false, ex.Message, status, stopwatch.ElapsedMilliseconds);
        }

        return new FmProbeResult(true, null, status, stopwatch.ElapsedMilliseconds);
    }

    /// <inheritdoc />
    public async Task<FmScanResult> ScanAsync(CancellationToken cancellationToken)
    {
        var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
        if (status.Gate is null || !status.Gate.AllowScan)
        {
            return Failed(status, status.Gate?.Message ?? "版本闸门未放行，拒绝扫描。");
        }

        if (status.ProcessId is null)
        {
            return Failed(status, "FM27 未运行：请启动游戏并加载存档。");
        }

        var workingDirectory = Path.Combine(_workingRoot, DateTimeOffset.UtcNow.ToString("yyyyMMdd-HHmmss-fff"));
        var warnings = new List<string>();
        UpstreamDump dump;
        try
        {
            dump = await _dumpProvider.ReadAsync(workingDirectory, TimeSpan.FromMinutes(10), cancellationToken)
                .ConfigureAwait(false);
        }
        catch (UpstreamReadException ex)
        {
            return Failed(status, ex.Message);
        }
        catch (OperationCanceledException)
        {
            return Failed(status, "扫描被取消。");
        }

        warnings.AddRange(dump.Diagnostics);
        var identity = new GameIdentity(
            Version: ReadDumpGameVersion(dump.Json) ?? null,
            Build: status.Build,
            AppId: status.AppId);

        MappedPayload mapped;
        try
        {
            mapped = _mapper.Map(dump.Json, identity, Version);
        }
        catch (System.Text.Json.JsonException ex)
        {
            return Failed(status, $"上游 dump 不是合法 JSON：{ex.Message}");
        }

        var gateNote = status.Gate.Message;
        var allWarnings = new List<string> { $"版本闸门：{gateNote}" };
        allWarnings.AddRange(mapped.Warnings);
        allWarnings.AddRange(warnings);

        var payloadJson = InjectWarnings(mapped.Payload, allWarnings);
        return new FmScanResult(
            PayloadJson: payloadJson,
            Players: mapped.Players,
            Clubs: mapped.Clubs,
            Transfers: 0,
            Coverage: mapped.Coverage,
            Warnings: allWarnings,
            Status: status,
            FailureReason: null,
            RawDumpPath: dump.DumpPath);
    }

    private static FmScanResult Failed(FmEngineStatus status, string reason) =>
        new(
            PayloadJson: null,
            Players: 0,
            Clubs: 0,
            Transfers: 0,
            Coverage: new Dictionary<string, bool>(StringComparer.Ordinal),
            Warnings: status.Diagnostics,
            Status: status,
            FailureReason: reason,
            RawDumpPath: null);

    private static string? ReadDumpGameVersion(string dumpJson)
    {
        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(dumpJson);
            if (document.RootElement.TryGetProperty("meta", out var meta)
                && meta.TryGetProperty("gameVersion", out var version)
                && version.ValueKind == System.Text.Json.JsonValueKind.String)
            {
                return version.GetString();
            }
        }
        catch (System.Text.Json.JsonException)
        {
            return null;
        }

        return null;
    }

    private static string InjectWarnings(string payloadJson, IReadOnlyList<string> warnings)
    {
        var node = System.Text.Json.Nodes.JsonNode.Parse(payloadJson) as System.Text.Json.Nodes.JsonObject;
        if (node is null)
        {
            return payloadJson;
        }

        var array = new System.Text.Json.Nodes.JsonArray();
        foreach (var warning in warnings.Distinct(StringComparer.Ordinal))
        {
            array.Add(warning);
        }

        node["warnings"] = array;
        return node.ToJsonString();
    }
}

/// <summary>从 Steam 的 appmanifest 读取构建号；读不到时返回 <c>null</c>（不猜）。</summary>
public static partial class SteamBuildResolver
{
    /// <summary>解析构建号。</summary>
    /// <param name="identity">已知身份（AppId 必须存在）。</param>
    /// <returns>构建号或 <c>null</c>。</returns>
    public static string? Resolve(GameIdentity identity)
    {
        if (string.IsNullOrWhiteSpace(identity.AppId))
        {
            return null;
        }

        foreach (var root in SteamLibraryRoots())
        {
            var manifest = Path.Combine(root, "steamapps", $"appmanifest_{identity.AppId}.acf");
            var build = ReadBuildId(manifest);
            if (!string.IsNullOrWhiteSpace(build))
            {
                return build;
            }
        }

        return null;
    }

    /// <summary>按 Steam 库目录查找 FM27 安装目录（不依赖游戏是否在运行）。</summary>
    /// <returns>安装目录或 <c>null</c>。</returns>
    public static string? FindInstallDirectory()
    {
        foreach (var library in SteamLibraryRoots())
        {
            var candidate = Path.Combine(library, "steamapps", "common", "Football Manager 27");
            if (Directory.Exists(Path.Combine(candidate, "fm_Data")))
            {
                return candidate;
            }
        }

        return null;
    }

    private static IEnumerable<string> SteamLibraryRoots()
    {
        var roots = new List<string>();
        var fromRegistry = ReadSteamPathFromRegistry();
        if (!string.IsNullOrWhiteSpace(fromRegistry))
        {
            roots.Add(fromRegistry);
        }

        roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam"));
        roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Steam"));

        var libraries = new List<string>();
        foreach (var root in roots.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            libraries.Add(root);
            libraries.AddRange(ReadLibraryFolders(root));
        }

        return libraries.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
    }

    /// <summary>读取 steamapps/libraryfolders.vdf，返回所有库目录（Steam 可能装在别的盘）。</summary>
    /// <param name="steamRoot">Steam 安装根目录。</param>
    /// <returns>库目录列表。</returns>
    private static IEnumerable<string> ReadLibraryFolders(string steamRoot)
    {
        var vdf = Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf");
        if (!File.Exists(vdf))
        {
            return Array.Empty<string>();
        }

        var result = new List<string>();
        try
        {
            foreach (var line in File.ReadLines(vdf))
            {
                var match = LibraryPathPattern().Match(line);
                if (match.Success)
                {
                    var path = match.Groups[1].Value.Replace(@"\\", @"\", StringComparison.Ordinal);
                    if (Directory.Exists(path))
                    {
                        result.Add(path);
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return result;
        }

        return result;
    }
    private static string? ReadSteamPathFromRegistry()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam");
            return key?.GetValue("SteamPath") as string;
        }
        catch (Exception ex) when (ex is System.Security.SecurityException or UnauthorizedAccessException or IOException)
        {
            return null;
        }
    }

    [System.Text.RegularExpressions.GeneratedRegex("\"path\"\\s+\"([^\"]+)\"", System.Text.RegularExpressions.RegexOptions.CultureInvariant)]
    private static partial System.Text.RegularExpressions.Regex LibraryPathPattern();

    private static string? ReadBuildId(string manifestPath)
    {
        try
        {
            if (!File.Exists(manifestPath))
            {
                return null;
            }

            foreach (var line in File.ReadLines(manifestPath))
            {
                var trimmed = line.Trim();
                if (!trimmed.StartsWith("\"buildid\"", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var parts = trimmed.Split('"', StringSplitOptions.RemoveEmptyEntries);
                var value = parts.LastOrDefault()?.Trim();
                return string.IsNullOrWhiteSpace(value) ? null : value;
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }

        return null;
    }
}
