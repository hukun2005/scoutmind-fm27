using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Probes;

/// <summary>
/// 一个可验证字段的规格：读哪里、什么类型、合理范围、怎么验证、当前状态。
///
/// 这份表是"字段级证据"的唯一来源：报告、文档、测试都读它，避免三处各写一套。
/// </summary>
/// <param name="Field">字段名（对应布局键，或 <c>derived.*</c> 表示派生字段）。</param>
/// <param name="Group">分组：core / technical / mental / physical / position / nation / team / club / loan。</param>
/// <param name="LayoutKey">布局里承载该字段的偏移键。</param>
/// <param name="RelativeTo">相对哪个基址：block / person / db / contract / team / club。</param>
/// <param name="DataType">数据类型描述。</param>
/// <param name="Range">合理范围描述。</param>
/// <param name="Method">验证方式。</param>
/// <param name="Status">当前状态。</param>
/// <param name="Kind">证据种类。</param>
/// <param name="Note">说明。</param>
public sealed record FieldSpec(
    string Field,
    string Group,
    string? LayoutKey,
    string RelativeTo,
    string DataType,
    string Range,
    string Method,
    FieldStatus Status,
    EvidenceKind Kind,
    string? Note = null);

/// <summary>字段规格表。</summary>
public static class FieldSpecs
{
    /// <summary>技术属性（键与 <c>upstream-attributes.json</c> 一致）。</summary>
    public static readonly string[] Technical =
    {
        "Corners", "Crossing", "Dribbling", "Finishing", "FirstTouch", "FreeKicks", "Heading",
        "LongShots", "LongThrows", "Marking", "Passing", "PenaltyTaking", "Tackling", "Technique",
    };

    /// <summary>精神属性。</summary>
    public static readonly string[] Mental =
    {
        "Aggression", "Anticipation", "Bravery", "Composure", "Concentration", "Decisions",
        "Determination", "Flair", "Leadership", "OffTheBall", "Positioning", "Teamwork",
        "Vision", "WorkRate",
    };

    /// <summary>身体属性。</summary>
    public static readonly string[] Physical =
    {
        "Acceleration", "Agility", "Balance", "JumpingReach", "NaturalFitness", "Pace",
        "Stamina", "Strength",
    };

    /// <summary>位置字节（下标即偏移）。</summary>
    public static readonly (string Key, int Offset)[] Positions =
    {
        ("GK", 0x00), ("SW", 0x01), ("DL", 0x02), ("DC", 0x03), ("DR", 0x04), ("DM", 0x05),
        ("ML", 0x06), ("MC", 0x07), ("MR", 0x08), ("AML", 0x09), ("AMC", 0x0A), ("AMR", 0x0B),
        ("ST", 0x0C), ("WBL", 0x0D), ("WBR", 0x0E),
    };

    /// <summary>生成完整规格表。</summary>
    /// <param name="layout">布局（决定字段是否存在）。</param>
    /// <returns>规格列表。</returns>
    public static IReadOnlyList<FieldSpec> Build(ILayout layout)
    {
        ArgumentNullException.ThrowIfNull(layout);
        var specs = new List<FieldSpec>
        {
            Spec(layout, "identity.name", "core", "PERO_COMMON_NAME", "person", "嵌套字符串（或姓+名）",
                "2..64 个可打印字符，至少 2 个字母", "可读 + 与 FMSuperScout 导出按姓名+出生年配对"),
            Spec(layout, "identity.dob", "core", "PERO_DOB", "person", "u32 FM 日期（年<<16 | 年内序日）",
                "年 1940..2015，序日 1..366", "解码 + 与导出比对出生年"),
            Spec(layout, "ability.ca", "core", "PLAO_CA", "block", "u16", "1..200", "范围 + 与导出比对（CA 非法按未知处理）"),
            Spec(layout, "ability.pa", "core", "PLAO_PA", "block", "u16", "1..200", "范围 + 与导出比对"),
            Spec(layout, "physical.height", "physical", "PLAO_HEIGHT", "block", "u16（cm）", "0（未设置）或 140..230", "范围 + 与导出比对"),
            Spec(layout, "club.name", "club", "CLUB_NAME", "club", "间接字符串", "2..64 字符，含字母", "可读 + 与导出比对俱乐部名"),
            Spec(layout, "team.current", "team", "CON_TEAM", "contract", "指针 → 球队对象", "可读、8 字节对齐", "指针链可达 + 球队类型范围"),
            Spec(layout, "team.type", "team", "TEAM_TYPE", "team", "u8", "0..20（0=一线队，≥10=青年队，上游注释）",
                "范围检查；语义本身未在 27.1 核对，因此状态保持 Candidate/Pending"),
            Spec(layout, "contract.expiry", "core", "CON_EXPIRY", "contract", "u32 FM 日期", "年 2000..2060，序日 1..366", "解码 + 与导出比对"),
            Spec(layout, "contract.wage", "core", "CON_WEEKLY_WAGE", "contract", "u32（GBP/周）", "≤ 5,000,000", "范围检查"),
            Spec(layout, "contract.status", "core", "CON_STATUS_FLAGS", "contract", "u8 位域", "≠ 0xFF（未定义值）", "范围检查"),
            Spec(layout, "nation.name", "nation", "PERO_NATION", "person", "指针 → 国家对象 → 间接字符串", "2..40 字符", "指针可读 + 名称可读（导出仅作交叉参考）"),
        };

        foreach (var key in Technical) specs.Add(Attribute(layout, key, "technical"));
        foreach (var key in Mental) specs.Add(Attribute(layout, key, "mental"));
        foreach (var key in Physical) specs.Add(Attribute(layout, key, "physical"));
        specs.Add(new FieldSpec(
            "position.familiarity", "position", "PLAO_POSITIONS", "block", "15 × u8",
            "0..20（上游注释：0 表示不熟悉）", "逐字节范围 + 至少一个位置 ≥15（自然位置）",
            layout.Verification("PLAO_POSITIONS").Status,
            layout.Verification("PLAO_POSITIONS").Kind,
            "位置字节的含义来自上游注释，尚未在游戏内逐项核对"));

        // 明确不支持的字段：布局里没有对应偏移，不能编造。
        specs.Add(new FieldSpec(
            "team.parent_club", "team", null, "—", "不存在", "—",
            "无法验证：布局没有 parentClub / loanClub / ownerTeamType",
            FieldStatus.NotSupported, EvidenceKind.None,
            "上游 dump 只给整数 teamType 与当前俱乐部；母队/租借关系只能来自阵容 CSV"));
        specs.Add(new FieldSpec(
            "loan.current_club", "loan", null, "—", "不存在", "—",
            "无法验证：布局没有租借字段", FieldStatus.NotSupported, EvidenceKind.None,
            "租借关系需要 CSV 或外部数据源"));
        specs.Add(new FieldSpec(
            "team.squad_level", "team", "TEAM_TYPE", "team", "u8", "0..20",
            "只能按上游注释映射为一线/预备/青年；语义未核对，因此永远是 Candidate 或 Pending",
            FieldStatus.Pending, EvidenceKind.InternalCheck,
            "梯队语义必须与游戏内球队界面核对后才能升级"));

        return specs;
    }

    /// <summary>汇总每种状态的字段数（报告用）。</summary>
    /// <param name="specs">规格列表。</param>
    /// <returns>状态 → 数量。</returns>
    public static IReadOnlyDictionary<FieldStatus, int> CountByStatus(IReadOnlyList<FieldSpec> specs)
    {
        ArgumentNullException.ThrowIfNull(specs);
        return Enum.GetValues<FieldStatus>()
            .ToDictionary(status => status, status => specs.Count(spec => spec.Status == status));
    }

    private static FieldSpec Spec(
        ILayout layout,
        string field,
        string group,
        string layoutKey,
        string relativeTo,
        string dataType,
        string range,
        string method)
    {
        var exists = layout.Offsets.ContainsKey(layoutKey);
        var verification = exists ? layout.Verification(layoutKey) : null;
        return new FieldSpec(
            field,
            group,
            layoutKey,
            relativeTo,
            dataType,
            range,
            method,
            exists ? verification!.Status : FieldStatus.NotSupported,
            exists ? verification!.Kind : EvidenceKind.None,
            exists ? verification!.Note : null);
    }

    private static FieldSpec Attribute(ILayout layout, string key, string group)
    {
        var exists = layout.Offsets.ContainsKey("PLAO_ATTRS");
        var verification = exists ? layout.Verification("PLAO_ATTRS") : null;
        return new FieldSpec(
            "attr." + key,
            group,
            "PLAO_ATTRS",
            "block",
            "u8（存储值 = 实际值 ×5）",
            "0..20（÷5 之后）",
            "÷5 后范围检查；分组按 FM 惯例，分组本身不是数据",
            exists ? verification!.Status : FieldStatus.NotSupported,
            exists ? verification!.Kind : EvidenceKind.None,
            "属性值来自偏移表 " + key);
    }
}
