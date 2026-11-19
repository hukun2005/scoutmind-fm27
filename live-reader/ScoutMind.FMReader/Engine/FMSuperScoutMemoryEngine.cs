using System.Diagnostics;
using FMSuperScout;
using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
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
/// 流程：识别构建 → 解析布局（构建未登记即拒绝）→ 诊断探测（结构自洽性）→ 注册表判决 → （全部 Verified 才）上游读取 → 协议映射。
/// 任何一步失败都返回失败结果，绝不回落到演示数据。
/// </summary>
public sealed class FMSuperScoutMemoryEngine : IFmScanEngine
{
    private readonly GameBuildDetector _detector;
    private readonly VersionGate _gate;
    private readonly LayoutResolver _layouts;
    private readonly CompatibilityRegistry _registry;
    private readonly IUpstreamDumpProvider _dumpProvider;
    private readonly UpstreamDumpMapper _mapper;
    private readonly string _workingRoot;
    private readonly Func<GameIdentity, string?> _buildResolver;
    private readonly IProbeEnvironment _probeEnvironment;

    /// <summary>创建引擎。</summary>
    /// <param name="locator">进程定位器。</param>
    /// <param name="gate">版本闸门（构建允许清单）。</param>
    /// <param name="layouts">布局解析器。</param>
    /// <param name="registry">兼容性注册表。</param>
    /// <param name="dumpProvider">上游读取实现。</param>
    /// <param name="mapper">协议映射。</param>
    /// <param name="workingRoot">临时目录根。</param>
    /// <param name="buildResolver">构建号解析（测试用）。</param>
    public FMSuperScoutMemoryEngine(
        IFmProcessLocator? locator = null,
        VersionGate? gate = null,
        LayoutResolver? layouts = null,
        CompatibilityRegistry? registry = null,
        IUpstreamDumpProvider? dumpProvider = null,
        UpstreamDumpMapper? mapper = null,
        string? workingRoot = null,
        Func<GameIdentity, string?>? buildResolver = null,
        IProbeEnvironment? probeEnvironment = null)
    {
        _probeEnvironment = probeEnvironment ?? new WinMemoryEnvironment();
        _buildResolver = buildResolver ?? SteamBuildResolver.Resolve;
        _detector = new GameBuildDetector(locator, _buildResolver);
        _gate = gate ?? new VersionGate();
        _layouts = layouts ?? new LayoutResolver();
        _registry = registry ?? new CompatibilityRegistry();
        _dumpProvider = dumpProvider ?? new FMSuperScoutDumpProvider();
        _mapper = mapper ?? new UpstreamDumpMapper();
        _workingRoot = workingRoot ?? Path.Combine(Path.GetTempPath(), "scoutmind", "fmreader");
    }

    /// <inheritdoc />
    public string Version => ReaderIdentity.Version;

    /// <inheritdoc />
    public Task<FmEngineStatus> GetStatusAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var detected = _detector.Detect();
        var diagnostics = new List<string>(detected.Diagnostics);
        var gate = _gate.Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        diagnostics.Add(gate.Message);

        var layout = _layouts.Resolve(detected.Build, detected.PluginVersion);
        if (layout is null)
        {
            diagnostics.Add(detected.Build is null
                ? "没有构建号，无法解析布局。"
                : $"构建 {detected.Build} 未在 LayoutResolver 中登记。");
        }
        else
        {
            _registry.Apply(detected.Build, layout);
            diagnostics.Add($"布局 {layout.Name}（状态 {layout.Status}）。");
        }

        return Task.FromResult(new FmEngineStatus(
            ProcessId: detected.ProcessId,
            ProcessPath: detected.ProcessPath,
            InstallDirectory: detected.InstallDirectory,
            AppId: detected.AppId,
            Build: detected.Build,
            PluginPath: detected.PluginPath,
            PluginVersion: detected.PluginVersion,
            AccessDenied: detected.ProcessId is null && detected.Diagnostics.Any(text => text.Contains("权限", StringComparison.Ordinal)),
            Diagnostics: diagnostics,
            Gate: gate,
            EngineVersion: Version));
    }

    /// <inheritdoc />
    public async Task<FmProbeResult> ProbeAsync(CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        var report = await DiagnoseAsync(cancellationToken).ConfigureAwait(false);
        var passed = report.Overall == OverallStatus.Verified;
        var reason = passed
            ? null
            : string.Join("；", new[]
            {
                report.Summary,
                report.Probes.FirstOrDefault(probe => probe.Status == ProbeStatus.Failed) is { } failed
                    ? $"探测 {failed.Name} 失败：{failed.Note ?? failed.Checks.FirstOrDefault(item => item.Status == CheckStatus.Failed)?.Detail}"
                    : null,
            }.Where(item => !string.IsNullOrWhiteSpace(item)));

        var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
        return new FmProbeResult(passed, reason, status, stopwatch.ElapsedMilliseconds, report);
    }

    /// <inheritdoc />
    public Task<DiagnosticReport> DiagnoseAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var detected = _detector.Detect();
        var layout = _layouts.Resolve(detected.Build, detected.PluginVersion);
        if (layout is not null)
        {
            _registry.Apply(detected.Build, layout);
        }

        var diagnostics = new List<string>(detected.Diagnostics);
        var limitations = new List<string>
        {
            "结构化探测只能发现明显错位（范围、指针、关系），不能证明数值与游戏内一致。",
            "租借与所有权关系不在内存布局中，只能来自阵容 CSV。",
            "转会记录没有 vtable，只能按形状识别；本次未做全量枚举。",
        };

        if (detected.ProcessId is null || layout is null)
        {
            var reason = layout is null
                ? detected.Build is null ? "没有读到构建号" : $"构建 {detected.Build} 未登记布局"
                : "FM27 未运行";
            diagnostics.Add($"{reason}：无法执行内存探测。");
            var empty = ReportBuilder.Build(
                Version,
                detected.Build,
                detected.PluginVersion,
                detected.AppId,
                layout,
                Array.Empty<ProbeOutcome>(),
                diagnostics,
                limitations);
            return Task.FromResult(empty with { Summary = $"{reason}：禁止扫描。" });
        }

        try
        {
            var memory = _probeEnvironment.Open();
            var locator = _probeEnvironment.CreateLocator(memory);
            var probes = new ObjectProbes(memory, layout);
            var located = locator.FindPlayers(layout, 96, TimeSpan.FromSeconds(25));
            // 女子数据库的对象结构未单独核对：分开统计，不让它污染男子样本的比率，也不假装它已通过。
            var (men, women) = probes.SplitByGender(located);
            var players = men.Count > 0 ? men : located;
            var clubs = locator.FindClubs(layout, 16, TimeSpan.FromSeconds(10)).ToList();
            // 俱乐部对象不一定能被 vtable 扫描命中；从球员的合同链上补一批。
            foreach (var (club, _) in probes.DeriveClubsFromPlayers(players))
            {
                if (clubs.All(item => item.Address != club))
                {
                    clubs.Add(new LocatedObject(club, 0, 0, 0));
                }
            }
            var outcomes = new List<ProbeOutcome>
            {
                probes.ProbePlayers(players),
                probes.ProbeClubs(clubs),
                probes.ProbeTeams(players),
                probes.ProbeContracts(players),
                probes.ProbeLoans(),
                probes.ProbeTransfers(Array.Empty<ulong>()),
                probes.ProbeIntegrity(players, clubs),
                // 字段级：属性三组 + 位置 + 国籍 + 球队关系（注册俱乐部/当前球队/层级）
                probes.ProbeAttributeGroup(players, "attributes.technical", FieldSpecs.Technical),
                probes.ProbeAttributeGroup(players, "attributes.mental", FieldSpecs.Mental),
                probes.ProbeAttributeGroup(players, "attributes.physical", FieldSpecs.Physical),
                probes.ProbePositions(players),
                probes.ProbeNationality(players),
                probes.ProbeTeamRelations(players),
                new ProbeOutcome("women_database", ProbeStatus.Inconclusive, women.Count,
                    new[]
                    {
                        new FieldCheck("women.objects", women.Count > 0 ? CheckStatus.Inconclusive : CheckStatus.Passed,
                            $"定位到女子数据库对象 {women.Count} 个（男子样本 {players.Count} 个）"),
                    },
                    "女子数据库结构与男子不同（合同/球队链在 25% 样本上读不通）：未验证，扫描前必须单独核对。"),
            };

            diagnostics.Add($"定位到球员对象 {players.Count} 个、俱乐部对象 {clubs.Count} 个。");
            var report = ReportBuilder.Build(
                Version,
                detected.Build,
                detected.PluginVersion,
                detected.AppId,
                layout,
                outcomes,
                diagnostics,
                limitations,
                FieldSpecs.Build(layout));
            return Task.FromResult(report);
        }
        catch (MemoryUnreadableException)
        {
            diagnostics.Add("无法打开 fm.exe 读取内存（权限不足或进程已退出）。");
            var report = ReportBuilder.Build(
                Version,
                detected.Build,
                detected.PluginVersion,
                detected.AppId,
                layout,
                Array.Empty<ProbeOutcome>(),
                diagnostics,
                limitations);
            return Task.FromResult(report with { Summary = "无法读取进程内存：禁止扫描。" });
        }
    }

    /// <inheritdoc />
    public async Task<FmScanResult> ScanAsync(CancellationToken cancellationToken)
    {
        var status = await GetStatusAsync(cancellationToken).ConfigureAwait(false);
        if (status.Gate is null || !status.Gate.AllowScan)
        {
            return Failed(status, status.Gate?.Message ?? "版本闸门未放行，拒绝扫描。");
        }

        if (!_registry.AllowsScan(status.Build))
        {
            var entry = _registry.For(status.Build);
            return Failed(status, entry is null
                ? $"构建 {status.Build} 未在兼容性注册表中登记：拒绝扫描。"
                : $"构建 {status.Build} 的注册状态为 {entry.Status}：拒绝扫描（需要 verified）。");
        }

        var layout = _layouts.Resolve(status.Build, status.PluginVersion);
        if (layout is null || layout.Status != FieldStatus.Verified)
        {
            return Failed(status, $"布局 {layout?.Name ?? "(未解析)"} 尚未通过真实核对：拒绝扫描。");
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
            Version: ReadDumpGameVersion(dump.Json),
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

        var allWarnings = new List<string> { $"版本闸门：{status.Gate.Message}", $"布局：{layout.Name}（已验证）" };
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

    /// <summary>按 Steam 库目录查找 FM27 安装目录。</summary>
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

    /// <summary>Steam 库根目录（诊断用）。</summary>
    /// <returns>库根目录列表。</returns>
    public static IReadOnlyList<string> SteamLibraryRootsPublic() => SteamLibraryRoots().ToList();

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

        // 同一库目录可能以 "d:/steam" 与 "D:\steam" 两种写法出现：先规范化再去重。
        return libraries
            .Select(path =>
            {
                try
                {
                    return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
                }
                catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
                {
                    return path;
                }
            })
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

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
