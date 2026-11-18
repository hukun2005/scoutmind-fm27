namespace ScoutMind.FMReader.Tests;

/// <summary>极简断言工具：失败记录为 <see cref="FailureException"/>，由 <see cref="TestHarness"/> 汇总。</summary>
public sealed class FailureException : Exception
{
    /// <summary>创建失败。</summary>
    /// <param name="message">失败说明。</param>
    public FailureException(string message)
        : base(message)
    {
    }
}

/// <summary>无 xunit 的测试运行器：每个用例都是 Action/Task，失败不中断其余用例。</summary>
public sealed class TestHarness
{
    private int _passed;
    private int _failed;
    private readonly List<string> _failures = new();

    /// <summary>已通过数。</summary>
    public int Passed => _passed;

    /// <summary>失败数。</summary>
    public int Failed => _failed;

    /// <summary>运行一个同步用例。</summary>
    /// <param name="name">用例名。</param>
    /// <param name="body">用例体。</param>
    public void Run(string name, Action body)
    {
        ArgumentNullException.ThrowIfNull(body);
        try
        {
            body();
            _passed++;
            Console.WriteLine($"  PASS  {name}");
        }
        catch (Exception ex)
        {
            _failed++;
            var message = $"{name}: {ex.Message}";
            _failures.Add(message);
            Console.WriteLine($"  FAIL  {message}");
        }
    }

    /// <summary>运行一个异步用例。</summary>
    /// <param name="name">用例名。</param>
    /// <param name="body">用例体。</param>
    /// <returns>任务。</returns>
    public async Task RunAsync(string name, Func<Task> body)
    {
        ArgumentNullException.ThrowIfNull(body);
        try
        {
            await body().ConfigureAwait(false);
            _passed++;
            Console.WriteLine($"  PASS  {name}");
        }
        catch (Exception ex)
        {
            _failed++;
            var message = $"{name}: {ex.Message}";
            _failures.Add(message);
            Console.WriteLine($"  FAIL  {message}");
        }
    }

    /// <summary>断言条件为真。</summary>
    /// <param name="condition">条件。</param>
    /// <param name="message">失败说明。</param>
    public static void True(bool condition, string message)
    {
        if (!condition)
        {
            throw new FailureException(message);
        }
    }

    /// <summary>断言两个值相等。</summary>
    /// <typeparam name="T">值类型。</typeparam>
    /// <param name="expected">期望值。</param>
    /// <param name="actual">实际值。</param>
    /// <param name="message">失败说明。</param>
    public static void Equal<T>(T expected, T actual, string message)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new FailureException($"{message}（期望 {expected}，实际 {actual}）");
        }
    }

    /// <summary>断言字符串包含子串。</summary>
    /// <param name="haystack">被检查文本。</param>
    /// <param name="needle">子串。</param>
    /// <param name="message">失败说明。</param>
    public static void Contains(string haystack, string needle, string message)
    {
        if (!haystack.Contains(needle, StringComparison.Ordinal))
        {
            throw new FailureException($"{message}（未找到 '{needle}'）");
        }
    }

    /// <summary>断言动作抛出指定异常。</summary>
    /// <typeparam name="TException">异常类型。</typeparam>
    /// <param name="action">动作。</param>
    /// <param name="message">失败说明。</param>
    public static void Throws<TException>(Action action, string message)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }
        catch (Exception ex)
        {
            throw new FailureException($"{message}（抛出了 {ex.GetType().Name}）");
        }

        throw new FailureException($"{message}（没有抛出 {typeof(TException).Name}）");
    }

    /// <summary>输出汇总并返回进程退出码。</summary>
    /// <returns>失败数为 0 时返回 0。</returns>
    public int Summary()
    {
        Console.WriteLine();
        Console.WriteLine($"PASS {_passed} · FAIL {_failed}");
        if (_failed > 0)
        {
            Console.WriteLine("失败项：");
            foreach (var failure in _failures)
            {
                Console.WriteLine($"  - {failure}");
            }
        }

        return _failed == 0 ? 0 : 1;
    }
}
