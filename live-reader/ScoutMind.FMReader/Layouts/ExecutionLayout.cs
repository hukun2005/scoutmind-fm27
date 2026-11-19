using System.Reflection;
using FMSuperScout;
using ScoutMind.FMReader.Layouts;

namespace ScoutMind.FMReader.Engine;

/// <summary>一条"诊断布局 vs 执行布局"的差异。</summary>
/// <param name="Field">字段名。</param>
/// <param name="Diagnostic">ScoutMind 布局里的值。</param>
/// <param name="Execution">上游 <c>Dumper</c> 实际会用的值。</param>
public sealed record LayoutDifference(string Field, uint Diagnostic, uint Execution);

/// <summary>
/// 诊断布局（ScoutMind 的 <see cref="ILayout"/>）与执行布局（上游 <c>Fields.FM27</c>，Dumper 真正使用的那份）
/// 的一致性检查。
///
/// 只做诊断不读内存，也不改上游；真正需要把 ScoutMind 的偏移推到上游时用 <see cref="UpstreamLayoutScope"/>。
/// </summary>
public static class LayoutConsistency
{
    private static readonly Dictionary<string, PropertyInfo> UpstreamProperties = typeof(Fields)
        .GetProperties(BindingFlags.Public | BindingFlags.Instance)
        .Where(property => property.PropertyType == typeof(uint) && property.CanRead)
        .ToDictionary(property => property.Name, StringComparer.Ordinal);

    /// <summary>读取上游执行布局的偏移表（只读反射，不修改任何值）。</summary>
    /// <returns>字段名 → 偏移。</returns>
    public static IReadOnlyDictionary<string, uint> ReadExecutionLayout()
    {
        var result = new Dictionary<string, uint>(StringComparer.Ordinal);
        foreach (var (name, property) in UpstreamProperties)
        {
            if (property.GetValue(Fields.FM27) is uint value)
            {
                result[name] = value;
            }
        }

        return result;
    }

    /// <summary>比较诊断布局与执行布局。</summary>
    /// <param name="layout">ScoutMind 布局。</param>
    /// <param name="execution">执行布局（默认读上游）。</param>
    /// <returns>差异列表；空列表表示一致。</returns>
    public static IReadOnlyList<LayoutDifference> Compare(
        ILayout layout,
        IReadOnlyDictionary<string, uint>? execution = null)
    {
        ArgumentNullException.ThrowIfNull(layout);
        var actual = execution ?? ReadExecutionLayout();
        var differences = new List<LayoutDifference>();
        foreach (var (field, diagnosticValue) in layout.Offsets)
        {
            if (actual.TryGetValue(field, out var executionValue) && executionValue != diagnosticValue)
            {
                differences.Add(new LayoutDifference(field, diagnosticValue, executionValue));
            }
        }

        return differences;
    }

    /// <summary>执行布局里是否存在该字段（用于判断"改了布局但对执行没影响"）。</summary>
    /// <param name="field">字段名。</param>
    /// <returns>存在时为 <c>true</c>。</returns>
    public static bool ExecutionHas(string field) => UpstreamProperties.ContainsKey(field);
}

/// <summary>
/// 把 ScoutMind 的布局临时推给上游 <see cref="Fields.FM27"/>，让 27.1 的偏移真正影响 Dumper 的执行。
///
/// 为什么需要它：上游把布局写死在 <c>Fields.FM27</c> 里（27.0）。如果 ScoutMind 的 <c>FM27_1</c> 偏移与上游不同，
/// 只改 ScoutMind 的布局不会影响读取结果——那是最危险的"看起来验证过、实际读的是旧布局"。
/// 这个 scope 在偏移不同时用反射写入上游属性，Dispose 时原样恢复；写入失败则抛异常，由调用方拒绝扫描。
/// 上游代码本身不改（符合"third_party 修改必须单独记录"的要求）。
/// </summary>
public sealed class UpstreamLayoutScope : IDisposable
{
    private readonly List<(PropertyInfo Property, uint Original)> _restore = new();
    private bool _disposed;

    private UpstreamLayoutScope()
    {
    }

    /// <summary>应用的字段数（0 表示本来就一致）。</summary>
    public int AppliedFields => _restore.Count;

    /// <summary>把布局应用到上游；不一致且无法应用时抛 <see cref="InvalidOperationException"/>。</summary>
    /// <param name="layout">要生效的 ScoutMind 布局。</param>
    /// <returns>可恢复的 scope。</returns>
    public static UpstreamLayoutScope Apply(ILayout layout)
    {
        ArgumentNullException.ThrowIfNull(layout);
        var scope = new UpstreamLayoutScope();
        var differences = LayoutConsistency.Compare(layout);
        if (differences.Count == 0)
        {
            return scope;
        }

        try
        {
            foreach (var difference in differences)
            {
                if (!LayoutConsistency.ExecutionHas(difference.Field))
                {
                    throw new InvalidOperationException(
                        $"布局字段 {difference.Field} 在上游执行布局里不存在，无法把 {layout.Name} 应用到执行层。");
                }

                var property = typeof(Fields).GetProperty(difference.Field, BindingFlags.Public | BindingFlags.Instance)
                    ?? throw new InvalidOperationException($"上游没有属性 {difference.Field}。");
                var setter = property.GetSetMethod(nonPublic: true)
                    ?? throw new InvalidOperationException($"上游属性 {difference.Field} 没有可用的 setter。");
                var original = (uint)(property.GetValue(Fields.FM27) ?? 0u);
                setter.Invoke(Fields.FM27, new object[] { difference.Diagnostic });
                scope._restore.Add((property, original));
            }
        }
        catch
        {
            scope.Dispose();
            throw;
        }

        return scope;
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        // 逆序恢复，避免中途失败留下半套偏移。
        for (var index = _restore.Count - 1; index >= 0; index--)
        {
            var (property, original) = _restore[index];
            try
            {
                property.GetSetMethod(nonPublic: true)?.Invoke(Fields.FM27, new object[] { original });
            }
            catch (Exception)
            {
                // 恢复失败不能掩盖原始异常：调用方已经拿到了结果，最坏情况下一次进程重启即可恢复。
            }
        }

        _restore.Clear();
    }
}
