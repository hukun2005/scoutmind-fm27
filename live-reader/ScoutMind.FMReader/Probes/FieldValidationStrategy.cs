namespace ScoutMind.FMReader.Probes;

/// <summary>字段级验证策略（SM-056）：每个字段独立声明类型、比较方式与门槛。</summary>
/// <param name="DataType">Integer / Numeric / Date / String / Enum / Boolean。</param>
/// <param name="ObjectType">player / person / contract / club / team。</param>
/// <param name="ComparisonStrategy">exact / numeric / date。</param>
/// <param name="NumericTolerance">数值比较的绝对容差；非数值字段为 0。</param>
/// <param name="MinimumSamples">至少多少个有效配对样本。</param>
/// <param name="MinimumUniqueObjects">至少多少个独立对象。</param>
/// <param name="MinimumUniqueObservations">至少多少个独立观测时间。</param>
/// <param name="AllowedMismatchRate">允许的异常比例；超过才可能 Rejected。</param>
/// <param name="NullPolicy">empty / sentinel / reject。</param>
/// <param name="SentinelPolicy">说明未初始化/哨兵值如何处理。</param>
/// <param name="EvidenceRequirements">升级到 Verified 需要的证据。</param>
public sealed record FieldValidationStrategy(
    string DataType,
    string ObjectType,
    string ComparisonStrategy,
    double NumericTolerance,
    int MinimumSamples,
    int MinimumUniqueObjects,
    int MinimumUniqueObservations,
    double AllowedMismatchRate,
    string NullPolicy,
    string SentinelPolicy,
    string EvidenceRequirements);

/// <summary>按字段给出策略，避免所有字段共享同一套门槛。</summary>
public static class FieldValidationStrategies
{
    /// <summary>为一个字段解析策略；未知字段按数据类型给保守默认。</summary>
    public static FieldValidationStrategy For(FieldSpec spec)
    {
        var name = spec.Field;
        var objectType = ObjectTypeOf(spec.RelativeTo);
        if (name is "ability.ca" or "ability.pa")
        {
            return new("Integer", "player", "numeric", 0, 3, 3, 2, 0.0, "reject", "空值不计数",
                "CA/PA 在游戏界面不可见，最多 Candidate");
        }
        if (name == "contract.wage")
        {
            return new("Integer", "contract", "numeric", 0, 3, 2, 2, 0.02, "reject", "0 需要界面确认",
                "至少 3 个样本、2 个独立对象，且界面显示工资");
        }
        if (name == "contract.expiry")
        {
            return new("Date", "contract", "date", 0, 2, 2, 2, 0.05, "empty", "全 0/全 1 按未设置",
                "界面日期 + 原始值配对；异常合同类型单独分组，最多 Candidate");
        }
        if (name is "identity.dob")
        {
            return new("Date", "person", "date", 0, 2, 2, 1, 0.0, "empty", "0 按未设置",
                "界面生日与原始日期一致");
        }
        if (name.StartsWith("identity.", StringComparison.Ordinal) || name is "club.name" or "nation.name")
        {
            return new("String", objectType, "exact", 0, 2, 2, 1, 0.02, "empty", "空字符串不计样本",
                "界面文本一致；大小写/空白按 trim 后精确比较");
        }
        if (name is "team.type" or "team.squad_level" or "contract.status")
        {
            return new("Enum", objectType, "exact", 0, 3, 2, 2, 0.02, "reject", "0xFF 视为未定义",
                "界面语义核对；仅按上游注释不能 Verified");
        }
        if (spec.DataType.Contains("日期", StringComparison.Ordinal))
        {
            return new("Date", objectType, "date", 0, 2, 2, 1, 0.02, "empty", "哨兵值不计数",
                "界面日期配对");
        }
        if (spec.DataType.Contains('u', StringComparison.OrdinalIgnoreCase)
            || spec.DataType.Contains("int", StringComparison.OrdinalIgnoreCase))
        {
            return new("Integer", objectType, "numeric", 0, 3, 2, 2, 0.02, "reject", "0 需确认",
                "至少 3 个样本、2 个对象");
        }
        return new("String", objectType, "exact", 0, 2, 2, 1, 0.02, "empty", "空值不计数",
            "界面文本配对");
    }

    private static string ObjectTypeOf(string relativeTo) => relativeTo switch
    {
        "person" => "person",
        "block" => "player",
        "contract" => "contract",
        "club" => "club",
        "team" => "team",
        _ => relativeTo,
    };
}
