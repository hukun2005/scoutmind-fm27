using System.Text;
using ScoutMind.Reader;

// Console output must stay readable for Chinese text on Windows terminals.
try
{
    Console.OutputEncoding = Encoding.UTF8;
}
catch (IOException)
{
    // Redirected stdout without a console handle: keep the default encoding instead of failing.
}

using var cancellation = new CancellationTokenSource();
ConsoleCancelEventHandler onCancel = (_, eventArgs) =>
{
    // Graceful shutdown: let the CLI kill any running scanner process tree before exiting.
    eventArgs.Cancel = true;
    cancellation.Cancel();
};
Console.CancelKeyPress += onCancel;

try
{
    var cli = new Cli(Console.Out, Console.Error, AppContext.BaseDirectory);
    return await cli.RunAsync(args, cancellation.Token).ConfigureAwait(false);
}
catch (OperationCanceledException)
{
    Console.Error.WriteLine("已取消。");
    return 130;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"读取器内部错误：{ex.Message}");
    return ExitCodes.ScanFailed;
}
finally
{
    Console.CancelKeyPress -= onCancel;
}
