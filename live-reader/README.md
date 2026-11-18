# ScoutMind 实时读取器（live-reader）

本目录是 Windows/C# 部分的读取器栈：检测 Football Manager 27（Steam AppId `4530370`）、
做严格版本闸门、委托外部扫描器执行 probe 与扫描，并把原始数据落盘。
它**不连接数据库**，也**不读写游戏进程内存**——真正读内存的是用户自行选择的外部扫描器。

> 重要：本机（开发机）**没有完成过一次真实的 FM27 扫描**。`config/compatibility.json` 中的
> 唯一条目是 `candidate`（未验证），因此读取器在本机会停在 `Unknown` 或 `Unsupported` 并拒绝读取。
> 详见 [../docs/LIVE_READER.md](../docs/LIVE_READER.md) 与 [../docs/VERSION_COMPATIBILITY.md](../docs/VERSION_COMPATIBILITY.md)。

## 目录结构

```
live-reader/
├── ScoutMind.Contracts/          共享契约（DTO、枚举、JSON 设置、协议序列化）
├── ScoutMind.Reader/             读取器可执行程序（ScoutMind.LiveReader.exe）
│   ├── SteamLocator.cs           Steam 注册表 + libraryfolders.vdf + appmanifest 解析
│   ├── ProcessDetector.cs        fm.exe 进程识别（拒绝误判同名进程）
│   ├── PluginProbe.cs            只读文件版本资源，绝不加载 game_plugin.dll
│   ├── CompatibilityService.cs   严格三方匹配（appId + buildId + 插件产品版本）
│   ├── StateMachine.cs           显式允许边表的状态机
│   ├── ScannerAdapter.cs         外部扫描器进程管理（超时终止进程树、协议校验）
│   ├── ScanWriter.cs             信封 + 边车落盘
│   └── Cli.cs / Program.cs       命令行入口
└── tests/ScoutMind.Reader.Tests/ 控制台自测（无 xunit、无 NuGet）
```

## 快速开始

```powershell
# 构建整个解决方案
dotnet build ScoutMind.sln -c Release

# 自测（46 个用例，全部通过才返回 0）
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests -c Release

# 检测与版本闸门
dotnet run --project live-reader/ScoutMind.Reader -c Release -- status

# 兼容清单
dotnet run --project live-reader/ScoutMind.Reader -c Release -- compatibility list --json
```

## 命令

| 命令 | 作用 | 说明 |
| --- | --- | --- |
| `status [--json]` | 输出检测与版本闸门状态 | 不启动任何外部进程 |
| `probe [--json]` | 让外部扫描器自检 | 只有状态为 `Compatible` 才允许 |
| `scan [--output <目录>] [--timeout <秒>] [--json]` | 执行一次扫描并落盘 | 需要 `ProbePassed`；若当前仅 `Compatible` 会自动先跑 probe |
| `compatibility list [--json]` | 列出兼容清单条目 | 只读 |

`--json` 模式下 stdout 只输出一个 JSON 对象，说明性文字被抑制。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 2 | 未找到 FM27（Steam 安装与进程都不存在） |
| 3 | 构建/版本不受支持或无法确定（拒绝读取） |
| 4 | probe 失败 |
| 5 | 扫描失败 |
| 64 | 用法或配置错误 |
| 130 | 用户按 Ctrl+C 取消 |

## 配置文件

两个文件都从**可执行文件同目录**读取：

- `compatibility.json`：兼容清单，仓库源文件在 `config/compatibility.json`，构建时复制到输出目录。
  可用环境变量 `SCOUTMIND_COMPATIBILITY_FILE` 覆盖路径。
- `scanner.json`：外部扫描器配置，可选。没有它时 `status` 与 `compatibility list` 仍可用，
  但 `probe` / `scan` 会以退出码 64 拒绝执行。示例见 `config/scanner.sample.json`。

也可以用环境变量 `SCOUTMIND_SCANNER_PATH` 临时覆盖扫描器路径。

## 扫描产物

一次成功扫描会在输出目录（默认 `<exe 目录>/scans`）写出：

```
scan-<scanId>.json          # 扫描信封（camelCase，见 ScoutMind.Contracts.ScanEnvelope）
scan-<scanId>.meta.json     # 边车：退出码、耗时、诊断、告警
scan-<attemptId>.stdout.txt # 扫描器标准输出（协议 JSON 原文）
scan-<attemptId>.stderr.txt # 扫描器标准错误
```

本地信封使用 camelCase；桌面代理上传前会用 `ScanProtocolSerializer` 转成
`docs/DATA_PROTOCOL.md` 要求的 snake_case（只改键名，不改值）。

## 安全边界

- 只读：读取器本身只读注册表、文本清单与文件版本资源，绝不写入游戏进程，也不注入 DLL。
- 版本闸门：只有 `appId + buildId + game_plugin.dll 产品版本` 同时命中 `verified` 条目才允许读取；
  `candidate` 一律判为 `Unknown`，未知构建判为 `Unsupported`，**绝不回退到旧版本偏移量**。
- 外部进程：扫描器通过 `Process` 启动，参数逐项传递（不经过 shell），超时终止整棵进程树。
- 失败即拒绝：`Unknown` / `Unsupported` / `ProbeFailed` 都是终态，任何读取动作都会被拒绝。

## 已知限制

- 本仓库**不包含任何内存偏移量或读取实现**；读取能力完全由第三方扫描器提供。
- 该第三方扫描器需要单独审查、单独授权，并自行承担与游戏服务条款相关的风险。
- `compatibility.json` 当前只有一条 `candidate` 条目，尚未在本机验证过真实扫描。
- 本机实测：FM27 构建 `26620374`、插件 `27.1.0+2505117`，与候选条目（`26577676` /
  `27.0.1+2503222`）不一致，因此读取器正确地拒绝读取（退出码 3）。
