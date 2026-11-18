# 第三方组件与许可证

ScoutMind 本体按仓库根目录的许可证发布。下表列出随仓库分发的第三方代码、来源、版本与许可证义务。

## 1. FMSuperScout 读取内核（MIT）

| 项 | 值 |
| --- | --- |
| 项目 | FMSuperScout |
| 仓库 | https://github.com/mavarobli/FMSuperScout |
| 固定 commit | `6cf8f87af24108d17667e415bb43f1c99eb6995e` |
| 许可证 | MIT |
| 许可证原文 | [`third_party/FMSuperScout/LICENSE`](../third_party/FMSuperScout/LICENSE) |
| 本地路径 | `third_party/FMSuperScout/src/`（6 个文件） |
| 纳入方式 | 原样编译进 `live-reader/ScoutMind.FMReader` |
| 本地修改 | 1 处：`Dumper.OutDir` 可用环境变量覆盖（`third_party/FMSuperScout/patches/0001-outdir-override.patch`） |

MIT 义务：保留版权声明与许可证文本，不得以作者名义为 ScoutMind 背书。两项均已满足：`LICENSE` 原文随仓库保留，
源文件头部声明未被修改，本文件明确说明改动范围。

未纳入的上游部分（因此不涉及它们的许可证）：`app/`（Node.js 桌面应用）、`scanner/`、`plugin/`（BepInEx 插件）、
`installer/`、`stats/`、`mac/`。

## 2. 依赖的运行时与框架

| 组件 | 许可证 | 使用方式 |
| --- | --- | --- |
| .NET 10 / ASP.NET Core（Microsoft） | MIT | 读取器、桌面代理、后端运行时 |
| FastAPI、SQLAlchemy、Pydantic | MIT / BSD-3-Clause | Python 后端 |
| Vue 3、Element Plus、ECharts、Pinia（及 Vite 生态） | MIT | 前端 |
| SQLite | Public Domain | 本地数据库 |

以上均为通过包管理器解析的依赖，不随仓库复制源码；其许可证以各自发布包为准。

## 3. 合规边界

- ScoutMind **不**包含、也**不**调用上游的插件（BepInEx `game_plugin` 之外的注入组件）、安装器或桌面应用；
- 读取器只读取游戏内存，不写入、不注入、不修改游戏文件；
- 上游固定版本与升级流程见 [`third_party/FMSuperScout/UPSTREAM.md`](../third_party/FMSuperScout/UPSTREAM.md)。
