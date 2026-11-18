namespace ScoutMind.Reader.Tests;

/// <summary>
/// 断言失败。消息包含期望值与实际值，便于定位。
/// </summary>
public sealed class AssertionException : Exception
{
    /// <summary>创建断言异常。</summary>
    /// <param name="message">中文说明。</param>
    public AssertionException(string message)
        : base(message)
    {
    }
}

/// <summary>
/// 精简断言集合。与 xunit 不同，这里不依赖任何包，失败即抛异常由测试框架收集。
/// </summary>
public static class Assert
{
    /// <summary>断言条件为真。</summary>
    /// <param name="condition">条件。</param>
    /// <param name="message">失败说明。</param>
    public static void True(bool condition, string message)
    {
        if (!condition)
        {
            throw new AssertionException($"期望为真，实际为假：{message}");
        }
    }

    /// <summary>断言条件为假。</summary>
    /// <param name="condition">条件。</param>
    /// <param name="message">失败说明。</param>
    public static void False(bool condition, string message)
    {
        if (condition)
        {
            throw new AssertionException($"期望为假，实际为真：{message}");
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
            throw new AssertionException($"期望 <{Format(expected)}>，实际 <{Format(actual)}>：{message}");
        }
    }

    /// <summary>断言字符串包含子串。</summary>
    /// <param name="haystack">被搜索的文本。</param>
    /// <param name="needle">期望出现的子串。</param>
    /// <param name="message">失败说明。</param>
    public static void Contains(string? haystack, string needle, string message)
    {
        if (haystack is null || !haystack.Contains(needle, StringComparison.Ordinal))
        {
            throw new AssertionException($"期望包含 \"{needle}\"，实际为 \"{haystack ?? "null"}\"：{message}");
        }
    }

    /// <summary>断言文件存在。</summary>
    /// <param name="path">文件路径。</param>
    /// <param name="message">失败说明。</param>
    public static void FileExists(string path, string message)
    {
        if (!File.Exists(path))
        {
            throw new AssertionException($"期望文件存在：{path}（{message}）");
        }
    }

    /// <summary>断言同步代码抛出指定异常。</summary>
    /// <typeparam name="TException">期望的异常类型。</typeparam>
    /// <param name="action">被测代码。</param>
    /// <param name="message">失败说明。</param>
    /// <returns>捕获到的异常。</returns>
    public static TException Throws<TException>(Action action, string message)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException ex)
        {
            return ex;
        }
        catch (Exception ex)
        {
            throw new AssertionException(
                $"期望 {typeof(TException).Name}，实际 {ex.GetType().Name}: {ex.Message}（{message}）");
        }

        throw new AssertionException($"期望抛出 {typeof(TException).Name}，但没有任何异常（{message}）");
    }

    /// <summary>断言异步代码抛出指定异常。</summary>
    /// <typeparam name="TException">期望的异常类型。</typeparam>
    /// <param name="action">被测代码。</param>
    /// <param name="message">失败说明。</param>
    /// <returns>捕获到的异常。</returns>
    public static async Task<TException> ThrowsAsync<TException>(Func<Task> action, string message)
        where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException ex)
        {
            return ex;
        }
        catch (Exception ex)
        {
            throw new AssertionException(
                $"期望 {typeof(TException).Name}，实际 {ex.GetType().Name}: {ex.Message}（{message}）");
        }

        throw new AssertionException($"期望抛出 {typeof(TException).Name}，但没有任何异常（{message}）");
    }

    private static string Format<T>(T value) => value?.ToString() ?? "null";
}

/// <summary>
/// 轻量测试框架：逐个执行用例、收集失败、打印汇总。
/// </summary>
public sealed class TestHarness
{
    private readonly List<string> _failures = new();
    private int _passed;
    private int _total;

    /// <summary>执行一个同步用例。</summary>
    /// <param name="name">用例名。</param>
    /// <param name="body">用例主体。</param>
    public void Case(string name, Action body)
    {
        _total++;
        try
        {
            body();
            _passed++;
            Console.WriteLine($"  [通过] {name}");
        }
        catch (Exception ex)
        {
            var detail = ex is AssertionException ? ex.Message : $"{ex.GetType().Name}: {ex.Message}";
            _failures.Add($"{name} — {detail}");
            Console.WriteLine($"  [失败] {name}");
            Console.WriteLine($"         {detail}");
        }
    }

    /// <summary>执行一个异步用例。</summary>
    /// <param name="name">用例名。</param>
    /// <param name="body">用例主体。</param>
    /// <returns>表示用例执行完成的任务。</returns>
    public async Task CaseAsync(string name, Func<Task> body)
    {
        _total++;
        try
        {
            await body().ConfigureAwait(false);
            _passed++;
            Console.WriteLine($"  [通过] {name}");
        }
        catch (Exception ex)
        {
            var detail = ex is AssertionException ? ex.Message : $"{ex.GetType().Name}: {ex.Message}";
            _failures.Add($"{name} — {detail}");
            Console.WriteLine($"  [失败] {name}");
            Console.WriteLine($"         {detail}");
        }
    }

    /// <summary>打印汇总并返回进程退出码。</summary>
    /// <returns>全部通过返回 0，否则返回 1。</returns>
    public int Summary()
    {
        Console.WriteLine();
        Console.WriteLine("=== 测试汇总 ===");
        Console.WriteLine($"用例总数：{_total}");
        Console.WriteLine($"通过：{_passed}");
        Console.WriteLine($"失败：{_failures.Count}");

        if (_failures.Count == 0)
        {
            Console.WriteLine("结果：全部通过");
            return 0;
        }

        Console.WriteLine("失败明细：");
        foreach (var failure in _failures)
        {
            Console.WriteLine($"  - {failure}");
        }

        Console.WriteLine("结果：存在失败");
        return 1;
    }
}
