namespace ScoutMind.FMReader.Layouts;

/// <summary>
/// FM27 27.1 布局（候选）。
///
/// 起点是 27.0 的偏移表，但**每个字段都是 <see cref="FieldStatus.Unknown"/>**：上游从未在 27.1 上核对过，
/// 这些数字只是"待验证假设"。只有把某个字段对着游戏内界面核对通过，才允许用
/// <see cref="LayoutBase.Mark"/> 升级为 <see cref="FieldStatus.Verified"/>。
///
/// 这份布局与 <see cref="FM27_0_Layout"/> 完全独立：改这里不会影响 27.0。
/// </summary>
public sealed class FM27_1_Layout : LayoutBase
{
    /// <summary>布局名。</summary>
    public const string LayoutName = "FM27_1";

    private const string Source = "由 FM27_0 复制而来，未在 FM 27.1 上逐类核对";

    /// <summary>创建布局。</summary>
    public FM27_1_Layout()
        : base(LayoutName, major: 27, minor: 1, FM27_0_Layout.OffsetsTable(), FieldStatus.Pending, Source)
    {
        // 扫描闸门字段：这些字段都能在游戏界面核对（CA/PA 不在其中——UI 不可见，
        // 它们只能靠与 FMSuperScout 的一致性或内部检查，因此永远不阻塞扫描）。
        Require(
            "PERO_FIRST_NAME",
            "PERO_SECOND_NAME",
            "PERO_COMMON_NAME",
            "PERO_DOB",
            "PLAO_HEIGHT",
            "PLAO_POSITIONS",
            "PERO_NATION",
            "CON_EXPIRY",
            "CON_SQUAD_NUMBER",
            "CON_TEAM",
            "TEAM_CLUB",
            "CLUB_NAME");
    }
}
