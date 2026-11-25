using System.Text;
using System.Text.Json;
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
                // 只读校准：对已定位的球员对象，逐个候选偏移尝试嵌套字符串解码，按"像人名"的比例排序。
                // 不写任何游戏内存；用于在布局漂移时重新发现姓名字段偏移。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                var count = args.Length > 1 && int.TryParse(args[1], out var parsedCount) ? parsedCount : 80;
                var maxOffset = args.Length > 2 && int.TryParse(args[2], out var parsedMax) ? parsedMax : 0x400;
                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var players = locator.FindPlayers(layout, count, TimeSpan.FromSeconds(40));
                var rows = new List<(int Off, int Readable, int NameLike, int Distinct, List<string> Samples)>();
                for (var off = 0; off <= maxOffset; off += 8)
                {
                    var readable = 0;
                    var nameLike = 0;
                    var distinct = new HashSet<string>(StringComparer.Ordinal);
                    var samples = new List<string>();
                    foreach (var player in players)
                    {
                        string? value;
                        try
                        {
                            value = memory.NestedString(player.Person + (ulong)off);
                        }
                        catch (ScoutMind.FMReader.Probes.MemoryUnreadableException)
                        {
                            continue;
                        }

                        if (string.IsNullOrWhiteSpace(value))
                        {
                            continue;
                        }

                        readable++;
                        var plausible = value.Length is >= 2 and <= 40
                                        && value.All(ch => char.IsLetter(ch) || ch is ' ' or '\'' or '-' or '.');
                        if (plausible)
                        {
                            nameLike++;
                            distinct.Add(value);
                            if (samples.Count < 5)
                            {
                                samples.Add(value);
                            }
                        }
                    }

                    if (readable > 0)
                    {
                        rows.Add((off, readable, nameLike, distinct.Count, samples));
                    }
                }

                Console.WriteLine(ToJson(new
                {
                    players = players.Count,
                    current_offsets = new
                    {
                        PERO_FIRST_NAME = layout["PERO_FIRST_NAME"],
                        PERO_SECOND_NAME = layout["PERO_SECOND_NAME"],
                        PERO_COMMON_NAME = layout["PERO_COMMON_NAME"],
                    },
                    name_field_probe = players.Take(8).Select(player => new
                    {
                        person = $"0x{player.Person:X}",
                        first_ptr = $"0x{memory.Pointer(player.Person + (ulong)layout["PERO_FIRST_NAME"]):X}",
                        second_ptr = $"0x{memory.Pointer(player.Person + (ulong)layout["PERO_SECOND_NAME"]):X}",
                        common_ptr = $"0x{memory.Pointer(player.Person + (ulong)layout["PERO_COMMON_NAME"]):X}",
                        first = memory.NestedString(player.Person + (ulong)layout["PERO_FIRST_NAME"]),
                        second = memory.NestedString(player.Person + (ulong)layout["PERO_SECOND_NAME"]),
                        ca = memory.UInt16(player.Block + (ulong)layout["PLAO_CA"]),
                    }),
                    candidates = rows.OrderByDescending(row => row.NameLike)
                        .ThenByDescending(row => row.Distinct)
                        .Take(25)
                        .Select(row => new
                        {
                            offset = $"0x{row.Off:X}",
                            readable = row.Readable,
                            name_like = row.NameLike,
                            distinct = row.Distinct,
                            samples = row.Samples,
                        }),
                }));
                return 0;
            }

            case "xref":
            {
                // 在每条球员记录的范围内寻找"指向完整 person 对象"的指针：
                // 对记录内每个 8 字节槽读指针 T，再用旧布局的姓名偏移尝试解码，命中即为可用的 person 基址。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
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
                // 只读转储一条球员记录（默认 0x3C8 字节）：非零指针与内联 ASCII 串，用于判断姓名是否内联或改址。
                var layout = new LayoutResolver().Resolve("26620374", "27.1");
                if (layout is null)
                {
                    Console.Error.WriteLine("未登记的构建");
                    return 3;
                }

                var index = args.Length > 1 && int.TryParse(args[1], out var parsedIndex) ? parsedIndex : 0;
                var length = args.Length > 2 && int.TryParse(args[2], out var parsedLength) ? parsedLength : 0x3C8;
                using var memory = ScoutMind.FMReader.Engine.WinMemorySource.Open();
                var locator = new ScoutMind.FMReader.Engine.HeapObjectLocator(memory);
                var players = locator.FindPlayers(layout, index + 1, TimeSpan.FromSeconds(30));
                var player = players.Skip(index).FirstOrDefault();
                if (player is null || player.Person == 0)
                {
                    Console.Error.WriteLine("没有定位到该序号的球员");
                    return 3;
                }

                var buffer = new byte[length];
                var ok = memory.TryReadBlock(player.Person, buffer, length);
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
                    ca = memory.UInt16(player.Block + (ulong)layout["PLAO_CA"]),
                    dob_year = FmDate.Decode(memory.UInt32(player.Person + (ulong)layout["PERO_DOB"])).Year,
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
