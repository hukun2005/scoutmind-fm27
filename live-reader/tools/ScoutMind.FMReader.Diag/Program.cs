using System.Globalization;
using System.Text;
using System.Text.Json;
using ScoutMind.FMReader.Calibration;
using ScoutMind.FMReader.Discovery;
using ScoutMind.FMReader.Engine;
using ScoutMind.FMReader.Layouts;
using ScoutMind.FMReader.Probes;
using ScoutMind.FMReader.Integration;
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
                    report = args.Contains("--summary", StringComparer.Ordinal) ? null : probe.Report,
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

            case "players":
            {
                // 只读抽样：把定位到的球员样本（姓名/CA/PA/身高/生日/合同/俱乐部/号码）打印出来，供人工与游戏内核对。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                try
                {
                    using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                    var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                    var players = locator.FindPlayers(layout, 60, TimeSpan.FromSeconds(20));
                    var rows = new List<object>();
                    foreach (var item in players)
                    {
                        var ca = memory.UInt16(item.Block + layout["PLAO_CA"]);
                        var pa = memory.UInt16(item.Block + layout["PLAO_PA"]);
                        var height = memory.UInt16(item.Block + layout["PLAO_HEIGHT"]);
                        var birth = FmDate.Decode(memory.UInt32(item.Person + layout["PERO_DOB"]));
                        var name = memory.NestedString(item.Person + layout["PERO_COMMON_NAME"])
                                   ?? string.Join(" ", new[]
                                   {
                                       memory.NestedString(item.Person + layout["PERO_FIRST_NAME"]),
                                       memory.NestedString(item.Person + layout["PERO_SECOND_NAME"]),
                                   }.Where(part => !string.IsNullOrWhiteSpace(part)));

                        int? expiryYear = null;
                        int? squadNumber = null;
                        string? clubName = null;
                        var contract = memory.Pointer(item.Person + layout["PERO_FULL_CONTRACT"]);
                        if (contract != 0 && memory.IsReadable(contract + layout["CON_EXPIRY"], 4))
                        {
                            var expiry = FmDate.Decode(memory.UInt32(contract + layout["CON_EXPIRY"]));
                            if (expiry.Year != 0)
                            {
                                expiryYear = expiry.Year;
                            }

                            squadNumber = memory.Byte(contract + layout["CON_SQUAD_NUMBER"]);
                            var team = memory.Pointer(contract + layout["CON_TEAM"]);
                            if (team != 0 && memory.IsReadable(team + layout["TEAM_CLUB"], 8))
                            {
                                var club = memory.Pointer(team + layout["TEAM_CLUB"]);
                                if (club != 0)
                                {
                                    clubName = memory.IndirectString(club + layout["CLUB_NAME"]);
                                }
                            }
                        }

                        rows.Add(new
                        {
                            name = string.IsNullOrWhiteSpace(name) ? null : name,
                            ca,
                            pa,
                            height,
                            birth_year = birth.Year == 0 ? (int?)null : birth.Year,
                            contract_year = expiryYear,
                            club = clubName,
                            squad_number = squadNumber,
                        });
                    }

                    Console.WriteLine(ToJson(new { layout = layout.Name, found = players.Count, sample = rows }));
                    return 0;
                }
                catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                {
                    Console.Error.WriteLine("无法读取进程内存");
                    return 3;
                }
            }
            case "compare":
            {
                // 与已有 FMSuperScout 导出比对同一存档的球员数值（独立实现交叉校验）。
                // 用「姓名 + 出生年」作键，避免同名球员被误配。
                var dumpPath = args.Length > 1 ? args[1] : null;
                if (dumpPath is null || !File.Exists(dumpPath))
                {
                    Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag compare <dump.json>");
                    return 64;
                }

                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                using var dump = JsonDocument.Parse(File.ReadAllText(dumpPath));
                var reference = new Dictionary<string, (int Ca, int Pa, int Height, int BirthYear, int? ExpiryYear, string? Club)>(StringComparer.Ordinal);
                foreach (var player in dump.RootElement.GetProperty("players").EnumerateArray())
                {
                    var name = player.TryGetProperty("name", out var nameElement) ? nameElement.GetString() : null;
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        continue;
                    }

                    var birthYear = player.TryGetProperty("birthYear", out var birth) ? birth.GetInt32() : 0;
                    int? expiryYear = null;
                    if (player.TryGetProperty("expires", out var expires) && expires.ValueKind == JsonValueKind.String
                        && expires.GetString() is { Length: >= 4 } expiresText
                        && int.TryParse(expiresText[..4], out var parsedYear))
                    {
                        expiryYear = parsedYear;
                    }

                    reference[$"{name}|{birthYear}"] = (
                        player.TryGetProperty("ca", out var ca) ? ca.GetInt32() : 0,
                        player.TryGetProperty("pa", out var pa) ? pa.GetInt32() : 0,
                        player.TryGetProperty("height", out var height) ? height.GetInt32() : 0,
                        birthYear,
                        expiryYear,
                        player.TryGetProperty("club", out var club) && club.ValueKind == JsonValueKind.String ? club.GetString() : null);
                }

                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var sample = locator.FindPlayers(layout, 400, TimeSpan.FromSeconds(40));
                int matched = 0, caOk = 0, paOk = 0, heightOk = 0, birthOk = 0;
                int expiryOk = 0, expiryApplicable = 0, clubOk = 0, clubApplicable = 0;
                var mismatches = new List<object>();
                foreach (var player in sample)
                {
                    var name = memory.NestedString(player.Person + layout["PERO_COMMON_NAME"])
                               ?? string.Join(" ", new[]
                               {
                                   memory.NestedString(player.Person + layout["PERO_FIRST_NAME"]),
                                   memory.NestedString(player.Person + layout["PERO_SECOND_NAME"]),
                               }.Where(part => !string.IsNullOrWhiteSpace(part)));
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        continue;
                    }

                    var birth = FmDate.Decode(memory.UInt32(player.Person + layout["PERO_DOB"])).Year;
                    if (!reference.TryGetValue($"{name}|{birth}", out var expected))
                    {
                        continue;
                    }

                    matched++;
                    var ca = memory.UInt16(player.Block + layout["PLAO_CA"]);
                    var pa = memory.UInt16(player.Block + layout["PLAO_PA"]);
                    var height = memory.UInt16(player.Block + layout["PLAO_HEIGHT"]);
                    if (ca == expected.Ca) caOk++;
                    if (pa == expected.Pa) paOk++;
                    if (height == expected.Height) heightOk++;
                    if (birth == expected.BirthYear) birthOk++;

                    int? expiryYear = null;
                    string? clubName = null;
                    var contract = memory.Pointer(player.Person + layout["PERO_FULL_CONTRACT"]);
                    if (contract != 0 && memory.IsReadable(contract + layout["CON_EXPIRY"], 4))
                    {
                        var expiry = FmDate.Decode(memory.UInt32(contract + layout["CON_EXPIRY"]));
                        expiryYear = expiry.Year == 0 ? null : expiry.Year;
                        var team = memory.Pointer(contract + layout["CON_TEAM"]);
                        if (team != 0 && memory.IsReadable(team + layout["TEAM_CLUB"], 8))
                        {
                            var club = memory.Pointer(team + layout["TEAM_CLUB"]);
                            if (club != 0)
                            {
                                clubName = memory.IndirectString(club + layout["CLUB_NAME"]);
                            }
                        }
                    }

                    if (expected.ExpiryYear is not null && expiryYear is not null)
                    {
                        expiryApplicable++;
                        if (expiryYear == expected.ExpiryYear) expiryOk++;
                    }

                    if (!string.IsNullOrWhiteSpace(expected.Club) && !string.IsNullOrWhiteSpace(clubName))
                    {
                        clubApplicable++;
                        if (string.Equals(expected.Club, clubName, StringComparison.Ordinal)) clubOk++;
                    }

                    if (mismatches.Count < 8 && (ca != expected.Ca || pa != expected.Pa || height != expected.Height))
                    {
                        mismatches.Add(new
                        {
                            name,
                            birth,
                            reader = new { ca, pa, height, expiry_year = expiryYear, club = clubName },
                            dump = new { ca = expected.Ca, pa = expected.Pa, height = expected.Height, expiry_year = expected.ExpiryYear, club = expected.Club },
                        });
                    }
                }

                Console.WriteLine(ToJson(new
                {
                    sampled = sample.Count,
                    matched,
                    ca_ok = caOk,
                    pa_ok = paOk,
                    height_ok = heightOk,
                    birth_year_ok = birthOk,
                    expiry_ok = expiryOk,
                    expiry_applicable = expiryApplicable,
                    club_ok = clubOk,
                    club_applicable = clubApplicable,
                    mismatches,
                }));
                return matched > 0 && caOk == matched && paOk == matched ? 0 : 3;
            }
            case "match":
            {
                // 任务一：未匹配记录分类（只分类，不删除、不强行匹配）。
                var dumpPath = args.Length > 1 ? args[1] : null;
                if (dumpPath is null || !File.Exists(dumpPath))
                {
                    Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag match <dump.json> [sample]");
                    return 64;
                }

                var limit = args.Length > 2 && int.TryParse(args[2], out var parsedLimit) ? parsedLimit : 400;
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                var reference = new MatchDiagnostics.Reference();
                using (var dump = JsonDocument.Parse(File.ReadAllText(dumpPath)))
                {
                    foreach (var player in dump.RootElement.GetProperty("players").EnumerateArray())
                    {
                        var name = player.TryGetProperty("name", out var nameElement) ? nameElement.GetString() : null;
                        var birthYear = player.TryGetProperty("birthYear", out var birth) ? birth.GetInt32() : 0;
                        if (!string.IsNullOrWhiteSpace(name))
                        {
                            reference.Add(name!, birthYear);
                        }
                    }
                }

                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var rows = new List<MatchDiagnostics.ReaderRow>();
                foreach (var player in locator.FindPlayers(layout, limit, TimeSpan.FromSeconds(45)))
                {
                    var name = memory.NestedString(player.Person + layout["PERO_COMMON_NAME"])
                               ?? string.Join(" ", new[]
                               {
                                   memory.NestedString(player.Person + layout["PERO_FIRST_NAME"]),
                                   memory.NestedString(player.Person + layout["PERO_SECOND_NAME"]),
                               }.Where(part => !string.IsNullOrWhiteSpace(part)));
                    var birthYear = FmDate.Decode(memory.UInt32(player.Person + layout["PERO_DOB"])).Year;
                    var gender = memory.Byte(player.Db + layout["PERO_GENDER"]);
                    rows.Add(new MatchDiagnostics.ReaderRow(name, birthYear, (gender & 0x10) != 0));
                }

                var report = MatchDiagnostics.Summarize(rows, reference);
                Console.WriteLine(ToJson(new
                {
                    sampled = report.Sampled,
                    matched = report.Matched,
                    unmatched = report.Unmatched.Count,
                    reference_keys = report.ReferenceSize,
                    counts = report.Counts.ToDictionary(item => item.Key.ToString(), item => item.Value),
                    details = report.Unmatched.Select(item => new
                    {
                        outcome = item.Outcome.ToString(),
                        name = item.Name,
                        birth_year = item.BirthYear,
                        detail = item.Detail,
                    }),
                }));
                return 0;
            }

            case "sample":
            {
                // 任务三：生成 30 名可人工核对的样本（JSON + Markdown）。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var reader = new VerificationReader(memory, layout);
                var candidates = new List<VerificationPlayer>();
                foreach (var located in locator.FindPlayers(layout, 400, TimeSpan.FromSeconds(40)))
                {
                    var row = reader.Read(located);
                    if (row is not null)
                    {
                        candidates.Add(row);
                    }
                }

                var sample = VerificationSample.Select(candidates, 30);
                var outputJson = args.Length > 1 ? args[1] : null;
                var json = ToJson(new
                {
                    build = "26620374",
                    plugin_version = "27.1.0+2505117",
                    candidates = candidates.Count,
                    selected = sample.Count,
                    players = sample,
                });
                if (!string.IsNullOrWhiteSpace(outputJson))
                {
                    File.WriteAllText(outputJson, json);
                    var markdown = VerificationSample.ToMarkdown(sample, "26620374", "27.1.0+2505117");
                    File.WriteAllText(Path.ChangeExtension(outputJson, ".md"), markdown);
                    Console.Error.WriteLine($"样本已写入 {outputJson} 与 .md");
                }

                Console.WriteLine(json);
                return sample.Count > 0 ? 0 : 3;
            }

            case "protocol":
            {
                // 把读取器信封（camelCase）转成后端要求的协议报文（snake_case），供离线验证/手动投递。
                var source = args.Length > 1 ? args[1] : null;
                if (source is null || !File.Exists(source))
                {
                    Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag protocol <envelope.json> [out.json]");
                    return 64;
                }

                var envelope = System.Text.Json.JsonSerializer.Deserialize<ScoutMind.Contracts.ScanEnvelope>(
                    File.ReadAllText(source), ScoutMind.Contracts.ScoutMindJson.Options);
                if (envelope is null)
                {
                    Console.Error.WriteLine("无法按读取器信封结构解析");
                    return 3;
                }

                var bytes = ScoutMind.Contracts.ScanProtocolSerializer.ToProtocolJson(envelope);
                var target = args.Length > 2 ? args[2] : Path.ChangeExtension(source, ".protocol.json");
                File.WriteAllBytes(target, bytes);
                Console.WriteLine(ToJson(new
                {
                    output = target,
                    bytes = bytes.Length,
                    scan_id = envelope.Scan.ScanId,
                    players = envelope.Players.Count,
                    clubs = envelope.Clubs.Count,
                    schema = envelope.SchemaVersion,
                }));
                return 0;
            }

            case "fields":
            {
                // 每个字段的偏移/类型/可信度/证据来源；供文档与审计使用。
                var layout = new ScoutMind.FMReader.Layouts.FM27_1_Layout();
                var rows = ScoutMind.FMReader.Engine.FieldMetadataCatalog.Build(layout);
                Console.WriteLine(ToJson(new
                {
                    layout = layout.Name,
                    count = rows.Count,
                    verified = rows.Count(row => row.Status == "Verified"),
                    candidate = rows.Count(row => row.Status == "Candidate"),
                    pending = rows.Count(row => row.Status == "Pending"),
                    fields = rows,
                }));
                return 0;
            }

            case "capture-live":
            {
                // Real raw capture from the running game; expected UI values are left empty on purpose.
                var limit = args.Length > 1 && int.TryParse(args[1], out var parsed) ? parsed : 20;
                var result = await engine.CaptureLiveAsync(limit, cancellation.Token).ConfigureAwait(false);
                var payload = ToJson(result);
                if (args.Length > 2 && !string.IsNullOrWhiteSpace(args[2]))
                {
                    File.WriteAllText(args[2], payload, new System.Text.UTF8Encoding(false));
                    Console.WriteLine($"真实原始采样已写入 {args[2]}");
                }
                else
                {
                    Console.WriteLine(payload);
                }
                Console.Error.WriteLine("NOTE: expected_value 为空；必须由操作员按游戏界面填写后才能验证。");
                return 0;
            }

            case "capture":
            {
                // SM-057：采样工具结构验证。没有运行中的 FM27 时只导出 simulated 证据，真实采集记 NOT_RUN。
                var store = new ScoutMind.FMReader.Evidence.FieldValidationCaptureStore();
                var now = DateTime.UtcNow.ToString("O");
                store.Add(new ScoutMind.FMReader.Evidence.FieldValidationCapture(
                    "CON_EXPIRY", "SIM-0001", "contract", "0x00000000", "2027-06-30", "26620374",
                    "27.1.0+2505117", "FM27_1", "2026-07-01", now, "simulated", "Pending", true));
                store.Add(new ScoutMind.FMReader.Evidence.FieldValidationCapture(
                    "PERO_COMMON_NAME", "SIM-0002", "person", "Player One", "Player One", "26620374",
                    "27.1.0+2505117", "FM27_1", "2026-07-01", now, "simulated", "Candidate", true));
                var directory = args.Length > 1 ? args[1] : "exports/field-capture";
                Directory.CreateDirectory(directory);
                File.WriteAllText(Path.Combine(directory, "captures.json"), store.ToJson(), new System.Text.UTF8Encoding(false));
                File.WriteAllText(Path.Combine(directory, "captures.csv"), store.ToCsv(), new System.Text.UTF8Encoding(false));
                Console.WriteLine(ToJson(new
                {
                    count = store.Count,
                    json = Path.Combine(directory, "captures.json"),
                    csv = Path.Combine(directory, "captures.csv"),
                    real_fm27_capture = "NOT_RUN",
                    note = "当前样本为 simulated，仅验证结构；真实采集需要 FM27 运行 + 界面期望值",
                }));
                return 0;
            }

            case "evidence":
            {
                // SM-042：字段级证据。没有样本时最高 Candidate；可用 evidence <out.json> 导出。
                var layout = new ScoutMind.FMReader.Layouts.FM27_1_Layout();
                var rows = ScoutMind.FMReader.Evidence.FieldEvidenceCatalog.Build(layout);
                var payload = ToJson(new
                {
                    layout = layout.Name,
                    count = rows.Count,
                    verified = rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Verified),
                    candidate = rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Candidate),
                    pending = rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Pending),
                    rejected = rows.Count(row => row.ValidationStatus == ScoutMind.FMReader.Evidence.FieldValidationStatus.Rejected),
                    fields = rows,
                });
                if (args.Length > 1 && !string.IsNullOrWhiteSpace(args[1]))
                {
                    File.WriteAllText(args[1], payload, new System.Text.UTF8Encoding(false));
                    Console.WriteLine($"证据报告已写入 {args[1]}");
                }
                else
                {
                    Console.WriteLine(payload);
                }
                return 0;
            }

            case "configcheck":
            {
                // 三份兼容性配置是否一致；不一致时退出码 3（CI / 发布脚本可以直接用）。
                var config = new CompatibilityConfig();
                var issues = config.Validate();
                Console.WriteLine(ToJson(new
                {
                    consistent = issues.Count == 0,
                    issues,
                    gate = config.GateEntries.Select(item => new { item.Build, item.Layout, item.AppId, item.PluginVersion, status = item.Status.ToString() }),
                    registry = config.Registrations.Select(item => new
                    {
                        item.Build,
                        item.Layout,
                        status = item.Status.ToString(),
                        item.PluginVersion,
                        verified = item.VerifiedFields.Count,
                        upstream = item.UpstreamFields?.Count ?? 0,
                    }),
                }));
                return issues.Count == 0 ? 0 : 3;
            }

            case "foot":
                Console.WriteLine(ToJson(new
                {
                    rechts = UpstreamDumpMapper.MapFoot("Rechts"),
                    links = UpstreamDumpMapper.MapFoot("Links"),
                    beide = UpstreamDumpMapper.MapFoot("Beide"),
                }));
                return 0;

            case "calibrate":
            {
                // 只读校准：现场检测环境 → 跨区域抽样 → 同一对象多次读取 → JSON/Markdown 报告。
                // 不写任何游戏内存；旧的位置参数 count / maxOffset 仍然保留。
                if (args.Contains("--help", StringComparer.Ordinal))
                {
                    Console.WriteLine("用法：ScoutMind.FMReader.Diag calibrate [count] [maxOffset] [选项]");
                    Console.WriteLine();
                    Console.WriteLine("  count                 抽样数量（默认 24）");
                    Console.WriteLine("  maxOffset             候选偏移扫描上限（默认 1024）");
                    Console.WriteLine("  --dry-run             只检测环境，不读取球员对象");
                    Console.WriteLine("  --candidate <id>      指定候选布局（默认 fm27.1.person.2026-11-25）");
                    Console.WriteLine("  --reads <n>           同一对象重复读取次数（默认 3，至少 2）");
                    Console.WriteLine("  --samples <n>         覆盖抽样数量");
                    Console.WriteLine("  --locate-limit <n>    堆扫描最多定位数量（默认 max(240, samples*10)）");
                    Console.WriteLine("  --output <path>       写入脱敏 JSON");
                    Console.WriteLine("  --local-output <path> 写入含原始指针的本机诊断 JSON（不要上传）");
                    Console.WriteLine("  --markdown <path>     写入脱敏 Markdown 报告");
                    Console.WriteLine("  --include-pointers    标准输出包含原始指针（仅本机调试）");
                    Console.WriteLine("  --version             输出版本");
                    return 0;
                }

                if (args.Contains("--version", StringComparer.Ordinal))
                {
                    Console.WriteLine("calibrate 1.0 (schema 1.0)");
                    return 0;
                }

                var candidateId = FlagValue(args, "--candidate") ?? PersonLayoutCandidate.Fm27_1_20261125.CandidateId;
                var candidate = candidateId == PersonLayoutCandidate.Fm27_1_20261125.CandidateId
                    ? PersonLayoutCandidate.Fm27_1_20261125
                    : null;
                if (candidate is null)
                {
                    Console.Error.WriteLine($"未知候选：{candidateId}");
                    return 64;
                }

                var sampleCount = args.Length > 1 && int.TryParse(args[1], out var parsedCount) ? parsedCount : 24;
                sampleCount = IntFlag(args, "--samples", sampleCount);
                var maxOffset = args.Length > 2 && int.TryParse(args[2], out var parsedMax) ? parsedMax : 0x400;
                maxOffset = IntFlag(args, "--max-offset", maxOffset);
                var readCount = IntFlag(args, "--reads", 3);
                var locateLimit = IntFlag(args, "--locate-limit", Math.Max(240, sampleCount * 10));
                var dryRun = args.Contains("--dry-run", StringComparer.Ordinal);
                var includePointers = args.Contains("--include-pointers", StringComparer.Ordinal);
                var outputPath = FlagValue(args, "--output");
                var localOutputPath = FlagValue(args, "--local-output");
                var markdownPath = FlagValue(args, "--markdown");

                var status = await engine.GetStatusAsync(cancellation.Token).ConfigureAwait(false);
                var gameVersion = status.Gate?.Layout is { Length: > 0 } gateLayout
                    ? gateLayout.Replace("FM", string.Empty, StringComparison.Ordinal).Replace('_', '.')
                    : status.PluginVersion;
                var environment = new CalibrationEnvironment(
                    status.ProcessId,
                    string.IsNullOrWhiteSpace(status.ProcessPath) ? null : Path.GetFileNameWithoutExtension(status.ProcessPath),
                    gameVersion,
                    status.Build,
                    status.PluginVersion,
                    status.Gate?.Status.ToString(),
                    status.Gate?.AllowScan == true,
                    status.AccessDenied);

                var timestamp = DateTimeOffset.Now;
                PersonCalibrationReport EmitBlocked(string conclusion) => new()
                {
                    CandidateId = candidate.CandidateId,
                    GameVersion = environment.GameVersion ?? "unknown",
                    BuildNumber = environment.BuildNumber ?? "unknown",
                    Environment = environment,
                    CalibrationTimestamp = timestamp,
                    NameFieldOffsets = candidate.NameOffsetCandidates,
                    DateOfBirthOffset = candidate.DateOfBirthOffsetCandidate,
                    SamplingStrategy = "even_stride",
                    DryRun = dryRun,
                    VerificationStatus = CandidateVerificationStatus.UnsupportedBuild,
                    Conclusion = conclusion,
                };

                void Emit(PersonCalibrationReport report)
                {
                    Console.WriteLine(PersonCalibrationReportWriter.ToJson(report, includePointers));
                    if (!string.IsNullOrWhiteSpace(outputPath))
                    {
                        File.WriteAllText(outputPath, PersonCalibrationReportWriter.ToJson(report));
                    }

                    if (!string.IsNullOrWhiteSpace(localOutputPath))
                    {
                        File.WriteAllText(localOutputPath, PersonCalibrationReportWriter.ToJson(report, includePointers: true));
                    }

                    if (!string.IsNullOrWhiteSpace(markdownPath))
                    {
                        File.WriteAllText(markdownPath, PersonCalibrationReportWriter.ToMarkdown(report));
                    }
                }

                if (status.Gate?.AllowScan != true)
                {
                    Emit(EmitBlocked("版本闸门未允许扫描：本次不读取任何球员对象，也不使用历史环境作为通过依据。"));
                    return 3;
                }

                if (!string.Equals(status.Build, candidate.BuildNumber, StringComparison.Ordinal)
                    || (!string.IsNullOrWhiteSpace(gameVersion)
                        && !string.Equals(gameVersion, candidate.GameVersion, StringComparison.Ordinal)))
                {
                    Emit(EmitBlocked(
                        $"检测到的构建/版本（{status.Build ?? "unknown"} / {gameVersion ?? "unknown"}）与候选"
                        + $"（{candidate.BuildNumber} / {candidate.GameVersion}）不一致，拒绝用该候选校准。"));
                    return 3;
                }

                var layout = new LayoutResolver().Resolve(status.Build, gameVersion);
                if (layout is null)
                {
                    Emit(EmitBlocked("没有与本次检测到的构建/版本对应的布局。"));
                    return 3;
                }

                if (dryRun)
                {
                    Emit(new PersonCalibrationReport
                    {
                        CandidateId = candidate.CandidateId,
                        GameVersion = environment.GameVersion ?? "unknown",
                        BuildNumber = environment.BuildNumber ?? "unknown",
                        Environment = environment,
                        CalibrationTimestamp = timestamp,
                        NameFieldOffsets = candidate.NameOffsetCandidates,
                        DateOfBirthOffset = candidate.DateOfBirthOffsetCandidate,
                        SamplingStrategy = "even_stride",
                        DryRun = true,
                        VerificationStatus = CandidateVerificationStatus.Unverified,
                        Conclusion = "dry-run：只检测环境，未读取任何球员对象。",
                    });
                    return 0;
                }

                try
                {
                    using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                    var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                    var located = locator.FindPlayers(layout, Math.Max(1, locateLimit), TimeSpan.FromSeconds(45));
                    var persons = located.Select(player => player.Person).ToList();
                    var report = new PersonCalibrationEngine(memory).Run(
                        candidate,
                        persons,
                        environment,
                        new PersonCalibrationOptions(
                            Math.Max(2, readCount),
                            sampleCount,
                            locateLimit,
                            (uint)Math.Max(0, maxOffset),
                            true,
                            false),
                        timestamp);
                    Emit(report);
                    return report.VerificationStatus == CandidateVerificationStatus.Unstable ? 3 : 0;
                }
                catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                {
                    Emit(EmitBlocked("无法读取进程内存（可能未加载存档或权限不足）。"));
                    return 3;
                }
            }

            case "verify":
            {
                // 只读验证 + Mark(Verified) 安全门控：默认只到 HumanReviewPending，
                // 只有显式 --human-confirmed 且提供 reviewer/source/evidence 时才可能 Verified。
                if (args.Contains("--help", StringComparer.Ordinal))
                {
                    Console.WriteLine("用法：ScoutMind.FMReader.Diag verify <记录序号> [选项]");
                    Console.WriteLine();
                    Console.WriteLine("  --located <n>              堆扫描最多定位数量（默认 400）");
                    Console.WriteLine("  --reads <n>                重复读取次数（默认 3，至少 2）");
                    Console.WriteLine("  --human-confirmed          用户已在 FM27 界面人工核对");
                    Console.WriteLine("  --reviewer <id>            确认人");
                    Console.WriteLine("  --source <text>            确认来源（如 fm27-ui）");
                    Console.WriteLine("  --evidence <path>          证据文档引用");
                    Console.WriteLine("  --save-identity <fp>       Save Identity 指纹；缺省时不得 Mark(Verified)");
                    Console.WriteLine("  --save-file <path>         显式指定当前存档文件；用于核对 --save-identity 是否属于当前存档");
                    Console.WriteLine("  --save-id <label>          存档标签（默认与指纹一致）");
                    Console.WriteLine("  --session <key>            采集会话键（默认 pid:build）");
                    Console.WriteLine("  --alternative-strategy <s> 经批准的替代生日验证策略");
                    Console.WriteLine("  --name <text>              按姓名精确选人（与 --dob 组合，必须唯一）");
                    Console.WriteLine("  --dob <yyyy-MM-dd>         按出生日期筛选目标");
                    Console.WriteLine("  --output <path>            写入 JSON 结果");
                    Console.WriteLine("  --audit <path>             追加一行审计 JSON（Verified/Rejected 都必须记录）");
                    return 0;
                }

                var candidate = PersonLayoutCandidate.Fm27_1_20261125;
                var targetIndex = args.Length > 1 && int.TryParse(args[1], out var parsedIndex) ? parsedIndex : 0;
                var locatedLimit = Math.Max(1, IntFlag(args, "--located", 400));
                var readCount = Math.Max(2, IntFlag(args, "--reads", 3));
                var humanConfirmed = args.Contains("--human-confirmed", StringComparer.Ordinal);
                var reviewer = FlagValue(args, "--reviewer");
                var confirmationSource = FlagValue(args, "--source");
                var evidenceReference = FlagValue(args, "--evidence");
                var saveIdentityFingerprint = FlagValue(args, "--save-identity");
                var saveId = FlagValue(args, "--save-id") ?? saveIdentityFingerprint;
                var alternativeStrategy = FlagValue(args, "--alternative-strategy");
                var nameFilter = FlagValue(args, "--name");
                var dobFilterText = FlagValue(args, "--dob");
                DateOnly? dobFilter = null;
                if (!string.IsNullOrWhiteSpace(dobFilterText))
                {
                    if (!DateOnly.TryParseExact(dobFilterText, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsedDob))
                    {
                        Console.Error.WriteLine($"--dob 格式应为 yyyy-MM-dd：{dobFilterText}");
                        return 64;
                    }

                    dobFilter = parsedDob;
                }
                var outputPath = FlagValue(args, "--output");
                var auditPath = FlagValue(args, "--audit");
                var explicitSaveFile = FlagValue(args, "--save-file");

                // 当前存档指纹必须由本次现场探测得出，不能沿用调用方传入的历史指纹；
                // 歧义/未解析时保持 null，让门控按 current_save_identity_missing 拒绝 Verified。
                string? currentSaveFingerprint = null;
                string? currentSaveProblem = null;
                try
                {
                    var detected = new GameBuildDetector().Detect();
                    ISaveFileProbe probe = string.IsNullOrWhiteSpace(explicitSaveFile)
                        ? new SaveFileLocator()
                        : new SingleSaveFileProbe(explicitSaveFile);
                    var files = probe.Probe(includeContentHash: false);
                    var processEvidence = new GameProcessEvidence(
                        detected.ProcessId,
                        detected.ProcessStartTime,
                        detected.Build,
                        detected.PluginVersion,
                        detected.ProcessId is not null);
                    var liveResolution = SaveIdentityResolver.Resolve(new SaveIdentityInput(processEvidence, files));
                    currentSaveFingerprint = SaveIdentityBinding.CurrentFingerprint(liveResolution);
                    if (currentSaveFingerprint is null)
                    {
                        currentSaveProblem = liveResolution.IsAmbiguous
                            ? "current_save_identity_ambiguous"
                            : "current_save_identity_unresolved";
                    }
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    currentSaveProblem = "current_save_identity_unreadable";
                }

                var status = await engine.GetStatusAsync(cancellation.Token).ConfigureAwait(false);
                var gameVersion = status.Gate?.Layout is { Length: > 0 } gateLayout
                    ? gateLayout.Replace("FM", string.Empty, StringComparison.Ordinal).Replace('_', '.')
                    : status.PluginVersion;
                var buildSupported = status.Gate?.AllowScan == true;
                var environment = new CalibrationEnvironment(
                    status.ProcessId,
                    string.IsNullOrWhiteSpace(status.ProcessPath) ? null : Path.GetFileNameWithoutExtension(status.ProcessPath),
                    gameVersion,
                    status.Build,
                    status.PluginVersion,
                    status.Gate?.Status.ToString(),
                    buildSupported,
                    status.AccessDenied);
                var sessionKey = FlagValue(args, "--session")
                                 ?? (status.ProcessId is { } processId
                                     ? string.Concat(processId.ToString(CultureInfo.InvariantCulture), ":", status.Build ?? "unknown")
                                     : null);

                string? displayName = null;
                DateOnly? dateOfBirth = null;
                int? ca = null;
                AttributeLinkResult? link = null;
                var pointerValid = false;
                var structureValid = false;
                var readsStable = false;
                var stableReadCount = 0;
                double confidence = 0;
                var layout = new LayoutResolver().Resolve(status.Build, gameVersion);
                var layoutMatches = layout is not null
                                    && string.Equals(gameVersion, candidate.GameVersion, StringComparison.Ordinal);

                if (layout is null || !buildSupported)
                {
                    var blocked = new PersonVerificationRequest(
                        candidate.CandidateId,
                        candidate.GameVersion,
                        status.Build ?? "unknown",
                        candidate.BuildNumber,
                        buildSupported,
                        layoutMatches,
                        false,
                        false,
                        null,
                        null,
                        alternativeStrategy,
                        null,
                        null,
                        false,
                        0,
                        0,
                        humanConfirmed,
                        reviewer,
                        confirmationSource,
                        evidenceReference,
                        DateTimeOffset.Now);
                    var blockedDecision = new PersonVerificationGate().Evaluate(blocked);
                    Console.WriteLine(ToJson(new
                    {
                        mode = "verify",
                        state = blockedDecision.State.ToString(),
                        mark_verified = blockedDecision.MarkVerified,
                        reasons = blockedDecision.Reasons,
                        warnings = blockedDecision.Warnings,
                        audit = JsonDocument.Parse(blockedDecision.Audit.ToJsonLine()).RootElement.Clone(),
                    }));
                    return 3;
                }

                try
                {
                    using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                    var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                    var located = locator.FindPlayers(layout, locatedLimit, TimeSpan.FromSeconds(45));
                    if (located.Count == 0)
                    {
                        Console.Error.WriteLine("没有定位到球员记录");
                        return 3;
                    }

                    var factsReader = new PlayerRecordFactsReader(memory, layout);
                    var facts = located.Select(factsReader.Read).ToList();

                    // 定位序号在两次扫描之间可能漂移；人工确认必须按姓名/生日精确选人，且要求唯一。
                    if (!string.IsNullOrWhiteSpace(nameFilter) || dobFilter is not null)
                    {
                        var matches = Enumerable.Range(0, facts.Count)
                            .Where(index => (string.IsNullOrWhiteSpace(nameFilter) || NameMatches(facts[index], nameFilter!))
                                            && (dobFilter is null || facts[index].DateOfBirth == dobFilter))
                            .ToList();
                        if (matches.Count == 0)
                        {
                            Console.Error.WriteLine("没有找到与姓名/生日匹配的球员，拒绝继续");
                            return 3;
                        }

                        if (matches.Count > 1)
                        {
                            Console.Error.WriteLine($"姓名/生日匹配到 {matches.Count} 条记录，拒绝自动选择");
                            return 3;
                        }

                        targetIndex = matches[0];
                    }

                    if (targetIndex < 0 || targetIndex >= facts.Count)
                    {
                        Console.Error.WriteLine($"记录序号超出范围：{targetIndex}（共 {facts.Count} 条）");
                        return 3;
                    }

                    var target = facts[targetIndex];
                    displayName = BuildName(target);
                    dateOfBirth = target.DateOfBirth;
                    ca = target.Ca;
                    link = new AttributeRecordLinker().Link(PersonIdentityFields.FromFacts(target), facts);

                    // Verified 必须绑定存档身份与会话：缺 --save-identity 时保持 RevalidationRequired。
                    VerifiedIdentityScope? scope = null;
                    if (!string.IsNullOrWhiteSpace(saveIdentityFingerprint)
                        && !string.IsNullOrWhiteSpace(sessionKey)
                        && !string.IsNullOrWhiteSpace(displayName)
                        && (dateOfBirth is not null || !string.IsNullOrWhiteSpace(alternativeStrategy))
                        && link.Target.Uid is { } confirmedUid
                        && link.CompatibleCandidates.Count > 0)
                    {
                        scope = new VerifiedIdentityScope(
                            string.IsNullOrWhiteSpace(saveId) ? saveIdentityFingerprint! : saveId!,
                            saveIdentityFingerprint!,
                            sessionKey!,
                            status.Build ?? "unknown",
                            candidate.GameVersion,
                            confirmedUid,
                            displayName!,
                            dateOfBirth ?? default,
                            alternativeStrategy,
                            VerifiedIdentityScope.AttributeRecordIdentityOf(link.CompatibleCandidates[0].Facts),
                            DateTimeOffset.Now,
                            reviewer ?? string.Empty,
                            confirmationSource ?? string.Empty,
                            evidenceReference ?? string.Empty);
                    }

                    var calibration = new PersonCalibrationEngine(memory).Run(
                        candidate,
                        new[] { target.PersonPointer },
                        environment,
                        new PersonCalibrationOptions(readCount, 1, 1, 0, false, false));
                    var sample = calibration.Samples.Count > 0 ? calibration.Samples[0] : null;
                    pointerValid = sample is not null
                                   && sample.First.PersonPointer != 0
                                   && sample.First.Status != CandidateVerificationStatus.Rejected;
                    structureValid = sample?.First.Status == CandidateVerificationStatus.StructurallyValid;
                    readsStable = sample?.Stable == true;
                    stableReadCount = calibration.ReadCount;
                    confidence = calibration.Confidence;

                    var request = new PersonVerificationRequest(
                        candidate.CandidateId,
                        candidate.GameVersion,
                        status.Build ?? "unknown",
                        candidate.BuildNumber,
                        buildSupported,
                        layoutMatches,
                        pointerValid,
                        structureValid,
                        displayName,
                        dateOfBirth,
                        alternativeStrategy,
                        ca,
                        link,
                        readsStable,
                        stableReadCount,
                        confidence,
                        humanConfirmed,
                        reviewer,
                        confirmationSource,
                        evidenceReference,
                        DateTimeOffset.Now,
                        scope,
                        currentSaveFingerprint,
                        sessionKey);
                    var decision = new PersonVerificationGate().Evaluate(request);
                    var json = ToJson(new
                    {
                        mode = "verify",
                        state = decision.State.ToString(),
                        mark_verified = decision.MarkVerified,
                        reasons = decision.Reasons,
                        warnings = currentSaveProblem is null
                            ? decision.Warnings
                            : decision.Warnings.Concat(new[] { currentSaveProblem }).ToArray(),
                        current_save_identity = new
                        {
                            fingerprint = currentSaveFingerprint,
                            problem = currentSaveProblem,
                        },
                        save_scope = scope is null
                            ? null
                            : new
                            {
                                save_id = scope.SaveId,
                                save_identity_fingerprint = scope.SaveIdentityFingerprint,
                                save_session_key = scope.SaveSessionKey,
                                game_build = scope.GameBuild,
                                layout_version = scope.LayoutVersion,
                                person_uid = scope.PersonUid,
                                attribute_record_identity = scope.AttributeRecordIdentity,
                            },
                        target = new
                        {
                            index = targetIndex,
                            name = displayName,
                            date_of_birth = FormatDate(dateOfBirth),
                            ca,
                            attribute_link_status = link.Status.ToString(),
                            attribute_link_reason = link.Reason,
                            conflicts = link.Conflicts.Count,
                        },
                        audit = JsonDocument.Parse(decision.Audit.ToJsonLine()).RootElement.Clone(),
                    });
                    Console.WriteLine(json);
                    if (!string.IsNullOrWhiteSpace(outputPath))
                    {
                        File.WriteAllText(outputPath, json);
                    }

                    if (!string.IsNullOrWhiteSpace(auditPath))
                    {
                        File.AppendAllText(auditPath, decision.Audit.ToJsonLine() + Environment.NewLine);
                    }

                    return decision.State switch
                    {
                        PersonVerificationState.Verified => 0,
                        PersonVerificationState.HumanReviewPending => 2,
                        _ => 3,
                    };
                }
                catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                {
                    Console.Error.WriteLine("无法读取进程内存");
                    return 3;
                }
            }

            case "xref":
            {
                // 旧行为（默认）：在每条球员记录范围内寻找"指向完整 person 对象"的指针。
                // 新增（只读）：--link <index> 走路线 A 的多字段关联；--link-all 做唯一性审计。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var includePointers = args.Contains("--include-pointers", StringComparer.Ordinal);

                if (args.Contains("--link", StringComparer.Ordinal)
                    || args.Contains("--link-all", StringComparer.Ordinal))
                {
                    var locatedLimit = Math.Max(1, IntFlag(args, "--located", 400));
                    var located = locator.FindPlayers(layout, locatedLimit, TimeSpan.FromSeconds(45));
                    if (located.Count == 0)
                    {
                        Console.Error.WriteLine("没有定位到球员记录");
                        return 3;
                    }

                    var factsReader = new PlayerRecordFactsReader(memory, layout);
                    var facts = located.Select(factsReader.Read).ToList();
                    var indexOf = BuildIndexMap(located);
                    var linker = new AttributeRecordLinker();
                    var recordIndex = AttributeRecordIndex.Build(facts);

                    if (args.Contains("--link-all", StringComparer.Ordinal))
                    {
                        var auditCount = Math.Max(1, IntFlag(args, "--samples", 32));
                        var indexes = PersonCalibrationEngine.SelectEvenly(
                            Enumerable.Range(0, facts.Count).ToList(),
                            auditCount);
                        var counts = new Dictionary<string, int>(StringComparer.Ordinal);
                        var rows = new List<object>();
                        foreach (var index in indexes)
                        {
                            var result = linker.Link(PersonIdentityFields.FromFacts(facts[index]), recordIndex);
                            var key = result.Status.ToString();
                            counts[key] = counts.GetValueOrDefault(key) + 1;
                            rows.Add(new
                            {
                                target_index = index,
                                name = BuildName(facts[index]),
                                date_of_birth = FormatDate(facts[index].DateOfBirth),
                                status = key,
                                reason = result.Reason,
                                compatible = result.CompatibleCandidates.Count,
                                matched_fields = result.CompatibleCandidates.Count == 0
                                    ? Array.Empty<string>()
                                    : result.CompatibleCandidates[0].Comparisons
                                        .Where(item => item.Applicable && item.Matched)
                                        .Select(item => item.Field)
                                        .ToArray(),
                                missing_fields = result.MissingFields,
                            });
                        }

                        Console.WriteLine(ToJson(new
                        {
                            mode = "link-all",
                            located_total = facts.Count,
                            sampled = indexes.Count,
                            counts,
                            rows,
                        }));
                        return 0;
                    }

                    var targetIndex = IntFlag(args, "--link", 0);
                    if (targetIndex < 0 || targetIndex >= facts.Count)
                    {
                        Console.Error.WriteLine($"记录序号超出范围：{targetIndex}（共 {facts.Count} 条）");
                        return 3;
                    }

                    var humanConfirmed = args.Contains("--human-confirmed", StringComparer.Ordinal);
                    var targetIdentity = PersonIdentityFields.FromFacts(facts[targetIndex]);
                    var link = linker.Link(targetIdentity, facts, humanConfirmed);
                    Console.WriteLine(ToJson(new
                    {
                        mode = "link",
                        located_total = facts.Count,
                        target_index = targetIndex,
                        target = IdentityJson(targetIdentity),
                        status = link.Status.ToString(),
                        reason = link.Reason,
                        human_confirmed = humanConfirmed,
                        missing_fields = link.MissingFields,
                        compatible_candidates = link.CompatibleCandidates
                            .Select(candidate => LinkCandidateJson(candidate, indexOf, includePointers))
                            .ToArray(),
                        rejected_total = link.RejectedCandidates.Count,
                        rejected_candidates = link.RejectedCandidates
                            .Take(10)
                            .Select(candidate => LinkCandidateJson(candidate, indexOf, includePointers))
                            .ToArray(),
                        conflicts_total = link.Conflicts.Count,
                        conflict_candidates = link.Conflicts
                            .Take(10)
                            .Select(candidate => LinkCandidateJson(candidate, indexOf, includePointers))
                            .ToArray(),
                    }));
                    return 0;
                }

                var players = locator.FindPlayers(layout, 10, TimeSpan.FromSeconds(40));
                var hits = new List<object>();
                foreach (var player in players.Take(5))
                {
                    for (var off = 0; off <= 0x3C0; off += 8)
                    {
                        var target = memory.Pointer(player.Person + (ulong)off);
                        if (target == 0)
                        {
                            continue;
                        }

                        foreach (var nameOffset in new[] { 0x50, 0x58, 0x60 })
                        {
                            string? value;
                            try
                            {
                                value = memory.NestedString(target + (ulong)nameOffset);
                            }
                            catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                            {
                                continue;
                            }

                            if (string.IsNullOrWhiteSpace(value) || value.Length is < 2 or > 40)
                            {
                                continue;
                            }

                            if (!value.All(ch => char.IsLetter(ch) || ch is ' ' or '\'' or '-' or '.'))
                            {
                                continue;
                            }

                            hits.Add(new
                            {
                                record = $"0x{player.Person:X}",
                                record_offset = $"0x{off:X}",
                                target = $"0x{target:X}",
                                name_offset = $"0x{nameOffset:X}",
                                value,
                            });
                        }
                    }
                }

                Console.WriteLine(ToJson(new { players = players.Count, hits }));
                return 0;
            }

            case "dump":
            {
                // 只读诊断。默认输出摘要；原有 dump <index> [length] 行为保留。
                // 新增：--summary / --xref / --calibration / --person <index> / --length <n>。
                if (args.Contains("--help", StringComparer.Ordinal))
                {
                    Console.WriteLine("用法：ScoutMind.FMReader.Diag dump [index] [length] [选项]");
                    Console.WriteLine();
                    Console.WriteLine("  默认（无位置参数）       输出诊断摘要（不转储进程内存）");
                    Console.WriteLine("  --summary                输出诊断摘要");
                    Console.WriteLine("  --xref                   输出属性记录关联统计");
                    Console.WriteLine("  --calibration            输出校准统计（不含逐样本明细）");
                    Console.WriteLine("  --uid                    输出 UID 可行性审计（字段、唯一性、稳定性）");
                    Console.WriteLine("  --person <index>         转储一条球员记录（等同于旧版 dump <index>）");
                    Console.WriteLine("  --length <n>             旧版转储长度（默认 0x3C8）");
                    Console.WriteLine("  --located <n>            堆扫描最多定位数量（默认 800）");
                    Console.WriteLine("  --samples <n>            抽样数量（默认 60）");
                    Console.WriteLine("  --reads <n>              校准重复读取次数（默认 3）");
                    return 0;
                }

                var status = await engine.GetStatusAsync(cancellation.Token).ConfigureAwait(false);
                var gameVersion = GameVersionOf(status);
                var environment = EnvironmentOf(status);
                var layout = new LayoutResolver().Resolve(status.Build, gameVersion);
                var legacyPositional = args.Length > 1 && int.TryParse(args[1], out _);
                var summaryMode = args.Contains("--summary", StringComparer.Ordinal);
                var xrefMode = args.Contains("--xref", StringComparer.Ordinal);
                var calibrationMode = args.Contains("--calibration", StringComparer.Ordinal);
                var uidMode = args.Contains("--uid", StringComparer.Ordinal);
                var personMode = args.Contains("--person", StringComparer.Ordinal);

                if (summaryMode || xrefMode || calibrationMode || uidMode || (!legacyPositional && !personMode))
                {
                    if (layout is null)
                    {
                        Console.WriteLine(ToJson(new
                        {
                            mode = "summary",
                            error = "layout_not_found",
                            game_version = gameVersion,
                            build = status.Build,
                            process_metadata = ProcessMetadataJson(environment),
                        }));
                        return 3;
                    }

                    try
                    {
                        using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                        var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                        var locatedLimit = Math.Max(1, IntFlag(args, "--located", 800));
                        var sampleCount = Math.Max(1, IntFlag(args, "--samples", 60));
                        var located = locator.FindPlayers(layout, locatedLimit, TimeSpan.FromSeconds(45));

                        if (uidMode)
                        {
                            // Phase 8：只做可行性调查，不建立 UID 索引，也不改生产路径。
                            var uidOffset = (ulong)layout["OBJ_DUNI"];
                            var factsReader = new PlayerRecordFactsReader(memory, layout);
                            var facts = located.Select(factsReader.Read).ToList();
                            var zero = 0;
                            var sentinel = 0;
                            var rawValid = 0;
                            var unreadable = 0;
                            var min = uint.MaxValue;
                            var max = 0u;
                            foreach (var record in located)
                            {
                                try
                                {
                                    var raw = memory.UInt32(record.Db + uidOffset);
                                    if (raw == 0)
                                    {
                                        zero++;
                                    }
                                    else if (raw == 0xFFFF_FFFF)
                                    {
                                        sentinel++;
                                    }
                                    else
                                    {
                                        rawValid++;
                                        min = Math.Min(min, raw);
                                        max = Math.Max(max, raw);
                                    }
                                }
                                catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                                {
                                    unreadable++;
                                }
                            }

                            var present = facts.Where(item => item.Uid is not null).ToList();
                            var groups = present.GroupBy(item => item.Uid!.Value)
                                .Where(group => group.Count() > 1)
                                .ToList();
                            var duplicateGroups = groups
                                .OrderByDescending(group => group.Count())
                                .Take(20)
                                .Select(group => new
                                {
                                    uid = group.Key,
                                    count = group.Count(),
                                    records = group.Take(5).Select(item => new
                                    {
                                        name = BuildName(item),
                                        date_of_birth = FormatDate(item.DateOfBirth),
                                        club = item.ClubName,
                                    }).ToArray(),
                                })
                                .ToArray();

                            var sampleIndexes = PersonCalibrationEngine.SelectEvenly(
                                Enumerable.Range(0, located.Count).ToList(),
                                Math.Min(60, located.Count));
                            var uidChanged = 0;
                            var nameChanged = 0;
                            foreach (var sampleIndex in sampleIndexes)
                            {
                                try
                                {
                                    var db = located[sampleIndex].Db;
                                    var first = memory.UInt32(db + uidOffset);
                                    var firstName = memory.NestedString(located[sampleIndex].Person + (ulong)layout["PERO_COMMON_NAME"]);
                                    Thread.Sleep(30);
                                    var second = memory.UInt32(db + uidOffset);
                                    var secondName = memory.NestedString(located[sampleIndex].Person + (ulong)layout["PERO_COMMON_NAME"]);
                                    if (first != second)
                                    {
                                        uidChanged++;
                                    }

                                    if (!string.Equals(firstName, secondName, StringComparison.Ordinal))
                                    {
                                        nameChanged++;
                                    }
                                }
                                catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                                {
                                    // 单条读取失败不计入稳定性样本。
                                }
                            }

                            Console.WriteLine(ToJson(new
                            {
                                mode = "uid-audit",
                                game_version = gameVersion,
                                build = status.Build,
                                layout_name = layout.Name,
                                field = new
                                {
                                    name = "OBJ_DUNI",
                                    offset = $"0x{uidOffset:X}",
                                    read_type = "u32",
                                    relative_to = "每条属性记录的 DB 块",
                                },
                                located_total = located.Count,
                                raw = new
                                {
                                    valid = rawValid,
                                    zero,
                                    sentinel,
                                    unreadable,
                                    min = rawValid > 0 ? $"0x{min:X8}" : null,
                                    max = rawValid > 0 ? $"0x{max:X8}" : null,
                                },
                                uid_present = present.Count,
                                uid_missing = facts.Count(item => item.Uid is null),
                                distinct_uid = present.Select(item => item.Uid!.Value).Distinct().Count(),
                                duplicate_uid_groups = groups.Count,
                                duplicate_records = groups.Sum(group => group.Count()),
                                duplicate_groups = duplicateGroups,
                                stability = new
                                {
                                    sampled = sampleIndexes.Count,
                                    uid_changed = uidChanged,
                                    name_sample_changed = nameChanged,
                                    reads_per_record = 2,
                                    delay_ms = 30,
                                },
                                cross_save = "unknown",
                                lifecycle = "unknown",
                                notes = new[]
                                {
                                    "UID 位于每条属性记录自身的 DB 块，无法在不扫描记录的情况下独立取得。",
                                    "跨存档是否区分 UID、UID 是否随转会/退役变化，本阶段未取得证据。",
                                },
                            }));
                            return 0;
                        }

                        if (calibrationMode)
                        {
                            var readCount = Math.Max(2, IntFlag(args, "--reads", 3));
                            var report = new PersonCalibrationEngine(memory).Run(
                                PersonLayoutCandidate.Fm27_1_20261125,
                                located.Select(player => player.Person).ToList(),
                                environment,
                                new PersonCalibrationOptions(readCount, sampleCount, locatedLimit, 0, false, false));
                            Console.WriteLine(ToJson(new
                            {
                                mode = "calibration",
                                game_version = gameVersion,
                                build = status.Build,
                                layout_name = layout.Name,
                                located_total = report.LocatedTotal,
                                sampled = report.Sampled,
                                name_valid = report.NameValidCount,
                                date_valid = report.DateValidCount,
                                structurally_valid = report.StructurallyValidCount,
                                unstable = report.UnstableCount,
                                confidence = report.Confidence,
                                verification_status = report.VerificationStatus.ToString(),
                                failure_reason_counts = report.FailureReasonCounts,
                                mark_verified = false,
                            }));
                            return report.VerificationStatus == CandidateVerificationStatus.Unstable ? 3 : 0;
                        }

                        var summary = new PersonDiagnosticsCollector(memory, layout).Collect(
                            located,
                            PersonLayoutCandidate.Fm27_1_20261125,
                            environment,
                            sampleCount);

                        if (xrefMode)
                        {
                            Console.WriteLine(ToJson(new
                            {
                                mode = "xref",
                                game_version = gameVersion,
                                build = status.Build,
                                layout_name = layout.Name,
                                located_total = summary.LocatedCount,
                                sampled = summary.SampledCount,
                                attribute_link_unique = summary.AttributeLinkUniqueCount,
                                attribute_link_success_rate = summary.AttributeLinkSuccessRate,
                                conflict_count = summary.ConflictCount,
                                link_status_counts = summary.LinkStatusCounts,
                                verified_count = summary.VerifiedCount,
                                verified_note = summary.VerifiedNote,
                            }));
                            return 0;
                        }

                        Console.WriteLine(ToJson(new
                        {
                            mode = "summary",
                            observed_at = summary.ObservedAt.ToString("O"),
                            game_version = gameVersion,
                            build = status.Build,
                            plugin_version = status.PluginVersion,
                            layout_name = summary.LayoutName,
                            process_metadata = ProcessMetadataJson(environment),
                            located_count = summary.LocatedCount,
                            sampled = summary.SampledCount,
                            valid_object_count = summary.ValidObjectCount,
                            invalid_pointer_count = summary.InvalidPointerCount,
                            name_read_count = summary.NameReadCount,
                            name_read_success_rate = summary.NameReadSuccessRate,
                            date_of_birth_read_count = summary.DateOfBirthReadCount,
                            date_of_birth_read_success_rate = summary.DateOfBirthReadSuccessRate,
                            attribute_link_unique = summary.AttributeLinkUniqueCount,
                            attribute_link_success_rate = summary.AttributeLinkSuccessRate,
                            conflict_count = summary.ConflictCount,
                            verified_count = summary.VerifiedCount,
                            verified_note = summary.VerifiedNote,
                            link_status_counts = summary.LinkStatusCounts,
                            full_memory_dump = false,
                            mark_verified = false,
                        }));
                        return 0;
                    }
                    catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                    {
                        Console.Error.WriteLine("无法读取进程内存");
                        return 3;
                    }
                }

                // 旧版行为：转储一条球员记录（非零指针与内联 ASCII 串）。
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                var index = personMode
                    ? IntFlag(args, "--person", 0)
                    : args.Length > 1 && int.TryParse(args[1], out var parsedIndex) ? parsedIndex : 0;
                var length = IntFlag(args, "--length",
                    args.Length > 2 && int.TryParse(args[2], out var parsedLength) ? parsedLength : 0x3C8);
                using var legacyMemory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var legacyLocator = new ScoutMind.FMReader.Engine.HeapObjectLocator(legacyMemory);
                var players = legacyLocator.FindPlayers(layout, index + 1, TimeSpan.FromSeconds(30));
                var player = players.Skip(index).FirstOrDefault();
                if (player is null || player.Person == 0)
                {
                    Console.Error.WriteLine("没有定位到该序号的球员");
                    return 3;
                }

                var buffer = new byte[length];
                var ok = legacyMemory.TryReadBlock(player.Person, buffer, length);
                var pointers = new List<object>();
                for (var i = 0; ok && i + 8 <= length; i += 8)
                {
                    var value = BitConverter.ToUInt64(buffer, i);
                    if (value != 0)
                    {
                        pointers.Add(new { offset = $"0x{i:X}", value = $"0x{value:X}" });
                    }
                }

                var strings = new List<object>();
                var text = new System.Text.StringBuilder();
                var start = 0;
                for (var i = 0; ok && i <= length; i++)
                {
                    var b = i < length ? buffer[i] : (byte)0;
                    if (b is >= 0x20 and <= 0x7E)
                    {
                        if (text.Length == 0)
                        {
                            start = i;
                        }

                        text.Append((char)b);
                    }
                    else
                    {
                        if (text.Length >= 3)
                        {
                            strings.Add(new { offset = $"0x{start:X}", text = text.ToString() });
                        }

                        text.Clear();
                    }
                }

                Console.WriteLine(ToJson(new
                {
                    person = $"0x{player.Person:X}",
                    block = $"0x{player.Block:X}",
                    ca = legacyMemory.UInt16(player.Block + (ulong)layout["PLAO_CA"]),
                    dob_year = FmDate.Decode(legacyMemory.UInt32(player.Person + (ulong)layout["PERO_DOB"])).Year,
                    length,
                    read_ok = ok,
                    pointer_count = pointers.Count,
                    pointers = pointers.Take(40),
                    strings = strings.Take(20),
                }));
                return 0;
            }

            default:
                Console.Error.WriteLine("用法：ScoutMind.FMReader.Diag [status|probe|scan|foot]");
                return 64;
        }
    }

    private static string? FlagValue(string[] args, string flag)
    {
        var index = Array.IndexOf(args, flag);
        if (index < 0 || index + 1 >= args.Length)
        {
            return null;
        }

        var value = args[index + 1];
        return value.StartsWith("--", StringComparison.Ordinal) ? null : value;
    }

    private static int IntFlag(string[] args, string flag, int fallback) =>
        int.TryParse(FlagValue(args, flag), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)
            ? parsed
            : fallback;

    private static Dictionary<ulong, int> BuildIndexMap(IReadOnlyList<LocatedObject> located)
    {
        var map = new Dictionary<ulong, int>(located.Count);
        for (var index = 0; index < located.Count; index++)
        {
            map.TryAdd(located[index].Address, index);
        }

        return map;
    }

    private static string? BuildName(PlayerRecordFacts facts) =>
        BuildName(facts.FirstName, facts.SecondName, facts.CommonName);

    private static string? BuildName(string? first, string? second, string? common)
    {
        if (!string.IsNullOrWhiteSpace(common))
        {
            return common;
        }

        var joined = string.Join(" ", new[] { first, second }.Where(part => !string.IsNullOrWhiteSpace(part)));
        return string.IsNullOrWhiteSpace(joined) ? null : joined;
    }

    private static bool NameMatches(PlayerRecordFacts facts, string filter)
    {
        var target = AttributeRecordLinker.NormalizeName(filter);
        if (target.Length == 0)
        {
            return false;
        }

        var values = new[]
        {
            facts.CommonName,
            facts.FirstName,
            facts.SecondName,
            Combine(facts.FirstName, facts.SecondName),
            Combine(facts.SecondName, facts.FirstName),
        };
        return values.Any(value => value is not null
                                   && AttributeRecordLinker.NormalizeName(value) == target);

        static string? Combine(string? first, string? second) =>
            string.IsNullOrWhiteSpace(first) || string.IsNullOrWhiteSpace(second)
                ? null
                : $"{first} {second}";
    }

    private static object IdentityJson(PersonIdentityFields identity) => new
    {
        name = BuildName(identity.FirstName, identity.SecondName, identity.CommonName),
        first_name = identity.FirstName,
        second_name = identity.SecondName,
        common_name = identity.CommonName,
        date_of_birth = FormatDate(identity.DateOfBirth),
        club = identity.ClubName,
        uid = identity.Uid,
    };

    private static string? FormatDate(DateOnly? value) =>
        value?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

    private static object LinkCandidateJson(
        AttributeLinkCandidate candidate,
        IReadOnlyDictionary<ulong, int> indexOf,
        bool includePointers) => new
    {
        record_index = indexOf.TryGetValue(candidate.RecordPointer, out var index) ? index : (int?)null,
        record_pointer = includePointers ? $"0x{candidate.RecordPointer:X}" : null,
        name = BuildName(candidate.Facts),
        first_name = candidate.Facts.FirstName,
        second_name = candidate.Facts.SecondName,
        common_name = candidate.Facts.CommonName,
        date_of_birth = FormatDate(candidate.Facts.DateOfBirth),
        ca = candidate.Facts.Ca,
        pa = candidate.Facts.Pa,
        club = candidate.Facts.ClubName,
        uid = candidate.Facts.Uid,
        missing_fields = candidate.Facts.MissingFields,
        reasons = candidate.Reasons,
        comparisons = candidate.Comparisons.Select(item => new
        {
            field = item.Field,
            target_value = item.TargetValue,
            candidate_value = item.CandidateValue,
            applicable = item.Applicable,
            matched = item.Matched,
        }).ToArray(),
    };

    private static string? GameVersionOf(ScoutMind.FMReader.Engine.FmEngineStatus status) =>
        status.Gate?.Layout is { Length: > 0 } gateLayout
            ? gateLayout.Replace("FM", string.Empty, StringComparison.Ordinal).Replace('_', '.')
            : status.PluginVersion;

    private static CalibrationEnvironment EnvironmentOf(ScoutMind.FMReader.Engine.FmEngineStatus status) =>
        new(
            status.ProcessId,
            string.IsNullOrWhiteSpace(status.ProcessPath) ? null : Path.GetFileNameWithoutExtension(status.ProcessPath),
            GameVersionOf(status),
            status.Build,
            status.PluginVersion,
            status.Gate?.Status.ToString(),
            status.Gate?.AllowScan == true,
            status.AccessDenied);

    private static object ProcessMetadataJson(CalibrationEnvironment environment) => new
    {
        process_id = environment.ProcessId,
        process_name = environment.ProcessName,
        plugin_version = environment.PluginVersion,
        gate_status = environment.GateStatus,
        allow_scan = environment.AllowScan,
        access_denied = environment.AccessDenied,
    };

    private static string? ReadNationName(ScoutMind.FMReader.Probes.IMemorySource memory, ScoutMind.FMReader.Layouts.ILayout layout, ulong person)
    {
        var nation = memory.Pointer(person + layout["PERO_NATION"]);
        if (nation == 0)
        {
            return null;
        }

        return memory.IndirectString(nation + layout["NATION_NAME"])
               ?? memory.IndirectString(nation + layout["NATION_SHORT_NAME"]);
    }

    private static string ToJson(object value) =>
        JsonSerializer.Serialize(value, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() },
        });
}
