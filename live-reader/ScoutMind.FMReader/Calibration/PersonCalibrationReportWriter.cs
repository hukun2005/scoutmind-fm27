using System.Text;
using System.Text.Json;

namespace ScoutMind.FMReader.Calibration;

/// <summary>
/// 校准报告的 JSON / Markdown 输出。
///
/// 默认脱敏：不输出 Person 指针与姓名指针；仅本机诊断时通过 <c>includePointers</c> 保留原始指针。
/// </summary>
public static class PersonCalibrationReportWriter
{
    /// <summary>输出 JSON。</summary>
    /// <param name="report">校准报告。</param>
    /// <param name="includePointers">是否包含原始指针（仅限本机诊断文件）。</param>
    /// <returns>JSON 文本。</returns>
    public static string ToJson(PersonCalibrationReport report, bool includePointers = false)
    {
        ArgumentNullException.ThrowIfNull(report);

        var payload = new
        {
            schema_version = report.SchemaVersion,
            candidate_id = report.CandidateId,
            game_version = report.GameVersion,
            build_number = report.BuildNumber,
            process_metadata = new
            {
                process_id = report.Environment.ProcessId,
                process_name = report.Environment.ProcessName,
                plugin_version = report.Environment.PluginVersion,
                gate_status = report.Environment.GateStatus,
                allow_scan = report.Environment.AllowScan,
                access_denied = report.Environment.AccessDenied,
            },
            calibration_timestamp = report.CalibrationTimestamp.ToString("O"),
            name_field_offsets = report.NameFieldOffsets.Select(offset => $"0x{offset:X}").ToArray(),
            date_of_birth_offset = $"0x{report.DateOfBirthOffset:X}",
            sampling = new
            {
                located_total = report.LocatedTotal,
                sampled = report.Sampled,
                strategy = report.SamplingStrategy,
                read_count = report.ReadCount,
                dry_run = report.DryRun,
            },
            raw_read_evidence = report.Samples.Select(sample => new
            {
                sample_index = sample.SampleIndex,
                person_pointer = includePointers ? $"0x{sample.PersonPointer:X}" : null,
                stable = sample.Stable,
                stability_notes = sample.StabilityNotes,
                reads = sample.Reads.Select(read => new
                {
                    read_index = read.ReadIndex,
                    status = read.Snapshot.Status.ToString(),
                    fields = read.Snapshot.Fields.Select(field => new
                    {
                        kind = field.Kind.ToString(),
                        offset = $"0x{field.Offset:X}",
                        read_type = field.ReadType,
                        raw_value = SanitizeRawValue(field, includePointers),
                        decoded_value = field.DecodedValue,
                        pointer_valid = field.PointerValid,
                        string_valid = field.StringValid,
                        date_valid = field.DateValid,
                        is_valid = field.IsValid,
                        failure_reason = field.FailureReason,
                    }).ToArray(),
                }).ToArray(),
            }).ToArray(),
            candidate_offset_sweep = report.OffsetSweep.Select(row => new
            {
                offset = $"0x{row.Offset:X}",
                readable = row.Readable,
                name_like = row.NameLike,
                distinct = row.Distinct,
                samples = row.Samples,
            }).ToArray(),
            validation_results = new
            {
                sample_count = report.Samples.Count,
                structurally_valid = report.StructurallyValidCount,
                name_valid = report.NameValidCount,
                date_valid = report.DateValidCount,
                unstable = report.UnstableCount,
                failure_reason_counts = report.FailureReasonCounts,
            },
            confidence = report.Confidence,
            verification_status = report.VerificationStatus.ToString(),
            conclusion = report.Conclusion,
            mark_verified = false,
        };

        return JsonSerializer.Serialize(payload, new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
    }

    /// <summary>输出 Markdown 摘要（完全脱敏，不含任何地址）。</summary>
    /// <param name="report">校准报告。</param>
    /// <returns>Markdown 文本。</returns>
    public static string ToMarkdown(PersonCalibrationReport report)
    {
        ArgumentNullException.ThrowIfNull(report);

        var builder = new StringBuilder();
        builder.AppendLine("# FM27 Person 校准报告（真实内存，只读）");
        builder.AppendLine();
        builder.AppendLine($"> 生成时间：{report.CalibrationTimestamp:yyyy-MM-dd HH:mm:ss zzz} · 候选：`{report.CandidateId}` · Schema `{report.SchemaVersion}`");
        builder.AppendLine();
        builder.AppendLine("## 1. 本次运行环境（现场检测，未使用历史记录）");
        builder.AppendLine();
        builder.AppendLine("| 项目 | 值 |");
        builder.AppendLine("| --- | --- |");
        builder.AppendLine($"| 游戏版本 | {Cell(report.GameVersion)} |");
        builder.AppendLine($"| 构建号 | {Cell(report.BuildNumber)} |");
        builder.AppendLine($"| 进程 | {Cell(report.Environment.ProcessName)} (pid {report.Environment.ProcessId?.ToString() ?? "unknown"}) |");
        builder.AppendLine($"| game_plugin.dll | {Cell(report.Environment.PluginVersion)} |");
        builder.AppendLine($"| 版本闸门 | {Cell(report.Environment.GateStatus)} · allow_scan={report.Environment.AllowScan} · access_denied={report.Environment.AccessDenied} |");
        builder.AppendLine();
        builder.AppendLine("## 2. 候选布局");
        builder.AppendLine();
        builder.AppendLine("| 项目 | 值 |");
        builder.AppendLine("| --- | --- |");
        builder.AppendLine($"| 姓名偏移 | {string.Join(" / ", report.NameFieldOffsets.Select(offset => $"0x{offset:X}"))} |");
        builder.AppendLine($"| 生日偏移 | 0x{report.DateOfBirthOffset:X} |");
        builder.AppendLine($"| 抽样 | {report.Sampled}/{report.LocatedTotal}（{report.SamplingStrategy}，每对象读取 {report.ReadCount} 次） |");
        builder.AppendLine();
        builder.AppendLine("## 3. 逐样本证据");
        builder.AppendLine();
        if (report.Samples.Count == 0)
        {
            builder.AppendLine("_本次没有读取任何样本（dry-run 或未定位到对象）。_");
        }
        else
        {
            builder.AppendLine("| # | 名 | 姓 | 常用名 | 生日 | 状态 | 稳定 |");
            builder.AppendLine("| --- | --- | --- | --- | --- | --- | --- |");
            foreach (var sample in report.Samples)
            {
                var fields = sample.First.Fields;
                var names = fields.Where(field => field.Kind == CandidateFieldKind.NestedName).ToList();
                var date = fields.First(field => field.Kind == CandidateFieldKind.DateOfBirth);
                builder.AppendLine($"| {sample.SampleIndex} | {Cell(ValueAt(names, 0))} | {Cell(ValueAt(names, 1))} | {Cell(ValueAt(names, 2))} | {Cell(date.DecodedValue)} | {sample.First.Status} | {(sample.Stable ? "是" : "否")} |");
            }

            var unstable = report.Samples.Where(sample => !sample.Stable).ToList();
            if (unstable.Count > 0)
            {
                builder.AppendLine();
                builder.AppendLine("不稳定样本：");
                builder.AppendLine();
                foreach (var sample in unstable)
                {
                    builder.AppendLine($"- 样本 {sample.SampleIndex}：{string.Join("，", sample.StabilityNotes)}");
                }
            }
        }

        builder.AppendLine();
        builder.AppendLine("## 4. 汇总与失败原因");
        builder.AppendLine();
        builder.AppendLine("| 指标 | 值 |");
        builder.AppendLine("| --- | --- |");
        builder.AppendLine($"| 姓名有效 | {report.NameValidCount}/{report.Samples.Count} |");
        builder.AppendLine($"| 生日有效 | {report.DateValidCount}/{report.Samples.Count} |");
        builder.AppendLine($"| 结构校验通过 | {report.StructurallyValidCount}/{report.Samples.Count} |");
        builder.AppendLine($"| 多次读取不稳定 | {report.UnstableCount} |");
        builder.AppendLine($"| 置信度（结构上限 0.5） | {report.Confidence:0.00} |");
        builder.AppendLine($"| 验证状态 | {report.VerificationStatus} |");
        builder.AppendLine();
        if (report.FailureReasonCounts.Count > 0)
        {
            builder.AppendLine("失败原因码：");
            builder.AppendLine();
            builder.AppendLine("| 原因 | 次数 |");
            builder.AppendLine("| --- | --- |");
            foreach (var pair in report.FailureReasonCounts.OrderByDescending(pair => pair.Value))
            {
                builder.AppendLine($"| {Cell(pair.Key)} | {pair.Value} |");
            }

            builder.AppendLine();
        }

        if (report.OffsetSweep.Count > 0)
        {
            builder.AppendLine("## 5. 候选偏移扫描（参考）");
            builder.AppendLine();
            builder.AppendLine("| 偏移 | 可读 | 像人名 | 去重 | 示例 |");
            builder.AppendLine("| --- | --- | --- | --- | --- |");
            foreach (var row in report.OffsetSweep
                         .OrderByDescending(row => row.NameLike)
                         .ThenByDescending(row => row.Distinct)
                         .Take(8))
            {
                builder.AppendLine($"| 0x{row.Offset:X} | {row.Readable} | {row.NameLike} | {row.Distinct} | {Cell(string.Join("；", row.Samples))} |");
            }

            builder.AppendLine();
        }

        builder.AppendLine("## 6. 结论与限制");
        builder.AppendLine();
        builder.AppendLine(report.Conclusion);
        builder.AppendLine();
        builder.AppendLine("- 本报告只做只读观测，未写入游戏内存、未修改保护属性、未注入 DLL。");
        builder.AppendLine("- 结构校验通过、多次读取稳定都**不等于**人工核对；未经真实 FM27 人工核对不得 Mark(Verified)。");
        builder.AppendLine("- 上传时使用脱敏版本：不包含 Person 指针、姓名指针或完整内存地址列表。");
        builder.AppendLine();
        builder.AppendLine("复现（在已加载存档的 FM27 上，只读）：");
        builder.AppendLine();
        builder.AppendLine("```text");
        builder.AppendLine("ScoutMind.FMReader.Diag.exe calibrate --output <sanitized.json> --markdown <report.md>");
        builder.AppendLine("```");

        return builder.ToString();
    }

    private static string? ValueAt(IReadOnlyList<PersonFieldObservation> names, int index) =>
        index < names.Count && names[index].StringValid ? names[index].DecodedValue : null;

    private static string? SanitizeRawValue(PersonFieldObservation field, bool includePointers)
    {
        if (field.RawValue is null)
        {
            return null;
        }

        if (field.Kind == CandidateFieldKind.NestedName && !includePointers)
        {
            return "<redacted>";
        }

        return field.RawValue;
    }

    private static string Cell(string? value) =>
        string.IsNullOrWhiteSpace(value) ? "—" : value.Replace("|", "\\|", StringComparison.Ordinal);
}
