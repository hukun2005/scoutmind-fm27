using ScoutMind.Contracts;

namespace ScoutMind.Reader;

/// <summary>
/// 一次已发生的状态迁移记录，用于诊断与排错。
/// </summary>
/// <param name="From">迁移前状态。</param>
/// <param name="To">迁移后状态。</param>
/// <param name="At">迁移发生的 UTC 时间。</param>
public sealed record StateTransition(ReaderState From, ReaderState To, DateTimeOffset At);

/// <summary>
/// 状态机拒绝一次非法迁移。任何失败状态（Unknown / Unsupported / ProbeFailed）都是终态，
/// 调用方收到该异常后必须停止读取。
/// </summary>
public sealed class InvalidStateTransitionException : Exception
{
    /// <summary>创建异常。</summary>
    /// <param name="from">当前状态。</param>
    /// <param name="to">被拒绝的目标状态。</param>
    public InvalidStateTransitionException(ReaderState from, ReaderState to)
        : base($"非法状态迁移：{from} → {to}。")
    {
        From = from;
        To = to;
    }

    /// <summary>当前状态。</summary>
    public ReaderState From { get; }

    /// <summary>被拒绝的目标状态。</summary>
    public ReaderState To { get; }
}

/// <summary>
/// 显式状态机：<c>NotFound → Detected → VersionIdentified → Compatible → ProbePassed → ScanCompleted</c>，
/// 失败分支为 <c>Unknown</c> / <c>Unsupported</c> / <c>ProbeFailed</c>，且都是终态。
/// 允许的迁移边固定写在 <see cref="AllowedEdges"/> 中，任何未列出的迁移都会抛异常并记录诊断。
/// </summary>
public sealed class StateMachine
{
    private static readonly IReadOnlyDictionary<ReaderState, ReaderState[]> AllowedEdges =
        new Dictionary<ReaderState, ReaderState[]>
        {
            [ReaderState.NotFound] = new[] { ReaderState.Detected },
            [ReaderState.Detected] = new[] { ReaderState.VersionIdentified, ReaderState.Unknown, ReaderState.Unsupported },
            [ReaderState.VersionIdentified] = new[] { ReaderState.Compatible, ReaderState.Unknown, ReaderState.Unsupported },
            [ReaderState.Compatible] = new[] { ReaderState.ProbePassed, ReaderState.ProbeFailed, ReaderState.Unsupported },
            [ReaderState.ProbePassed] = new[] { ReaderState.ScanCompleted, ReaderState.ProbeFailed },
            [ReaderState.ScanCompleted] = Array.Empty<ReaderState>(),
            [ReaderState.Unsupported] = Array.Empty<ReaderState>(),
            [ReaderState.Unknown] = Array.Empty<ReaderState>(),
            [ReaderState.ProbeFailed] = Array.Empty<ReaderState>(),
        };

    private readonly List<string> _diagnostics = new();
    private readonly List<StateTransition> _history = new();

    /// <summary>创建状态机。</summary>
    /// <param name="initial">初始状态，默认 <see cref="ReaderState.NotFound"/>。</param>
    public StateMachine(ReaderState initial = ReaderState.NotFound)
    {
        Current = initial;
        if (initial != ReaderState.NotFound)
        {
            _diagnostics.Add($"状态机从非初始状态 {initial} 启动（仅恢复或测试场景使用）。");
        }
    }

    /// <summary>当前状态。</summary>
    public ReaderState Current { get; private set; }

    /// <summary>状态机产生的诊断信息，包含每次成功与失败的迁移。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <summary>已完成的迁移历史。</summary>
    public IReadOnlyList<StateTransition> History => _history;

    /// <summary>判断状态是否为失败终态；失败状态一律禁止读取。</summary>
    /// <param name="state">待判断的状态。</param>
    /// <returns>失败终态返回 <c>true</c>。</returns>
    public static bool IsFailureState(ReaderState state) =>
        state is ReaderState.Unknown or ReaderState.Unsupported or ReaderState.ProbeFailed;

    /// <summary>判断从当前状态是否可以迁移到目标状态。</summary>
    /// <param name="next">目标状态。</param>
    /// <returns>迁移合法时返回 <c>true</c>。</returns>
    public bool CanTransitionTo(ReaderState next) =>
        AllowedEdges.TryGetValue(Current, out var edges) && edges.Contains(next);

    /// <summary>尝试迁移但不改变状态，用于在不抛异常的情况下获得拒绝原因。</summary>
    /// <param name="next">目标状态。</param>
    /// <param name="reason">拒绝原因；允许迁移时为 <c>null</c>。</param>
    /// <returns>允许迁移时返回 <c>true</c>。</returns>
    public bool TryTransitionTo(ReaderState next, out string? reason)
    {
        if (CanTransitionTo(next))
        {
            reason = null;
            return true;
        }

        reason = IsFailureState(Current)
            ? $"当前状态 {Current} 是失败终态，禁止任何后续迁移（目标 {next}）。"
            : $"状态 {Current} 不允许迁移到 {next}。";
        return false;
    }

    /// <summary>执行一次状态迁移。</summary>
    /// <param name="next">目标状态。</param>
    /// <exception cref="InvalidStateTransitionException">迁移不在允许边表中。</exception>
    public void TransitionTo(ReaderState next)
    {
        if (!TryTransitionTo(next, out var reason))
        {
            _diagnostics.Add($"拒绝迁移：{reason}");
            throw new InvalidStateTransitionException(Current, next);
        }

        var transition = new StateTransition(Current, next, DateTimeOffset.UtcNow);
        _history.Add(transition);
        _diagnostics.Add($"状态迁移：{Current} → {next}");
        Current = next;
    }
}
