# Phase 0 仓库审计（ScoutMind FM27 Desktop V1.0）

审计时间：2026-11-26；基线：`main` @ `e233265`。

## 1. 现有架构

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 前端 | `frontend/` | Vue 3 + TypeScript + Vite，构建产物 `frontend/dist` |
| 后端 | `backend/` | FastAPI + SQLAlchemy + Alembic + SQLite，入口 `app.main:app` |
| 存档读取 | `live-reader/` | C# self-contained win-x64（LiveReader / Agent / Contracts） |
| 发布工程 | `scripts/build-release.ps1`、`scripts/release/` | 便携版 zip、校验、备份脚本 |
| 数据库 | `backend/data/scoutmind.db`（默认） | 迁移链 head `b2c3d4e5f6a7` |

## 2. 本地运行依赖

- 后端仅依赖 Python 包（`backend/requirements.txt`），无系统级原生依赖，PyInstaller 可打包。
- 前端构建为纯静态资源，无运行时 CDN；离线可用。
- C# Reader/Agent 已是 self-contained 发布，无需 .NET 运行时。
- 数据访问全部为本地 SQLite，无 PostgreSQL 硬依赖（PG 仅用于 CI 兼容性作业）。

## 3. 网络依赖审计（源码检索结论）

| 类别 | 结论 |
| --- | --- |
| 业务 API | 无云端业务调用，全部本地 `/api/v1/*` |
| AI Provider | 默认无远程 Provider；AI Sporting Director 的确定性分析本地执行 |
| CDN / 在线字体 / 在线图片 | 前端无外链资源 |
| 遥测 / 在线授权 / 自动更新 | 不存在 |
| 运行时下载 | 不存在 |

尚未做真实断网隔离验收（见 PHASE-11 状态标注）。

## 4. 打包方案结论

| 组件 | 方案 |
| --- | --- |
| FastAPI | PyInstaller `onedir`（复用 `desktop-shell/main.py` 的 `--headless` 模式） |
| 前端 | Vite 生产构建，作为 `extraResources/frontend` 由后端托管 |
| Reader/Agent | 复用发布流水线 self-contained 产物，放入 `extraResources/live-reader` |
| 桌面外壳 | Electron 33.2.1 + electron-builder 25.1.8，NSIS 安装包 |
| 数据目录 | 程序文件与应用数据分离：`%APPDATA%\ScoutMind FM27\data` |

## 5. 风险

1. 安装包未做代码签名 → SmartScreen 提示（自有分发可接受，正式对外需证书）。
2. Windows 10 干净机、真实断网隔离未在本机验证。
3. 首版不提供自动更新，仅手动覆盖安装。
