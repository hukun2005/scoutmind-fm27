namespace ScoutMind.Reader.Tests;

/// <summary>VDF 解析与 appmanifest 解析用例，全部使用内嵌字符串，不依赖外部文件。</summary>
public static class VdfParserTests
{
    private const string LibraryFoldersVdf = """
        // Steam 库列表（内嵌测试夹具）
        "libraryfolders"
        {
        	"0"
        	{
        		"path"		"C:\\Program Files (x86)\\Steam"
        		"label"		""
        		"contentstatsid"		"-1234567890"
        	}
        	"1"
        	{
        		"path"		"D:\\SteamLibrary"
        	}
        }
        """;

    private const string AppManifestAcf = """
        "AppState"
        {
        	"appid"		"4530370"
        	"name"		"Football Manager 27"
        	"StateFlags"		"4"
        	"installdir"		"Football Manager 27"
        	"buildid"		"26577676"
        	"UserConfig"
        	{
        		"language"		"schinese"
        	}
        }
        """;

    /// <summary>注册并执行 VDF 用例。</summary>
    /// <param name="harness">测试框架。</param>
    public static void Run(TestHarness harness)
    {
        harness.Case("VDF 解析嵌套块与带引号的键", () =>
        {
            var root = VdfParser.Parse(LibraryFoldersVdf);
            var libraryFolders = root.Child("libraryfolders");
            Assert.True(libraryFolders is not null, "应解析出 libraryfolders 块");
            Assert.Equal(2, libraryFolders!.Children.Count, "应有两个库条目");
            Assert.Equal(
                @"C:\Program Files (x86)\Steam",
                libraryFolders.Child("0")?.ChildValue("path"),
                "转义后的路径应还原");
            Assert.Equal(string.Empty, libraryFolders.Child("0")?.ChildValue("label"), "空字符串值应保留");
        });

        harness.Case("VDF 解析忽略注释与未加引号的值", () =>
        {
            var root = VdfParser.Parse("""
                // 注释行
                key1 value1
                "key2" "value2" // 行尾注释
                """);
            Assert.Equal("value1", root.ChildValue("key1"), "未加引号的标量应可解析");
            Assert.Equal("value2", root.ChildValue("key2"), "行尾注释应被忽略");
        });

        harness.Case("VDF 解析处理引号转义", () =>
        {
            var root = VdfParser.Parse("""
                "weird\"key" "line1\nline2"
                """);
            Assert.Equal("line1\nline2", root.ChildValue("weird\"key"), "转义换行与引号都应还原");
        });

        harness.Case("VDF 解析在结构非法时抛异常", () =>
        {
            Assert.Throws<VdfParseException>(() => VdfParser.Parse("\"a\" { \"b\" \"c\""), "未闭合的块应报错");
            Assert.Throws<VdfParseException>(() => VdfParser.Parse("}"), "多余的反括号应报错");
            Assert.Throws<VdfParseException>(() => VdfParser.Parse("\"unclosed"), "未闭合的引号应报错");
        });

        harness.Case("libraryfolders 解析出新旧两种布局", () =>
        {
            var paths = SteamLocator.ParseLibraryFolders(LibraryFoldersVdf);
            Assert.Equal(2, paths.Count, "应解析出两个库路径");
            Assert.Equal(@"C:\Program Files (x86)\Steam", paths[0], "第一个库路径应正确");

            var legacy = SteamLocator.ParseLibraryFolders("""
                "libraryfolders"
                {
                	"1"		"E:\\Games\\Steam"
                }
                """);
            Assert.Equal(1, legacy.Count, "旧布局应解析出一个库路径");
            Assert.Equal(@"E:\Games\Steam", legacy[0], "旧布局的库路径应正确");
        });

        harness.Case("appmanifest 提取 buildid 与 installdir", () =>
        {
            var install = SteamLocator.ParseAppManifest(
                AppManifestAcf,
                @"D:\steam\steamapps\appmanifest_4530370.acf",
                @"D:\steam",
                SteamLocator.Fm27AppId);

            Assert.True(install is not null, "应成功解析 appmanifest");
            Assert.Equal("26577676", install!.BuildId, "buildid 应被提取");
            Assert.Equal("4", install.StateFlags, "StateFlags 应被提取");
            Assert.Equal("4530370", install.AppId, "appid 应被提取");
            Assert.Equal(
                Path.Combine(@"D:\steam", "steamapps", "common", "Football Manager 27"),
                install.InstallDirectory,
                "安装目录应为 <库>/steamapps/common/<installdir>");
        });

        harness.Case("appmanifest 缺少 installdir 时返回 null", () =>
        {
            var install = SteamLocator.ParseAppManifest(
                """
                "AppState"
                {
                	"appid"		"4530370"
                	"buildid"		"26577676"
                }
                """,
                @"D:\steam\steamapps\appmanifest_4530370.acf",
                @"D:\steam",
                SteamLocator.Fm27AppId);

            Assert.True(install is null, "缺少 installdir 时不得到猜测路径");
        });
    }
}
