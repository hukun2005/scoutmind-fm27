using System.Text;
using System.Text.Json;
using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Integration;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Versioning;

namespace ScoutMind.FMReader.Diag;

/// <summary>
/// 诊断入口：<c>status</c> / <c>probe</c> / <c>scan</c>。
///
/// 只做一件事：把引擎的判断原样打印出来。它**不**提供跳过版本闸门的开关——未验证的构建一律拒绝，
/// 这里只是让拒绝原因（构建号、插件版本、命中的清单条目）可见，便于按流程逐项核对偏移。
/// </summary>
internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        var command = args.FirstOrDefault()?.Trim().ToLowerInvariant() ?? "status";
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        var engine = new FMSuperScoutMemoryEngine();

        switch (command)
        {
            case "status":
            {
                var status = await engine.GetStatusAsync(cancellation.Token).ConfigureAwait(false);
                Console.WriteLine(ToJson(new
                {
                    engine_version = status.EngineVersion,
                    process_id = status.ProcessId,
                    process_path = status.ProcessPath,
                    install_directory = status.InstallDirectory,
                    app_id = status.AppId,
                    build = status.Build,
                    plugin_path = status.PluginPath,
                    plugin_version = status.PluginVersion,
                    access_denied = status.AccessDenied,
                    gate = status.Gate is null
                        ? null
                        : new
                        {
                            allow_scan = status.Gate.AllowScan,
                            status = status.Gate.Status.ToString(),
                            layout = status.Gate.Layout,
                            message = status.Gate.Message,
                        },
                    diagnostics = status.Diagnostics,
                }));
                return status.Gate?.AllowScan == true ? 0 : 3;
            }

            case "probe":
            {
                var probe = await engine.ProbeAsync(cancellation.Token).ConfigureAwait(false);
                Console.WriteLine(ToJson(new
                {
                    passed = probe.Passed,
                    reason = probe.Reason,
                    duration_ms = probe.DurationMs,
                    process_id = probe.Status.ProcessId,
                    build = probe.Status.Build,
                    plugin_version = probe.Status.PluginVersion,
                    gate = probe.Status.Gate is null ? null : probe.Status.Gate.Message,
                    diagnostics = probe.Status.Diagnostics,
                }));
                return probe.Passed ? 0 : 3;
            }

            case "scan":
            {
                var scan = await engine.ScanAsync(cancellation.Token).ConfigureAwait(false);
                if (scan.PayloadJson is null)
                {
                    Console.WriteLine(ToJson(new
                    {
                        ok = false,
                        failure_reason = scan.FailureReason,
                        build = scan.Status.Build,
                        plugin_version = scan.Status.PluginVersion,
                        diagnostics = scan.Status.Diagnostics,
                    }));
                    return 3;
                }

                Console.WriteLine(ToJson(new
                {
                    ok = true,
                    players = scan.Players,
                    clubs = scan.Clubs,
                    transfers = scan.Transfers,
                    coverage = scan.Coverage,
                    warnings = scan.Warnings,
                    payload = JsonDocument.Parse(scan.PayloadJson).RootElement,
                }));
                return 0;
            }

            case "map":
            {
                var source = args.Length > 1 ? args[1] : null;
                if (source is null || !File.Exists(source))
                {
                    Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag map <上游 dump.json> [输出路径]");
                    return 64;
                }

                var mapper = new UpstreamDumpMapper();
                var mapped = mapper.Map(File.ReadAllText(source), new GameIdentity("27.1", "26620374", "4530370"), "0.1.0");
                var target = args.Length > 2 ? args[2] : Path.Combine(Path.GetTempPath(), "scoutmind-mapped.json");
                File.WriteAllText(target, mapped.Payload);
                Console.WriteLine(ToJson(new
                {
                    output = target,
                    players = mapped.Players,
                    clubs = mapped.Clubs,
                    coverage = mapped.Coverage,
                    warnings = mapped.Warnings,
                }));
                return 0;
            }

            case "report":
            {
                var report = await engine.DiagnoseAsync(cancellation.Token).ConfigureAwait(false);
                var target = args.Length > 1 ? args[1] : null;
                var json = JsonSerializer.Serialize(report, new JsonSerializerOptions
                {
                    WriteIndented = true,
                    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
                    Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() },
                });
                if (!string.IsNullOrWhiteSpace(target))
                {
                    File.WriteAllText(target, json);
                    Console.Error.WriteLine($"报告已写入 {target}");
                }

                Console.WriteLine(json);
                return report.ScanAllowed ? 0 : 3;
            }

            case "layout":
            {
                var resolver = new LayoutResolver();
                var registry = new CompatibilityRegistry();
                var rows = LayoutResolver.KnownBuildMap().Select(item =>
                {
                    var entry = registry.For(item.Key);
                    var layout = resolver.Resolve(item.Key);
                    return new
                    {
                        build = item.Key,
                        layout = item.Value,
                        registry_status = entry?.Status.ToString() ?? "unregistered",
                        layout_status = layout?.Status.ToString() ?? "n/a",
                        scan_allowed = registry.AllowsScan(item.Key),
                        verified_fields = entry?.VerifiedFields.Count ?? 0,
                        note = entry?.Note,
                    };
                });
                Console.WriteLine(ToJson(new { builds = rows, steam_libraries = SteamPaths.Libraries() }));
                return 0;
            }

            case "foot":
                Console.WriteLine(ToJson(new
                {
                    rechts = UpstreamDumpMapper.MapFoot("Rechts"),
                    links = UpstreamDumpMapper.MapFoot("Links"),
                    beide = UpstreamDumpMapper.MapFoot("Beide"),
                }));
                return 0;

            default:
                Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag [status|probe|scan|foot]");
                return 64;
        }
    }

    private static string ToJson(object value) =>
        JsonSerializer.Serialize(value, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
}
