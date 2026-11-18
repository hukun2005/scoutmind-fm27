using Microsoft.Win32;

namespace ScoutMind.Reader;

/// <summary>
/// 一次成功解析的 FM27 安装信息。<see cref="BuildId"/> 决定了是否可以继续读取，
/// 缺失时必须让状态机停在 Unknown。
/// </summary>
/// <param name="AppId">Steam AppId。</param>
/// <param name="AppManifestPath">解析来源的 <c>appmanifest_*.acf</c> 绝对路径。</param>
/// <param name="InstallDirectory">解析出的游戏安装目录绝对路径。</param>
/// <param name="SteamLibrary">该安装所在的 Steam 库根目录。</param>
/// <param name="BuildId">清单中的 <c>buildid</c>；缺失时为 <c>null</c>。</param>
/// <param name="StateFlags">清单中的 <c>StateFlags</c>，仅用于诊断（例如判断是否已完整安装）。</param>
public sealed record SteamAppInstall(
    string AppId,
    string AppManifestPath,
    string InstallDirectory,
    string SteamLibrary,
    string? BuildId,
    string? StateFlags);

/// <summary>
/// 通过 Steam 的安装清单定位 FM27。只读取注册表与文本文件，不接触游戏进程。
/// 任何缺失（未安装 Steam、未安装 FM27、清单损坏）都返回 <c>null</c> 并记录诊断，绝不抛异常。
/// </summary>
public sealed class SteamLocator
{
    /// <summary>FM27 在 Steam 上的 AppId。</summary>
    public const string Fm27AppId = "4530370";

    private readonly Func<string?> _steamPathProvider;
    private readonly List<string> _diagnostics = new();

    /// <summary>创建定位器。</summary>
    /// <param name="steamPathProvider">
    /// 自定义 Steam 根目录来源，便于测试；为 <c>null</c> 时读取本机注册表。
    /// </param>
    public SteamLocator(Func<string?>? steamPathProvider = null) =>
        _steamPathProvider = steamPathProvider ?? ReadSteamPathFromRegistry;

    /// <summary>最近一次 <see cref="Locate"/> 产生的诊断信息（注册表不可读、清单缺失等）。</summary>
    public IReadOnlyList<string> Diagnostics => _diagnostics;

    /// <summary>在本机所有 Steam 库中查找指定 AppId 的安装清单并解析安装目录。</summary>
    /// <param name="appId">Steam AppId，默认 FM27。</param>
    /// <returns>解析成功时返回安装信息；未安装或无法解析时返回 <c>null</c>。</returns>
    public SteamAppInstall? Locate(string appId = Fm27AppId)
    {
        _diagnostics.Clear();

        var steamRoot = _steamPathProvider();
        if (string.IsNullOrWhiteSpace(steamRoot))
        {
            _diagnostics.Add("未能读取 Steam 安装路径：注册表 HKCU\\Software\\Valve\\Steam\\SteamPath 与 HKLM 均为空或不可访问。");
            return null;
        }

        steamRoot = steamRoot.Trim().Trim('"');
        var normalizedRoot = TryNormalize(steamRoot);
        if (normalizedRoot is null)
        {
            return null;
        }

        if (!Directory.Exists(normalizedRoot))
        {
            _diagnostics.Add($"Steam 安装目录不存在：{normalizedRoot}");
            return null;
        }

        var libraries = new List<string> { normalizedRoot };
        libraries.AddRange(ReadLibraryFolders(normalizedRoot));

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var scanned = 0;
        foreach (var library in libraries)
        {
            var normalizedLibrary = string.IsNullOrWhiteSpace(library) ? null : TryNormalize(library);
            if (normalizedLibrary is null || !seen.Add(normalizedLibrary))
            {
                continue;
            }

            scanned++;
            var manifest = Path.Combine(normalizedLibrary, "steamapps", $"appmanifest_{appId}.acf");
            if (!File.Exists(manifest))
            {
                continue;
            }

            var install = TryReadManifest(manifest, normalizedLibrary, appId);
            if (install is not null)
            {
                return install;
            }
        }

        _diagnostics.Add($"在 {scanned} 个 Steam 库中未找到可用的 appmanifest_{appId}.acf。");
        return null;
    }

    /// <summary>
    /// 解析 <c>appmanifest_*.acf</c> 文本，提取 <c>buildid</c>、<c>installdir</c> 与 <c>StateFlags</c>。
    /// 纯函数，便于用固定文本做单元测试。
    /// </summary>
    /// <param name="manifestText">清单原文。</param>
    /// <param name="appManifestPath">清单文件路径，写入结果用于追溯。</param>
    /// <param name="steamLibrary">清单所属的 Steam 库根目录。</param>
    /// <param name="appId">期望的 AppId。</param>
    /// <returns>解析结果；缺少 <c>installdir</c> 时返回 <c>null</c>。</returns>
    /// <exception cref="VdfParseException">清单文本结构非法。</exception>
    public static SteamAppInstall? ParseAppManifest(
        string manifestText,
        string appManifestPath,
        string steamLibrary,
        string appId)
    {
        ArgumentNullException.ThrowIfNull(manifestText);
        var root = VdfParser.Parse(manifestText);
        var appState = root.Child("AppState") ?? root;

        var installDirName = appState.ChildValue("installdir");
        if (string.IsNullOrWhiteSpace(installDirName))
        {
            return null;
        }

        return new SteamAppInstall(
            AppId: appState.ChildValue("appid") ?? appId,
            AppManifestPath: appManifestPath,
            InstallDirectory: Path.Combine(steamLibrary, "steamapps", "common", installDirName),
            SteamLibrary: steamLibrary,
            BuildId: appState.ChildValue("buildid"),
            StateFlags: appState.ChildValue("StateFlags"));
    }

    /// <summary>
    /// 解析 <c>libraryfolders.vdf</c>，返回所有库根目录。同时兼容新版（子节点含 <c>path</c>）
    /// 与旧版（<c>"1" "D:\\Games"</c>）两种写法。
    /// </summary>
    /// <param name="vdfText">VDF 原文。</param>
    /// <returns>库根目录列表；结构不符时返回空列表。</returns>
    /// <exception cref="VdfParseException">文本结构非法。</exception>
    public static IReadOnlyList<string> ParseLibraryFolders(string vdfText)
    {
        ArgumentNullException.ThrowIfNull(vdfText);
        var root = VdfParser.Parse(vdfText);
        var libraryFolders = root.Child("libraryfolders");
        if (libraryFolders is null)
        {
            return Array.Empty<string>();
        }

        var paths = new List<string>();
        foreach (var child in libraryFolders.Children)
        {
            if (child.Children.Count > 0)
            {
                var path = child.ChildValue("path");
                if (!string.IsNullOrWhiteSpace(path))
                {
                    paths.Add(path);
                }

                continue;
            }

            // Legacy layout stores the library path as the entry's scalar value.
            if (!string.IsNullOrWhiteSpace(child.Value)
                && (Path.IsPathFullyQualified(child.Value) || child.Value.Contains('\\') || child.Value.Contains('/')))
            {
                paths.Add(child.Value);
            }
        }

        return paths;
    }

    private string? ReadSteamPathFromRegistry()
    {
        // The registry APIs are Windows-only; guard explicitly so the platform analyzer stays green
        // and a non-Windows host reports a diagnosis instead of throwing PlatformNotSupportedException.
        if (!OperatingSystem.IsWindows())
        {
            _diagnostics.Add("当前平台不是 Windows，无法读取 Steam 注册表路径。");
            return null;
        }

        var candidates = new (RegistryKey Root, string SubKey, string ValueName)[]
        {
            (Registry.CurrentUser, @"Software\Valve\Steam", "SteamPath"),
            (Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (Registry.LocalMachine, @"SOFTWARE\Valve\Steam", "InstallPath"),
        };

        foreach (var (root, subKey, valueName) in candidates)
        {
            try
            {
                using var key = root.OpenSubKey(subKey);
                if (key?.GetValue(valueName) is string value && !string.IsNullOrWhiteSpace(value))
                {
                    return value;
                }
            }
            catch (Exception ex) when (ex is System.Security.SecurityException or UnauthorizedAccessException or IOException)
            {
                _diagnostics.Add($"读取注册表 {subKey} 失败：{ex.Message}");
            }
        }

        return null;
    }

    private SteamAppInstall? TryReadManifest(string manifestPath, string steamLibrary, string appId)
    {
        string text;
        try
        {
            text = File.ReadAllText(manifestPath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            _diagnostics.Add($"读取安装清单失败（{manifestPath}）：{ex.Message}");
            return null;
        }

        try
        {
            var install = ParseAppManifest(text, manifestPath, steamLibrary, appId);
            if (install is null)
            {
                _diagnostics.Add($"安装清单缺少 installdir 字段：{manifestPath}");
            }

            return install;
        }
        catch (VdfParseException ex)
        {
            _diagnostics.Add($"安装清单格式非法（{manifestPath}）：{ex.Message}");
            return null;
        }
    }

    private string? TryNormalize(string path)
    {
        try
        {
            return Path.GetFullPath(path);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            _diagnostics.Add($"Steam 路径非法（{path}）：{ex.Message}");
            return null;
        }
    }

    private List<string> ReadLibraryFolders(string steamRoot)
    {
        var result = new List<string>();
        var vdfPath = Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf");
        if (!File.Exists(vdfPath))
        {
            _diagnostics.Add($"未找到 libraryfolders.vdf（{vdfPath}），只扫描主库。");
            return result;
        }

        string text;
        try
        {
            text = File.ReadAllText(vdfPath);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or System.Security.SecurityException)
        {
            _diagnostics.Add($"读取 libraryfolders.vdf 失败：{ex.Message}");
            return result;
        }

        try
        {
            result.AddRange(ParseLibraryFolders(text));
        }
        catch (VdfParseException ex)
        {
            _diagnostics.Add($"libraryfolders.vdf 格式非法：{ex.Message}");
        }

        return result;
    }
}
