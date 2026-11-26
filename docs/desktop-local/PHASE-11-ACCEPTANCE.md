# Desktop V1.0 验收报告（Phase 3 / 5 / 8 / 9 / 11 / 12）

执行环境：Windows 11（当前开发机），安装包 `ScoutMind-FM27-Setup-x64.exe`。

## 1. 交付物

| 项 | 值 |
| --- | --- |
| 安装包 | `release/ScoutMind-FM27-Setup-x64.exe`（161.8 MB） |
| SHA-256 | 见 `release/SHA256SUMS.txt` |
| 构建命令 | `scripts/build-installer.ps1` |
| 安装方式 | NSIS，按用户安装（无需管理员），可选目录、桌面/开始菜单快捷方式、卸载程序 |
| 桌面外壳 | Electron 33.2.1（`nodeIntegration:false` / `contextIsolation:true` / `sandbox:true`，禁止任意导航与新窗口，注入 CSP，IPC 校验 sender） |
| 本地服务 | PyInstaller onedir，无 Python 环境依赖；仅监听 `127.0.0.1` 随机端口 |
| Reader/Agent | self-contained win-x64，随安装包分发到 `resources\live-reader` |

## 2. 已实测（PASS）

| 项 | 结果 |
| --- | --- |
| 安装包静默安装（`/S`） | PASS，退出码 0 |
| 安装目录与快捷方式 | PASS，桌面/开始菜单快捷方式创建，卸载后移除 |
| 无 Python 环境启动 | PASS，安装目录不含 Python，后端为独立 exe |
| 首次启动建库 + 迁移 | PASS，自动生成 `data\scoutmind.db`（head `b2c3d4e5f6a7`） |
| 本地 API 健康检查 | PASS，`/api/v1/health` = ok |
| 界面加载 | PASS，根路径 200，Electron 渲染进程已缓存前端资源 |
| 数据目录分离 | PASS，数据在 `%APPDATA%\ScoutMind FM27`，程序在 `%LOCALAPPDATA%\Programs\ScoutMind FM27` |
| 强制结束主进程后的残留检查 | PASS，stdin 看门狗使本地服务在 10 秒内自行退出，无残留进程 |
| 静默卸载 | PASS，程序文件与快捷方式移除 |
| 卸载保留数据 | PASS，`data\scoutmind.db` 保留 |
| 单实例运行 | PASS（`requestSingleInstanceLock`） |

## 3. 未执行（如实标注）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| Windows 10 干净机安装 | NOT_RUN | 无第二台干净 Win10 环境 |
| 真实断网隔离全流程验收 | NOT_RUN | 需在隔离环境逐项取证 |
| 真实 FM27 读档 → 导入 → 页面全链路 | BLOCKED_BY_ENVIRONMENT | 安装版未在运行中的 FM27 存档上执行导入验收 |
| 升级包 `ScoutMind-FM27-Update-x64.exe` | NOT_RUN | 首版未实现独立更新器，当前用覆盖安装替代 |
| 数字签名 | NOT_RUN | 无代码签名证书 |
| SBOM | NOT_RUN | 未生成 |
| 本地 LLM 推理（Ollama/llama.cpp） | NOT_RUN | 未随包分发模型，确定性分析不受影响 |

## 4. 已知问题

1. 卸载后安装目录可能残留空文件夹（NSIS 常规行为）。
2. 首次启动需 10–30 秒建库迁移，期间无进度界面。
3. 未签名安装包会触发 SmartScreen 提示。
