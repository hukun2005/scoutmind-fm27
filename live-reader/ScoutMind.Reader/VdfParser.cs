using System.Text;

namespace ScoutMind.Reader;

/// <summary>
/// 解析 VDF（Valve Data Format）文本时发现的结构错误。消息为中文，直接进入诊断信息。
/// </summary>
public sealed class VdfParseException : Exception
{
    /// <summary>创建解析异常。</summary>
    /// <param name="message">中文错误说明。</param>
    /// <param name="position">出错位置在原文中的字符偏移。</param>
    public VdfParseException(string message, int position)
        : base($"{message}（位置 {position}）")
    {
        Position = position;
    }

    /// <summary>出错位置在原文中的字符偏移。</summary>
    public int Position { get; }
}

/// <summary>
/// VDF 文档中的一个键值节点。<see cref="Children"/> 非空表示该节点是块（带 <c>{ }</c>）。
/// </summary>
/// <param name="Key">键名；根节点为 <c>null</c>。</param>
/// <param name="Value">标量值；块节点为 <c>null</c>。</param>
/// <param name="Children">子节点集合；标量节点为空集合。</param>
public sealed record VdfNode(string? Key, string? Value, IReadOnlyList<VdfNode> Children)
{
    /// <summary>按名称查找第一个子节点，名称比较不区分大小写。</summary>
    /// <param name="key">子节点键名。</param>
    /// <returns>找到的子节点；不存在时为 <c>null</c>。</returns>
    public VdfNode? Child(string key) =>
        Children.FirstOrDefault(child => string.Equals(child.Key, key, StringComparison.OrdinalIgnoreCase));

    /// <summary>按名称查找第一个子节点的标量值。</summary>
    /// <param name="key">子节点键名。</param>
    /// <returns>子节点的值；不存在或为块节点时为 <c>null</c>。</returns>
    public string? ChildValue(string key) => Child(key)?.Value;
}

/// <summary>
/// 极简 VDF 分词器与解析器，足以处理 <c>libraryfolders.vdf</c> 与 <c>appmanifest_*.acf</c>。
/// 支持带引号字符串、嵌套花括号、<c>\\</c>/<c>\"</c>/<c>\n</c>/<c>\t</c> 转义与 <c>//</c> 行注释。
/// </summary>
public static class VdfParser
{
    private const int MaxDepth = 64;

    private enum TokenKind
    {
        String,
        OpenBrace,
        CloseBrace,
    }

    private readonly record struct Token(TokenKind Kind, string? Value, int Position);

    /// <summary>解析整段 VDF 文本。</summary>
    /// <param name="text">VDF 原文，允许带 UTF-8 BOM。</param>
    /// <returns>虚拟根节点，其 <see cref="VdfNode.Children"/> 为顶层键值。</returns>
    /// <exception cref="VdfParseException">文本结构非法（引号或花括号未闭合、深度超限）。</exception>
    public static VdfNode Parse(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        if (text.Length > 0 && text[0] == '\uFEFF')
        {
            text = text[1..];
        }

        var tokens = Tokenize(text);
        var index = 0;
        var children = ParseChildren(tokens, ref index, depth: 0);
        if (index < tokens.Count)
        {
            throw new VdfParseException("VDF 末尾存在多余的 }。", tokens[index].Position);
        }

        return new VdfNode(null, null, children);
    }

    private static List<VdfNode> ParseChildren(List<Token> tokens, ref int index, int depth)
    {
        var children = new List<VdfNode>();
        while (index < tokens.Count)
        {
            var token = tokens[index];
            if (token.Kind == TokenKind.CloseBrace)
            {
                if (depth == 0)
                {
                    throw new VdfParseException("出现没有对应 { 的 }。", token.Position);
                }

                index++;
                return children;
            }

            if (token.Kind == TokenKind.OpenBrace)
            {
                throw new VdfParseException("出现没有前置键名的 {。", token.Position);
            }

            index++;
            if (index < tokens.Count && tokens[index].Kind == TokenKind.OpenBrace)
            {
                if (depth + 1 > MaxDepth)
                {
                    throw new VdfParseException($"VDF 嵌套超过 {MaxDepth} 层，拒绝继续解析。", token.Position);
                }

                index++;
                var inner = ParseChildren(tokens, ref index, depth + 1);
                children.Add(new VdfNode(token.Value, null, inner));
            }
            else if (index < tokens.Count && tokens[index].Kind == TokenKind.String)
            {
                children.Add(new VdfNode(token.Value, tokens[index].Value, Array.Empty<VdfNode>()));
                index++;
            }
            else
            {
                children.Add(new VdfNode(token.Value, null, Array.Empty<VdfNode>()));
            }
        }

        if (depth > 0)
        {
            var position = tokens.Count > 0 ? tokens[^1].Position : 0;
            throw new VdfParseException("VDF 结束时仍有未闭合的 { 块。", position);
        }

        return children;
    }

    private static List<Token> Tokenize(string text)
    {
        var tokens = new List<Token>();
        var index = 0;
        while (index < text.Length)
        {
            var current = text[index];
            if (char.IsWhiteSpace(current))
            {
                index++;
                continue;
            }

            if (current == '/' && index + 1 < text.Length && text[index + 1] == '/')
            {
                while (index < text.Length && text[index] != '\n')
                {
                    index++;
                }

                continue;
            }

            if (current == '{')
            {
                tokens.Add(new Token(TokenKind.OpenBrace, null, index));
                index++;
                continue;
            }

            if (current == '}')
            {
                tokens.Add(new Token(TokenKind.CloseBrace, null, index));
                index++;
                continue;
            }

            if (current == '"')
            {
                tokens.Add(ReadQuotedToken(text, ref index));
                continue;
            }

            tokens.Add(ReadBareToken(text, ref index));
        }

        return tokens;
    }

    private static Token ReadQuotedToken(string text, ref int index)
    {
        var start = index;
        index++;
        var builder = new StringBuilder();
        while (index < text.Length)
        {
            var current = text[index];
            if (current == '\\' && index + 1 < text.Length)
            {
                builder.Append(text[index + 1] switch
                {
                    'n' => '\n',
                    't' => '\t',
                    'r' => '\r',
                    '\\' => '\\',
                    '"' => '"',
                    var other => other,
                });
                index += 2;
                continue;
            }

            if (current == '"')
            {
                index++;
                return new Token(TokenKind.String, builder.ToString(), start);
            }

            builder.Append(current);
            index++;
        }

        throw new VdfParseException("字符串缺少结束引号。", start);
    }

    private static Token ReadBareToken(string text, ref int index)
    {
        var start = index;
        while (index < text.Length)
        {
            var current = text[index];
            if (char.IsWhiteSpace(current) || current == '{' || current == '}')
            {
                break;
            }

            if (current == '/' && index + 1 < text.Length && text[index + 1] == '/')
            {
                break;
            }

            index++;
        }

        return new Token(TokenKind.String, text[start..index], start);
    }
}
