using System.Text;
using ScoutMind.Agent;

// Console output must stay readable for Chinese text on Windows terminals.
try
{
    Console.OutputEncoding = Encoding.UTF8;
}
catch (IOException)
{
    // Redirected stdout without a console handle: keep the default encoding.
}

using var cancellation = new CancellationTokenSource();
ConsoleCancelEventHandler onCancel = (_, eventArgs) =>
{
    // Graceful shutdown: a running scan is stopped through the reader's own cancellation path.
    eventArgs.Cancel = true;
    cancellation.Cancel();
};
Console.CancelKeyPress += onCancel;

try
{
    var application = new AgentApplication(Console.Out, Console.Error, AppContext.BaseDirectory);
    return await application.RunAsync(args, cancellation.Token).ConfigureAwait(false);
}
catch (OperationCanceledException)
{
    Console.Error.WriteLine("已取消。");
    return 130;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"代理内部错误：{ex.Message}");
    return 1;
}
finally
{
    Console.CancelKeyPress -= onCancel;
}
