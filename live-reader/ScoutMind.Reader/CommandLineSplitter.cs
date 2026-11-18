using System.Text;

namespace ScoutMind.Reader;

/// <summary>
/// 按 Windows 引号习惯把参数模板切分为独立参数。参数逐项交给 <see cref="System.Diagnostics.ProcessStartInfo.ArgumentList"/>，
/// 因此永远不会经过 shell。支持 <c>"a b"</c> 分组与 <c>""</c> 转义为单个引号。
/// </summary>
public static class CommandLineSplitter
{
    /// <summary>切分参数模板。</summary>
    /// <param name="template">模板文本，例如 <c>--scan --output "{output}"</c>。</param>
    /// <returns>切分后的参数列表；空模板返回空列表。</returns>
    /// <exception cref="FormatException">引号未闭合。</exception>
    public static List<string> Split(string template)
    {
        ArgumentNullException.ThrowIfNull(template);

        var result = new List<string>();
        var current = new StringBuilder();
        var inQuotes = false;
        var hasToken = false;

        for (var index = 0; index < template.Length; index++)
        {
            var character = template[index];
            if (character == '"')
            {
                if (inQuotes && index + 1 < template.Length && template[index + 1] == '"')
                {
                    current.Append('"');
                    index++;
                    continue;
                }

                inQuotes = !inQuotes;
                hasToken = true;
                continue;
            }

            if (!inQuotes && char.IsWhiteSpace(character))
            {
                if (hasToken)
                {
                    result.Add(current.ToString());
                    current.Clear();
                    hasToken = false;
                }

                continue;
            }

            current.Append(character);
            hasToken = true;
        }

        if (inQuotes)
        {
            throw new FormatException("参数模板中的引号未闭合。");
        }

        if (hasToken)
        {
            result.Add(current.ToString());
        }

        return result;
    }
}
