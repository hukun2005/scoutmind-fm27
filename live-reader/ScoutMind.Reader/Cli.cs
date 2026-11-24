using System.Globalization;
using System.Text.Json;
using ScoutMind.Contracts;
using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Engine;

namespace ScoutMind.Reader;

/// <summary>
/// 命令行入口逻辑。所有输出写入注入的 <see cref="TextWriter"/>，便于测试；
/// <c>--json</c> 模式下 stdout 只输出一个 JSON 对象，说明性文字被抑制。
/// </summary>
public sealed class Cli
{
    private readonly TextWriter _stdout;
    private readonly TextWriter _stderr;
    private readonly string _baseDirectory;
    private readonly ReaderPipeline? _pipeline;

    /// <summary>创建命令行。</summary>
    /// <param name="stdout">标准输出。</param>
    /// <param name="stderr">标准错误。</param>
    /// <param name="baseDirectory">可执行文件所在目录，用于定位 compatibility.json 与 scanner.json。</param>
    /// <param name="pipeline">可注入的检测编排；为 <c>null</c> 时按目录中的兼容清单自行构建。</param>
    public Cli(TextWriter stdout, TextWriter stderr, string baseDirectory, ReaderPipeline? pipeline = null)
    {
        _stdout = stdout ?? throw new ArgumentNullException(nameof(stdout));
        _stderr = stderr ?? throw new ArgumentNullException(nameof(stderr));
        _baseDirectory = baseDirectory;
        _pipeline = pipeline;
    }

    /// <summary>把状态映射为进程退出码。</summary>
    /// <param name="state">状态。</param>
    /// <returns>退出码：0 成功、2 未找到、3 不兼容/未知、4 probe 失败。</returns>
    public static int MapState(ReaderState state) => state switch
    {
        ReaderState.NotFound => ExitCodes.NotFound,
        ReaderState.Unsupported or ReaderState.Unknown => ExitCodes.Incompatible,
        ReaderState.ProbeFailed => ExitCodes.ProbeFailed,
        _ => ExitCodes.Success,
    };

    /// <summary>执行命令行。</summary>
    /// <param name="args">进程参数（不含程序名）。</param>
    /// <param name="cancellationToken">取消令牌（Ctrl+C）。</param>
    /// <returns>进程退出码。</returns>
    public async Task<int> RunAsync(string[] args, CancellationToken cancellationToken)
    {
        var parsed = CliCommandParser.Parse(args);
        if (!parsed.Ok)
        {
            WriteUsageError(parsed.Error!);
            return ExitCodes.UsageError;
        }

        var options = parsed.Options!;
        switch (options.Command)
        {
            case CliCommand.Help:
                WriteUsage(_stdout);
                return ExitCodes.Success;

            case CliCommand.Status:
                return RunStatus(options);

            case CliCommand.Probe:
                return await RunProbeAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.Date:
                return await RunDateAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.DateDiscovery:
                return await RunDateDiscoveryAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.PointerScan:
                return await RunPointerScanAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.DateLocate:
                return await RunDateLocateAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.StaticDateScan:
                return await RunStaticDateScanAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.DateRead:
                return RunDateRead(options);

            case CliCommand.ModuleInfo:
                return RunModuleInfo(options);

            case CliCommand.Scan:
                return await RunScanAsync(options, cancellationToken).ConfigureAwait(false);

            case CliCommand.CompatibilityList:
                return RunCompatibilityList(options);

            default:
                WriteUsageError("未知子命令。");
                return ExitCodes.UsageError;
        }
    }

    private async Task<int> RunDateAsync(CliOptions options, CancellationToken cancellationToken)
    {
        var probe = new FmDateProbe();
        var result = await probe.ProbeAsync(cancellationToken).ConfigureAwait(false);
        if (options.Json)
        {
            WriteJson(result);
        }
        else
        {
            _stdout.WriteLine($"日期探测：{result.State}");
            if (result.GameDate is not null) _stdout.WriteLine($"游戏日期：{result.GameDate}");
            foreach (var line in result.Diagnostics) _stdout.WriteLine(line);
        }

        return result.State switch
        {
            FmDateProbeState.DateDetected => ExitCodes.Success,
            FmDateProbeState.GameNotRunning => ExitCodes.NotFound,
            _ => ExitCodes.Incompatible,
        };
    }

    private async Task<int> RunDateDiscoveryAsync(CliOptions options, CancellationToken cancellationToken)
    {
        if (options.ExpectedDate is null)
        {
            WriteUsageError("date-discovery 需要 --expect <yyyy-MM-dd>。");
            return ExitCodes.UsageError;
        }

        var discovery = new FmDateDiscovery();
        var result = await discovery
            .DiscoverAsync(options.ExpectedDate.Value, options.MaxScanMb is { } megabytes ? megabytes * 1024L * 1024L : DateDiscovery.DefaultMaxBytes, cancellationToken)
            .ConfigureAwait(false);

        var document = new
        {
            build = result.Build,
            plugin_version = result.PluginVersion,
            app_id = result.AppId,
            layout = result.Layout,
            process_detected = result.ProcessDetected,
            expected_date = result.ExpectedDate,
            encoded_value = result.EncodedValue,
            candidate_count = result.Candidates.Count,
            candidates = result.Candidates.Select(item => new
            {
                candidate_id = item.Index,
                address = $"0x{item.Address:X}",
                region = $"0x{item.RegionStart:X}",
                raw_value = $"0x{item.RawValue:X8}",
                decode_rule = "year<<16|day_of_year",
                field_type = "u32",
                source = "date_discovery_scan",
            }),
            current_date = (string?)null,
            date_source = result.Candidates.Count > 0 ? "memory_candidate" : "unknown",
            verification_status = result.VerificationStatus,
            diagnostics = result.Diagnostics,
        };

        if (options.Json)
        {
            WriteJson(document);
        }
        else
        {
            _stdout.WriteLine($"日期候选发现：期望 {result.ExpectedDate}（编码 0x{result.EncodedValue:X8}）");
            _stdout.WriteLine($"进程：{result.Build ?? "(未检测)"} · 布局：{result.Layout ?? "(无)"} · 状态：{result.VerificationStatus}");
            _stdout.WriteLine($"候选数：{result.Candidates.Count}");
            foreach (var candidate in result.Candidates)
            {
                _stdout.WriteLine(
                    $"  #{candidate.Index} 0x{candidate.Address:X}（区域 0x{candidate.RegionStart:X}）");
            }

            foreach (var line in result.Diagnostics) _stdout.WriteLine(line);
        }

        return result.VerificationStatus switch
        {
            "game_not_running" => ExitCodes.NotFound,
            "unsupported_build" or "layout_not_verified" => ExitCodes.Incompatible,
            _ => ExitCodes.Success,
        };
    }

    private async Task<int> RunPointerScanAsync(CliOptions options, CancellationToken cancellationToken)
    {
        if (options.TargetAddress is null)
        {
            WriteUsageError("pointer-scan 需要 --target <0x地址>。");
            return ExitCodes.UsageError;
        }

        var scanner = new FmPointerScan();
        var window = options.WindowBytes ?? 0x1000;
        var maxBytes = options.MaxScanMb is { } megabytes
            ? megabytes * 1024L * 1024L
            : PointerScan.DefaultMaxBytes;
        var result = await scanner
            .ScanAsync(options.TargetAddress.Value, window, maxBytes, cancellationToken)
            .ConfigureAwait(false);

        var document = new
        {
            build = result.Build,
            plugin_version = result.PluginVersion,
            process_detected = result.ProcessDetected,
            target = $"0x{result.TargetStart:X}",
            target_end = $"0x{result.TargetEnd:X}",
            hit_count = result.Hits.Count,
            hits = result.Hits.Select(item => new
            {
                slot = $"0x{item.SlotAddress:X}",
                value = $"0x{item.Value:X}",
                in_module = item.InModule,
            }),
            status = result.Status,
            diagnostics = result.Diagnostics,
        };

        if (options.Json)
        {
            WriteJson(document);
        }
        else
        {
            _stdout.WriteLine($"指针扫描：0x{result.TargetStart:X} .. 0x{result.TargetEnd:X}　命中 {result.Hits.Count}");
            foreach (var hit in result.Hits.Take(32))
            {
                _stdout.WriteLine(
                    $"  slot 0x{hit.SlotAddress:X} -> 0x{hit.Value:X}{(hit.InModule ? "（模块内）" : string.Empty)}");
            }

            foreach (var line in result.Diagnostics) _stdout.WriteLine(line);
        }

        return result.Status switch
        {
            "game_not_running" => ExitCodes.NotFound,
            "unsupported_build" => ExitCodes.Incompatible,
            _ => ExitCodes.Success,
        };
    }
    private async Task<int> RunDateLocateAsync(CliOptions options, CancellationToken cancellationToken)
    {
        var locator = new FmWorldDateLocator();
        var maxBytes = options.MaxScanMb is { } megabytes
            ? megabytes * 1024L * 1024L
            : WorldDateLocator.DefaultMaxBytes;
        var result = await locator.LocateAsync(maxBytes, cancellationToken).ConfigureAwait(false);

        var document = new
        {
            build = result.Build,
            plugin_version = result.PluginVersion,
            process_detected = result.ProcessDetected,
            match_count = result.Matches.Count,
            matches = result.Matches.Select(item => new
            {
                date_address = $"0x{item.DateAddress:X}",
                base_address = $"0x{item.BaseAddress:X}",
                raw_date = $"0x{item.RawDate:X8}",
                date = item.Date,
                raw_reference = $"0x{item.RawReference:X8}",
                reference = item.Reference,
                date_field_offset = "0x44",
            }),
            status = result.Status,
            verification_status = result.Matches.Count == 0 ? "not_found" : "unverified_candidate",
            diagnostics = result.Diagnostics,
        };

        if (options.Json)
        {
            WriteJson(document);
        }
        else
        {
            _stdout.WriteLine($"世界日期定位：命中 {result.Matches.Count}");
            foreach (var match in result.Matches.Take(16))
            {
                _stdout.WriteLine(
                    $"  {match.Date}（参考 {match.Reference}）字段 0x{match.DateAddress:X} 基址 0x{match.BaseAddress:X}");
            }

            foreach (var line in result.Diagnostics) _stdout.WriteLine(line);
        }

        return result.Status switch
        {
            "game_not_running" => ExitCodes.NotFound,
            "unsupported_build" => ExitCodes.Incompatible,
            _ => ExitCodes.Success,
        };
    }
    private int RunModuleInfo(CliOptions options)
    {
        var detected = new ScoutMind.FMReader.Engine.GameBuildDetector().Detect();
        object document;
        var status = "ok";
        if (detected.ProcessId is null)
        {
            status = "game_not_running";
            document = new { process_detected = false, status, diagnostics = detected.Diagnostics };
        }
        else
        {
            try
            {
                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var bounds = memory.Bounds;
                document = new
                {
                    process_detected = true,
                    pid = detected.ProcessId,
                    build = detected.Build,
                    plugin_version = detected.PluginVersion,
                    app_id = detected.AppId,
                    game_plugin_base = $"0x{bounds.GpBase:X}",
                    game_plugin_end = $"0x{bounds.GpEnd:X}",
                    game_plugin_size = bounds.GpEnd > bounds.GpBase ? bounds.GpEnd - bounds.GpBase : 0,
                    game_assembly_base = $"0x{bounds.GaBase:X}",
                    game_assembly_end = $"0x{bounds.GaEnd:X}",
                    scan_region_count = bounds.ScanRegionCount,
                    plugin_path = bounds.PluginPath,
                    status,
                    diagnostics = detected.Diagnostics,
                };
            }
            catch (ScoutMind.FMReader.Probes.MemoryUnreadableException ex)
            {
                status = "unreadable";
                document = new { process_detected = true, status, error = ex.Message, diagnostics = detected.Diagnostics };
            }
        }

        if (options.Json)
        {
            WriteJson(document);
        }
        else
        {
            _stdout.WriteLine($"模块边界：{status}");
            if (document is not null)
            {
                _stdout.WriteLine(System.Text.Json.JsonSerializer.Serialize(document));
            }
        }

        return status switch
        {
            "game_not_running" => ExitCodes.NotFound,
            "unreadable" => ExitCodes.Incompatible,
            _ => ExitCodes.Success,
        };
    }
    private async Task<int> RunStaticDateScanAsync(CliOptions options, CancellationToken cancellationToken)
    {
        if (options.ExpectedDate is null)
        {
            WriteUsageError("static-date-scan 需要 --expect <yyyy-MM-dd>。");
            return ExitCodes.UsageError;
        }

        var scanner = new FmStaticDateScan();
        var maxBytes = options.MaxScanMb is { } megabytes
            ? megabytes * 1024L * 1024L
            : StaticDateScan.DefaultMaxBytes;
        var result = await scanner
            .ScanAsync(options.ExpectedDate.Value, options.MaxDepth ?? 2, maxBytes, cancellationToken)
            .ConfigureAwait(false);

        var document = new
        {
            build = result.Build,
            plugin_version = result.PluginVersion,
            process_detected = result.ProcessDetected,
            expected_date = options.ExpectedDate.Value.ToString("yyyy-MM-dd"),
            module_regions = result.ModuleRegions.Select(item => new
            {
                start = $"0x{item.Start:X}",
                size = item.Size,
            }),
            root_count = result.Roots.Count,
            roots = result.Roots.Select(item => new
            {
                slot = $"0x{item.Slot:X}",
                module_base = $"0x{item.ModuleBase:X}",
                rva = $"0x{item.Rva:X}",
                target = $"0x{item.Target:X}",
                hop = item.Hop,
                date_offset = $"0x{item.DateOffset:X}",
                date = item.Date,
            }),
            status = result.Status,
            diagnostics = result.Diagnostics,
        };

        if (options.Json)
        {
            WriteJson(document);
        }
        else
        {
            _stdout.WriteLine($"静态根扫描：{result.Status}，候选 {result.Roots.Count}");
            foreach (var region in result.ModuleRegions)
            {
                _stdout.WriteLine($"  模块 0x{region.Start:X} 大小 {region.Size:N0}");
            }

            foreach (var root in result.Roots.Take(20))
            {
                _stdout.WriteLine(
                    $"  RVA 0x{root.Rva:X}（{root.Hop} 跳，字段 +0x{root.DateOffset:X}）= {root.Date}");
            }

            foreach (var line in result.Diagnostics) _stdout.WriteLine(line);
        }

        return result.Status switch
        {
            "game_not_running" => ExitCodes.NotFound,
            "unsupported_build" or "no_modules" => ExitCodes.Incompatible,
            _ => ExitCodes.Success,
        };
    }
    private int RunDateRead(CliOptions options)
    {
        if (options.Rva is null || options.FieldOffset is null)
        {
            WriteUsageError("date-read 需要 --rva 与 --field。");
            return ExitCodes.UsageError;
        }

        var detected = new ScoutMind.FMReader.Engine.GameBuildDetector().Detect();
        if (detected.ProcessId is null)
        {
            WriteJson(new { process_detected = false, status = "game_not_running" });
            return ExitCodes.NotFound;
        }

        var gate = new ScoutMind.FMReader.Versioning.VersionGate()
            .Evaluate(detected.AppId, detected.Build, detected.PluginVersion);
        if (!gate.AllowScan)
        {
            WriteJson(new { process_detected = true, status = "unsupported_build", message = gate.Message });
            return ExitCodes.Incompatible;
        }

        try
        {
            using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
            var bounds = memory.Bounds;
            if (bounds.GpEnd <= bounds.GpBase)
            {
                WriteJson(new { process_detected = true, status = "no_modules" });
                return ExitCodes.Incompatible;
            }

            var slot = bounds.GpBase + options.Rva.Value;
            if (slot >= bounds.GpEnd)
            {
                WriteJson(new
                {
                    process_detected = true,
                    status = "rva_out_of_module",
                    module_base = $"0x{bounds.GpBase:X}",
                    module_end = $"0x{bounds.GpEnd:X}",
                    slot = $"0x{slot:X}",
                });
                return ExitCodes.Incompatible;
            }

            var target = memory.Pointer(slot);
            var raw = memory.UInt32(target + (ulong)options.FieldOffset.Value);
            var decoded = ScoutMind.FMReader.Discovery.DateDiscovery.Decode(raw);
            var document = new
            {
                process_detected = true,
                build = detected.Build,
                plugin_version = detected.PluginVersion,
                module_base = $"0x{bounds.GpBase:X}",
                rva = $"0x{options.Rva.Value:X}",
                slot = $"0x{slot:X}",
                target = $"0x{target:X}",
                field_offset = $"0x{options.FieldOffset.Value:X}",
                raw_value = $"0x{raw:X8}",
                date = decoded?.ToString("yyyy-MM-dd"),
                status = decoded is null ? "undecodable" : "ok",
            };

            if (options.Json)
            {
                WriteJson(document);
            }
            else
            {
                _stdout.WriteLine($"RVA 0x{options.Rva.Value:X} → {document.date ?? "(无法解码)"}（原始 0x{raw:X8}）");
            }

            return decoded is null ? ExitCodes.Incompatible : ExitCodes.Success;
        }
        catch (ScoutMind.FMReader.Probes.MemoryUnreadableException ex)
        {
            WriteJson(new { process_detected = true, status = "unreadable", message = ex.Message });
            return ExitCodes.Incompatible;
        }
    }
    private int RunStatus(CliOptions options)
    {
        var status = GetPipeline().Detect();
        if (options.Json)
        {
            WriteJson(status);
        }
        else
        {
            WriteStatusHuman(status);
        }

        return MapState(status.State);
    }

    private async Task<int> RunProbeAsync(CliOptions options, CancellationToken cancellationToken)
    {
        var status = GetPipeline().Detect();
        if (status.State != ReaderState.Compatible)
        {
            if (options.Json)
            {
                WriteJson(status);
            }
            else
            {
                WriteStatusHuman(status);
            }

            _stderr.WriteLine($"当前状态为 {status.State}，未执行 probe。");
            return RefusalExitCode(status.State);
        }

        var scannerConfig = ScannerConfigLoader.Load(_baseDirectory);
        var (backend, rationale) = ScanBackendFactory.Create(options.Engine, scannerConfig);
        if (!options.Json)
        {
            _stdout.WriteLine($"扫描后端    : {backend.Name}（{rationale}）");
        }

        ProbeResult probe;
        try
        {
            probe = await backend.ProbeAsync(ReaderState.Compatible, cancellationToken).ConfigureAwait(false);
        }
        catch (ScanRefusedException ex)
        {
            _stderr.WriteLine(ex.Message);
            return ExitCodes.Incompatible;
        }
        catch (ScannerConfigurationException ex)
        {
            _stderr.WriteLine($"配置错误：{ex.Message}");
            return ExitCodes.UsageError;
        }

        if (!options.Json)
        {
            WriteStatusHuman(status);
            WriteScanConfigHuman(scannerConfig);
        }

        if (!string.IsNullOrWhiteSpace(options.ReportPath))
        {
            try
            {
                var written = ProbeReportWriter.Write(
                    options.ReportPath,
                    ReaderInfo.Version,
                    probe,
                    backend.LastReport,
                    DateTimeOffset.UtcNow);
                _stderr.WriteLine($"结构化诊断报告已写入 {written}");
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
            {
                _stderr.WriteLine($"写入结构化诊断报告失败：{ex.Message}");
                return ExitCodes.UsageError;
            }
        }

        if (options.Json)
        {
            WriteJson(probe);
        }
        else
        {
            WriteProbeHuman(probe);
        }

        return probe.Passed ? ExitCodes.Success : ExitCodes.ProbeFailed;
    }

    private async Task<int> RunScanAsync(CliOptions options, CancellationToken cancellationToken)
    {
        var status = GetPipeline().Detect();
        if (status.State is not (ReaderState.Compatible or ReaderState.ProbePassed))
        {
            if (options.Json)
            {
                WriteJson(status);
            }
            else
            {
                WriteStatusHuman(status);
            }

            _stderr.WriteLine($"当前状态为 {status.State}，未执行扫描。");
            return RefusalExitCode(status.State);
        }

        var scannerConfig = ScannerConfigLoader.Load(_baseDirectory);
        var (backend, rationale) = ScanBackendFactory.Create(options.Engine, scannerConfig);
        if (!options.Json)
        {
            _stdout.WriteLine($"扫描后端    : {backend.Name}（{rationale}）");
        }

        try
        {
            backend.EnsureUsable();
        }
        catch (ScannerConfigurationException ex)
        {
            _stderr.WriteLine($"配置错误：{ex.Message}");
            return ExitCodes.UsageError;
        }

        if (!options.Json)
        {
            WriteStatusHuman(status);
            WriteScanConfigHuman(scannerConfig);
        }

        // A scan is only allowed after a probe has passed in this very run; the CLI never assumes
        // a previous run's probe still holds.
        if (status.State != ReaderState.ProbePassed)
        {
            if (!options.Json)
            {
                _stdout.WriteLine("正在执行 probe……");
            }

            ProbeResult probe;
            try
            {
                probe = await backend.ProbeAsync(ReaderState.Compatible, cancellationToken).ConfigureAwait(false);
            }
            catch (ScannerConfigurationException ex)
            {
                _stderr.WriteLine($"配置错误：{ex.Message}");
                return ExitCodes.UsageError;
            }

            if (!probe.Passed)
            {
                if (options.Json)
                {
                    WriteJson(probe);
                }
                else
                {
                    WriteProbeHuman(probe);
                }

                _stderr.WriteLine("probe 未通过，已拒绝扫描。");
                return ExitCodes.ProbeFailed;
            }

            if (!options.Json)
            {
                WriteProbeHuman(probe);
            }
        }

        var outputDirectory = string.IsNullOrWhiteSpace(options.OutputDirectory)
            ? Path.Combine(_baseDirectory, "scans")
            : options.OutputDirectory;
        var timeoutSeconds = options.TimeoutSeconds ?? scannerConfig.Config.TimeoutSeconds;

        ScanResult result;
        try
        {
            result = await backend
                .ScanAsync(
                    new ScanRequest(outputDirectory, timeoutSeconds, null),
                    ReaderState.ProbePassed,
                    status.Game,
                    cancellationToken)
                .ConfigureAwait(false);
        }
        catch (ScanRefusedException ex)
        {
            _stderr.WriteLine(ex.Message);
            return ExitCodes.Incompatible;
        }
        catch (ScannerConfigurationException ex)
        {
            _stderr.WriteLine($"配置错误：{ex.Message}");
            return ExitCodes.UsageError;
        }

        if (options.Json)
        {
            WriteJson(result);
        }
        else
        {
            WriteScanResultHuman(result);
        }

        return result.State == ReaderState.ScanCompleted ? ExitCodes.Success : ExitCodes.ScanFailed;
    }

    private int RunCompatibilityList(CliOptions options)
    {
        var manifestPath = ResolveManifestPath();
        CompatibilityManifest manifest;
        try
        {
            manifest = CompatibilityService.LoadManifest(manifestPath);
        }
        catch (CompatibilityManifestException ex)
        {
            _stderr.WriteLine($"兼容清单不可用：{ex.Message}");
            return ExitCodes.Incompatible;
        }

        if (options.Json)
        {
            WriteJson(manifest);
        }
        else
        {
            WriteManifestHuman(manifest, manifestPath);
        }

        return ExitCodes.Success;
    }

    private ReaderPipeline GetPipeline() => _pipeline ?? CreatePipeline();

    private ReaderPipeline CreatePipeline()
    {
        var manifestPath = ResolveManifestPath();
        CompatibilityService? compatibility = null;
        string? error = null;
        try
        {
            compatibility = new CompatibilityService(CompatibilityService.LoadManifest(manifestPath));
        }
        catch (CompatibilityManifestException ex)
        {
            error = ex.Message;
        }

        return new ReaderPipeline(compatibility, error);
    }

    private string ResolveManifestPath()
    {
        var overridePath = Environment.GetEnvironmentVariable(ReaderInfo.CompatibilityFileEnvironmentVariable);
        return string.IsNullOrWhiteSpace(overridePath)
            ? Path.Combine(_baseDirectory, ReaderInfo.CompatibilityFileName)
            : overridePath.Trim();
    }

    private static int RefusalExitCode(ReaderState state) => state switch
    {
        ReaderState.NotFound => ExitCodes.NotFound,
        ReaderState.ProbeFailed => ExitCodes.ProbeFailed,
        _ => ExitCodes.Incompatible,
    };

    private void WriteJson<T>(T value) =>
        _stdout.WriteLine(JsonSerializer.Serialize(value, ScoutMindJson.Options));

    private void WriteStatusHuman(ReaderStatus status)
    {
        _stdout.WriteLine($"{ReaderInfo.Product} {ReaderInfo.Version}");
        _stdout.WriteLine($"状态        : {status.State}");
        _stdout.WriteLine($"说明        : {status.Message}");
        _stdout.WriteLine($"检测时间    : {ScoutMindJson.FormatTimestamp(status.DetectedAt)}");
        _stdout.WriteLine($"FM27 进程   : {DescribeProcess(status.Process)}");
        _stdout.WriteLine($"游戏        : {DescribeGame(status.Game)}");
        _stdout.WriteLine($"安装目录    : {status.Game?.InstallDir ?? "—"}");
        _stdout.WriteLine($"插件        : {DescribePlugin(status.Plugin)}");
        _stdout.WriteLine($"兼容性      : {DescribeCompatibility(status.Compatibility)}");

        if (status.Diagnostics.Count > 0)
        {
            _stdout.WriteLine("诊断：");
            foreach (var diagnostic in status.Diagnostics)
            {
                _stdout.WriteLine($"  - {diagnostic}");
            }
        }
    }

    private void WriteScanConfigHuman(ScannerConfigLoad scannerConfig)
    {
        var path = string.IsNullOrWhiteSpace(scannerConfig.Config.ScannerPath)
            ? "（未配置）"
            : scannerConfig.Config.ScannerPath;
        _stdout.WriteLine($"外部扫描器  : {path}");
        foreach (var diagnostic in scannerConfig.Diagnostics)
        {
            _stdout.WriteLine($"  · {diagnostic}");
        }
    }

    private void WriteProbeHuman(ProbeResult probe)
    {
        _stdout.WriteLine($"probe 结果  : {(probe.Passed ? "通过" : "失败")}");
        _stdout.WriteLine($"退出码      : {FormatNullable(probe.ExitCode)}");
        _stdout.WriteLine($"耗时        : {probe.DurationMs.ToString(CultureInfo.InvariantCulture)} ms");
        if (!string.IsNullOrWhiteSpace(probe.Output))
        {
            _stdout.WriteLine("输出：");
            _stdout.WriteLine(probe.Output.TrimEnd());
        }

        if (probe.FailureReason is not null)
        {
            _stderr.WriteLine($"失败原因    : {probe.FailureReason}");
        }
    }

    private void WriteScanResultHuman(ScanResult result)
    {
        _stdout.WriteLine($"扫描状态    : {result.State}");
        _stdout.WriteLine($"扫描 ID     : {result.ScanId}");
        _stdout.WriteLine($"开始时间    : {ScoutMindJson.FormatTimestamp(result.StartedAt)}");
        _stdout.WriteLine($"结束时间    : {ScoutMindJson.FormatTimestamp(result.FinishedAt)}");
        _stdout.WriteLine($"退出码      : {FormatNullable(result.ExitCode)}");
        _stdout.WriteLine($"球员数量    : {result.PlayersCount.ToString(CultureInfo.InvariantCulture)}");
        _stdout.WriteLine($"转会数量    : {result.TransfersCount.ToString(CultureInfo.InvariantCulture)}");
        _stdout.WriteLine($"输出文件    : {result.OutputFile ?? "—"}");
        _stdout.WriteLine($"stdout      : {result.StdoutFile ?? "—"}");
        _stdout.WriteLine($"stderr      : {result.StderrFile ?? "—"}");

        if (result.Warnings.Count > 0)
        {
            _stdout.WriteLine("告警：");
            foreach (var warning in result.Warnings)
            {
                _stdout.WriteLine($"  - {warning}");
            }
        }

        if (result.FailureReason is not null)
        {
            _stderr.WriteLine($"失败原因    : {result.FailureReason}");
        }
    }

    private void WriteManifestHuman(CompatibilityManifest manifest, string manifestPath)
    {
        _stdout.WriteLine($"兼容清单    : {manifestPath}");
        _stdout.WriteLine($"schemaVersion: {manifest.SchemaVersion.ToString(CultureInfo.InvariantCulture)}");
        _stdout.WriteLine($"条目数量    : {manifest.Entries.Count.ToString(CultureInfo.InvariantCulture)}");
        for (var index = 0; index < manifest.Entries.Count; index++)
        {
            var entry = manifest.Entries[index];
            _stdout.WriteLine(
                $"  {index + 1}. appId={entry.AppId} buildId={entry.BuildId} plugin={entry.PluginProductVersion} 状态={FormatStatus(entry.Status)}");
            if (!string.IsNullOrWhiteSpace(entry.Notes))
            {
                _stdout.WriteLine($"     说明：{entry.Notes}");
            }

            _stdout.WriteLine($"     验证时间：{(entry.VerifiedAt is null ? "—" : ScoutMindJson.FormatTimestamp(entry.VerifiedAt.Value))}");
        }
    }

    private static string FormatStatus(CompatibilityStatus status) => status switch
    {
        CompatibilityStatus.Candidate => "candidate",
        CompatibilityStatus.Verified => "verified",
        _ => "rejected",
    };

    private static string DescribeProcess(ProcessInfo? process) =>        process is null
            ? "未运行"
            : $"pid {process.Pid.ToString(CultureInfo.InvariantCulture)}（{process.ProcessName}）{process.ExecutablePath}";

    private static string DescribeGame(GameInfo? game) =>
        game is null
            ? "—"
            : $"appId={game.AppId} build={game.BuildId ?? "—"} 版本={game.GameVersion ?? "—"}";

    private static string DescribePlugin(PluginInfo? plugin) =>
        plugin is null
            ? "未找到 game_plugin.dll"
            : $"{plugin.ProductVersion ?? "—"}（文件版本 {plugin.FileVersion ?? "—"}）";

    private static string DescribeCompatibility(CompatibilityResult? compatibility) =>
        compatibility is null
            ? "未判定"
            : $"{compatibility.Status} / {compatibility.Reason}";

    private static string FormatNullable(int? value) =>
        value?.ToString(CultureInfo.InvariantCulture) ?? "—";

    private void WriteUsageError(string message)
    {
        _stderr.WriteLine($"参数错误：{message}");
        WriteUsage(_stderr);
    }

    private void WriteUsage(TextWriter writer)
    {
        writer.WriteLine("用法：");
        writer.WriteLine("  ScoutMind.LiveReader status [--json]");
        writer.WriteLine("  ScoutMind.LiveReader probe [--json] [--report <文件>]");
        writer.WriteLine("  ScoutMind.LiveReader scan [--output <目录>] [--timeout <秒>] [--json]");
        writer.WriteLine("  ScoutMind.LiveReader date [--json]");
        writer.WriteLine("  ScoutMind.LiveReader date-discovery --expect <yyyy-MM-dd> [--max-mb <1..8192>] [--json]");
        writer.WriteLine("  ScoutMind.LiveReader pointer-scan --target <0x地址> [--window <字节>] [--max-mb <1..8192>] [--json]");
        writer.WriteLine("  ScoutMind.LiveReader date-locate [--max-mb <1..8192>] [--json]");
        writer.WriteLine("  ScoutMind.LiveReader module-info [--json]");
        writer.WriteLine("  ScoutMind.LiveReader static-date-scan --expect <yyyy-MM-dd> [--depth 1|2] [--max-mb <1..8192>] [--json]");
        writer.WriteLine("  ScoutMind.LiveReader date-read --rva <0x偏移> --field <0x字段偏移> [--json]");
        writer.WriteLine("  ScoutMind.LiveReader compatibility list [--json]");
        writer.WriteLine();
        writer.WriteLine("退出码：");
        writer.WriteLine("  0  成功");
        writer.WriteLine("  2  未找到 FM27");
        writer.WriteLine("  3  构建或版本不受支持 / 无法确定（拒绝读取）");
        writer.WriteLine($"  {ExitCodes.ProbeFailed.ToString(CultureInfo.InvariantCulture)}  probe 失败");
        writer.WriteLine("  5  扫描失败");
        writer.WriteLine("  64 用法或配置错误");
    }
}







