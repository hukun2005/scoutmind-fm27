namespace ScoutMind.Reader.Tests;

/// <summary>
/// 每个用例独占的临时目录，用例结束后尽力删除，避免测试之间互相污染。
/// 默认使用可执行文件旁的 <c>test-tmp</c> 目录，而不是系统临时目录：
/// 某些受限环境（沙箱、组策略）会拒绝子进程写入 <c>%TEMP%</c>，让纯逻辑测试误报失败。
/// 需要改位置时设置环境变量 <c>SCOUTMIND_TEST_ROOT</c>。
/// </summary>
internal sealed class TempWorkspace : IDisposable
{
    /// <summary>覆盖测试根目录的环境变量。</summary>
    public const string RootEnvironmentVariable = "SCOUTMIND_TEST_ROOT";

    /// <summary>创建临时目录。</summary>
    public TempWorkspace()
    {
        var configured = Environment.GetEnvironmentVariable(RootEnvironmentVariable);
        var root = string.IsNullOrWhiteSpace(configured)
            ? Path.Combine(AppContext.BaseDirectory, "test-tmp")
            : Path.GetFullPath(configured.Trim());
        Root = Path.Combine(root, "scoutmind-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Root);
    }

    /// <summary>临时目录根路径。</summary>
    public string Root { get; }

    /// <summary>在临时目录下解析相对路径。</summary>
    /// <param name="relativePath">相对路径。</param>
    /// <returns>绝对路径。</returns>
    public string Combine(string relativePath) => Path.Combine(Root, relativePath);

    /// <summary>删除临时目录。失败时保留目录内容以便排错，不抛异常。</summary>
    public void Dispose()
    {
        try
        {
            if (Directory.Exists(Root))
            {
                Directory.Delete(Root, recursive: true);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Console.WriteLine($"（提示）临时目录未删除：{Root}（{ex.Message}）");
        }
    }
}
