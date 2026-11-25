# ScoutMind FM27 V3.2.6 Windows 发布报告

**状态：NOT_RUN（没有产出安装包）**

## 1. 现有能力

`scripts/publish-windows.ps1`：

- `dotnet publish` 自包含单文件：`ScoutMind.LiveReader.exe`、`ScoutMind.Agent.exe`（win-x64）；
- 复制 `compatibility.json`、`scanner.sample.json`；
- 不包含后端、前端、数据库初始化、首次启动向导。

## 2. 缺口

| 要求 | 现状 |
| --- | --- |
| 安装包（MSI/EXE） | 没有（无 WiX/Inno/MSIX 工程） |
| 后端 Python 运行时 | 未打包（需源码 + venv） |
| 前端静态资源集成 | 未集成到发布物 |
| 数据库初始化 | 仅 Alembic，无用户级初始化 |
| 首次启动向导 | 无 |
| 升级保留数据 | 无安装器，无从谈起 |
| 卸载保留数据 | 无 |
| 备份/恢复工具 | 无 |
| 代码签名 | 无证书 |

## 3. 依赖与许可证

- 读取器不要求用户安装 FMSuperScout：`third_party/FMSuperScout` 为 MIT License（Copyright 2026 mavarobli），
  源码编译进读取器；分发需附许可证文本。
- .NET 运行时以 self-contained 形式随 exe 发布。

## 4. 结论

“下载即用”的目标未达成；V3.2.6 不能声称具备正式安装包。
RC 只能作为源码/开发包交付，或由用户按 `scripts/setup.ps1` 手动部署。
