# 上游：FMSuperScout

ScoutMind 内置的只读读取引擎（`live-reader/ScoutMind.FMReader`）复用了 FMSuperScout 的 Windows 内存读取内核。
本文件记录**固定版本、许可证、纳入了哪些文件、做了哪些本地修改**，便于复核与升级。

## 固定版本

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/mavarobli/FMSuperScout |
| 许可证 | MIT（见同目录 `LICENSE`） |
| 固定 commit | `6cf8f87af24108d17667e415bb43f1c99eb6995e` |
| commit 时间 | 2026-11-18 14:01:06 +0000 |
| commit 标题 | `stats: dagelijkse download-tellers` |
| 上游版本（dump 自报） | FMSuperScout 1.7.3 |

升级步骤：`git clone` 上游 → `git checkout <新 SHA>` → 用下面的文件清单覆盖 `src/` → 重新应用 `patches/` →
更新本文件的 SHA → 跑 `dotnet test`（见 `live-reader/tests/ScoutMind.FMReader.Tests`）。

## 纳入的文件

只纳入读取内核，不含其 UI、Node.js 应用、插件与安装器。

| 上游路径 | 本地路径 | 作用 |
| --- | --- | --- |
| `core/Dumper.cs` | `src/Dumper.cs` | 遍历 FM 数据库、解析球员/俱乐部/合同、写出 dump |
| `core/Fields.cs` | `src/Fields.cs` | 每个 FM 版本的内存布局与偏移 |
| `core/Host.cs` | `src/Host.cs` | 日志钩子与宿主标识 |
| `core/Json.cs` | `src/Json.cs` | 最小 JSON 写入器 |
| `core/MemScan.cs` | `src/MemScan.cs` | 只读内存访问的通用部分 |
| `core/MemScan.Win.cs` | `src/MemScan.Win.cs` | Windows 平台实现（`ReadProcessMemory` / 快照） |

**未纳入**（明确排除）：`app/`（Node.js 桌面应用）、`scanner/`（独立扫描器进程入口）、`plugin/`（BepInEx 插件）、
`installer/`、`stats/`、`mac/`、`core/MemScan.Mac.cs`。ScoutMind 自带 Reader 进程，不需要上游的进程入口。

## 本地修改

只有一处，且可逐行复核：`patches/0001-outdir-override.patch`

- `Dumper.cs` 的输出目录 `OutDir` 支持用环境变量 `SCOUTMIND_FMREADER_OUTDIR` 覆盖，未设置时行为与上游一致；
- 目的：把 dump 写到 ScoutMind 自己的临时目录，不污染用户的 `%LOCALAPPDATA%\FMSuperScout`，
  也不依赖 FMSuperScout 是否安装。

## 使用方式与约束

- 上游文件**原样编译**进 `ScoutMind.FMReader` 程序集（上游类型是 `internal`，包装层因此同程序集），
  包装代码全部在 `Engine/`、`Integration/`、`Versioning/`，不修改上游逻辑；
- 只读：上游通过 `ReadProcessMemory` 读取，ScoutMind 不写入、不注入、不 hook 游戏进程；
- 版本闸门、协议转换、数据校验全部在 ScoutMind 侧实现，见 `docs/FM27-VERSION-VERIFICATION.md`。

## 许可证与合规

- 保留上游 `LICENSE` 原文（MIT），ScoutMind 的 `docs/THIRD_PARTY_NOTICES.md` 汇总了所有第三方组件；
- 上游版权声明保留在源文件头部与 `LICENSE` 中，不修改、不删除；
- ScoutMind 自身代码仍按其仓库许可证发布；上游代码的再分发遵循 MIT 条件（保留版权与许可声明）。
