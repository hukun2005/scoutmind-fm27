namespace ScoutMind.FMReader.Layouts;

/// <summary>
/// FM27 27.0 布局：偏移取自上游 FMSuperScout 1.7.3 的 <c>Fields.FM27</c>（上游声称已在 FM 27.0 上钉过，
/// 02-11-2026）。ScoutMind 不覆盖这份布局，只在旁边新增 27.1 的候选布局。
/// </summary>
public sealed class FM27_0_Layout : LayoutBase
{
    /// <summary>布局名。</summary>
    public const string LayoutName = "FM27_0";

    private const string Source = "上游 FMSuperScout 1.7.3 · Fields.FM27 · 上游声明 02-11-2026 于 FM 27.0 核对（ScoutMind 未复现）";

    /// <summary>创建布局。</summary>
    public FM27_0_Layout()
        : base(LayoutName, major: 27, minor: 0, OffsetsTable(), FieldStatus.Candidate, Source, EvidenceKind.UpstreamAgreement)
    {
        Require(
            "OBJ_DUNI",
            "PLAO_CA",
            "PLAO_PA",
            "PLAO_HEIGHT",
            "PLAO_POSITIONS",
            "PLAO_ATTRS",
            "PLAO_TRANSFER_VALUE",
            "PERO_DOB",
            "PERO_FIRST_NAME",
            "PERO_SECOND_NAME",
            "PERO_COMMON_NAME",
            "PERO_FULL_CONTRACT",
            "PERO_NATION",
            "CON_EXPIRY",
            "CON_WEEKLY_WAGE",
            "CON_STATUS_FLAGS",
            "CON_TEAM",
            "TEAM_CLUB",
            "TEAM_TYPE",
            "TEAM_PLAYERS_BEGIN",
            "TEAM_PLAYERS_END",
            "CLUB_NAME",
            "CLUB_TEAMS_BEGIN",
            "CLUB_TEAMS_END");
    }

    /// <summary>该布局的字段偏移表（与上游 <c>Fields</c> 同名同值，逐字抄录，便于比对）。</summary>
    /// <returns>偏移表。</returns>
    public static Dictionary<string, uint> OffsetsTable() => new(StringComparer.Ordinal)
    {
        // 对象头
        ["OBJ_DUNI"] = 0x0C,
        // 动态偏移
        ["PLAYER_OFFSET"] = 0x288,
        ["PLAYER_STAFF_OFFSET"] = 0x380,
        ["STAFF_OFFSET"] = 0x100,
        ["HUMAN_MANAGER_OFFSET"] = 0x440,
        // 球员块
        ["PLAO_CA"] = 0x264,
        ["PLAO_PA"] = 0x266,
        ["PLAO_HOME_REP"] = 0x25E,
        ["PLAO_CUR_REP"] = 0x260,
        ["PLAO_WORLD_REP"] = 0x262,
        ["PLAO_CONDITION"] = 0x258,
        ["PLAO_MORALE"] = 0x26C,
        ["PLAO_HEIGHT"] = 0x22E,
        ["PLAO_POSITIONS"] = 0x150,
        ["PLAO_ATTRS"] = 0x15F,
        ["PLAO_GUIDE_VALUE"] = 0x234,
        ["PLAO_TRANSFER_VALUE"] = 0x238,
        // 个人块
        ["PERO_GENDER"] = 0x19,
        ["PERO_FIRST_NAME"] = 0x50,
        ["PERO_SECOND_NAME"] = 0x58,
        ["PERO_COMMON_NAME"] = 0x60,
        ["PERO_NATION"] = 0x68,
        ["PERO_DOB"] = 0x88,
        ["PERO_FULL_CONTRACT"] = 0xA8,
        // 合同
        ["CON_WEEKLY_WAGE"] = 0x20,
        ["CON_EXPIRY"] = 0x48,
        ["CON_SQUAD_NUMBER"] = 0x5D,
        ["CON_STATUS_FLAGS"] = 0x57,
        ["CON_TEAM"] = 0x10,
        ["CON_JOB"] = 0x26,
        // 国家
        ["NATION_SHORT_NAME"] = 0x20,
        ["NATION_NAME"] = 0x30,
        // 球队
        ["TEAM_TYPE"] = 0x28,
        ["TEAM_CLUB"] = 0x30,
        ["TEAM_PLAYERS_BEGIN"] = 0x38,
        ["TEAM_PLAYERS_END"] = 0x40,
        ["TEAM_MANAGER"] = 0x80,
        ["TEAM_REP"] = 0xA8,
        ["TEAM_COMP"] = 0x50,
        ["TEAM_SCHEDULE"] = 0xA0,
        // 俱乐部
        ["CLUB_TEAMS_BEGIN"] = 0x18,
        ["CLUB_TEAMS_END"] = 0x20,
        ["CLUB_NAME"] = 0xC0,
        ["CLUB_SHORT_NAME"] = 0xC8,
        // 转会（上游记录为 0xC8 字节，未植入 vtable）
        ["DEAL_TO_TEAM"] = 0x08,
        ["DEAL_FROM_TEAM"] = 0x18,
        ["DEAL_SENT1"] = 0x2C,
        ["DEAL_SENT2"] = 0x34,
        ["DEAL_DATE"] = 0x44,
        ["DEAL_STATUS"] = 0x55,
    };
}
