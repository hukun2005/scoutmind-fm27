# Phase 4：Windows 发布工程（V3.2.9.2）

- 目标：用户解压后用一个脚本启动，不需要手工进入多个目录、手工开两个服务
- 方式：复用现有 `scripts/publish-windows.ps1`（Reader/Agent），新增整包构建与运行脚本

## 1. 现有部署结构审计

| 组件 | 现状 | 结论 |
| --- | --- | --- |
| 后端入口 | `backend/app/main.py`（`create_app`，uvicorn `app.main:app`） | 直接复用 |
| 后端依赖 | `backend/requirements.txt`（FastAPI/SQLAlchemy/Alembic/uvicorn 等） | 发布包内首次启动自动安装 |
| 前端 | Vite 生产构建 → `frontend/dist` | 只发布 `dist`，不带 `node_modules` |
| 前端托管 | 原实现只提供 API，`/` 返回 JSON | **新增**：后端可选托管 `dist`（`SCOUTMIND_FRONTEND_DIST`），单端口同时提供 API 与界面 |
| Native Reader | `scripts/publish-windows.ps1`（自包含单文件） | 复用 |
| Desktop Agent | 同上 | 复用 |
| 数据库 | SQLite `backend/data/scoutmind.db`；目录自动创建；WAL + busy_timeout | 发布包改为 `data/scoutmind.db` |
| 配置 | `backend/.env`（`SCOUTMIND_*`）；`config/compatibility.json`、`scanner.sample.json` | 新增 `config/app.example.json` |
| 日志 | 无统一目录 | 发布包 `logs/backend.{out,err}.log` |
| 现有启动脚本 | `setup.ps1`、`run-backend.ps1`、`run-frontend.ps1`（开发用，需要 Node 与两个终端） | 不用于发布包 |

## 2. 发布包结构

```
ScoutMind-FM27-V3.2.9.2/
├── backend/                 app/ + alembic/ + alembic.ini + requirements.txt（无 .venv、无 __pycache__）
├── frontend/dist/           vite 生产构建
├── live-reader/             ScoutMind.LiveReader.exe、ScoutMind.Agent.exe、
│                            compatibility.json、scanner.sample.json
├── config/app.example.json
├── data/                    运行期数据库（首发为空）
├── logs/                    后端日志
├── scripts/
│   ├── Start-ScoutMind.ps1
│   ├── Stop-ScoutMind.ps1
│   ├── Check-Environment.ps1
│   ├── Backup-Database.ps1
│   └── backup_sqlite.py
├── docs 副本                  INSTALLATION.md、RELEASE_NOTES.md、COMPATIBILITY.md、KNOWN_ISSUES.md
├── INSTALLATION.md / README.txt / VERSION.txt / LICENSE
```

构建脚本：`scripts/build-release.ps1 -Version 3.2.9.2`，输出 `dist-release/ScoutMind-FM27-V3.2.9.2-Windows-x64.zip` 与 `SHA256SUMS.txt`，并在打包后解压校验关键文件。

## 3. 启动脚本（Start-ScoutMind.ps1）

| 功能 | 实现 |
| --- | --- |
| 检查 Windows 版本 | 非 Win10/11 仅告警 |
| 检查 Python | 要求 3.11+，缺失则明确报错 |
| 检查端口 | 端口被占用直接失败（避免健康检查误连其它实例） |
| 首次初始化 | 自动创建 `backend/.venv` 并 `pip install -r requirements.txt` |
| 检查数据库 | 执行 `alembic upgrade head`（幂等） |
| 启动后端 | `uvicorn app.main:app --host 127.0.0.1 --port <Port>`，输出 stdout/stderr 到 `logs/` |
| 健康检查 | 轮询 `/api/v1/health`，最多 60 秒；失败时打印错误日志尾部并清理进程 |
| PID 记录 | 写入**实际监听端口**的进程 PID 到 `data/scoutmind.pid` |
| 输出 | 访问地址、API 文档、日志路径、数据库路径；默认打开浏览器 |

## 4. 停止脚本（Stop-ScoutMind.ps1）

- 只读取 `data/scoutmind.pid`，不按进程名批量结束；
- 校验命令行同时包含 `uvicorn` 与 `app.main:app`，且命令行或可执行文件位于本发布包目录；
- Windows 上 venv 的 `python.exe` 可能重定向到基础解释器，因此以命令行路径为归属依据（本轮实测修复）；
- 不匹配时拒绝结束并退出码 1。

## 5. 环境诊断（Check-Environment.ps1）

检查 Windows、PowerShell、Python 版本、后端虚拟环境、.NET Runtime、9 个关键文件、`data`/`logs` 写权限、磁盘空间、端口占用、数据库是否存在，输出 PASS/WARN/FAIL 与汇总；存在 FAIL 时退出码 1。

## 6. 数据库备份（Backup-Database.ps1 + backup_sqlite.py）

- 使用 SQLite backup API（WAL 下安全），不是裸文件复制；
- 文件名带时间戳，已存在则追加序号，绝不覆盖；
- 备份后执行 `PRAGMA integrity_check` 与大小校验；
- 不修改、不删除原数据库，输出完整备份路径。

## 7. 干净目录验收（真实执行）

解压 `ScoutMind-FM27-V3.2.9.2-Windows-x64.zip` 到全新目录 `temp_20261124_02/rc-clean`：

| 步骤 | 命令/动作 | 结果 |
| --- | --- | --- |
| 1. 文件完整性 | 解压 + `Check-Environment.ps1` | PASS 16 / WARN 3 / FAIL 0 |
| 2. 首次启动 | `Start-ScoutMind.ps1 -Port 8020` | PASS：自动建 venv、装依赖、迁移 24 个 migration、健康检查通过 |
| 3. API | `GET /api/v1/health` | `{"status":"ok","database":"sqlite"}` |
| 4. 前端 | `GET /` | 返回 `index.html`（生产构建） |
| 5. 静态资源 | `/assets/index-*.js` | 200 |
| 6. 刷新深链 | `GET /transfers` | 200 且返回 `index.html`（SPA fallback，刷新不 404） |
| 7. 未知 API | `GET /api/v1/does-not-exist` | 404 JSON 错误信封（不被 SPA 吞掉） |
| 8. 转会接口 | `GET /api/v1/transfers` | 200，`{"items":[],"total":0,"coverage":{...0.0}}`（Phase 2 修复在发布包内生效） |
| 9. 数据库 | `data/scoutmind.db` | 初始化成功，`alembic_version=b2c3d4e5f6a7` |
| 10. 日志 | `logs/backend.err.log` | 正常启动记录，无 ERROR |
| 11. 停止 | `Stop-ScoutMind.ps1` | PASS：校验归属后停止，端口释放 |
| 12. 再次启动 | `Start-ScoutMind.ps1` | PASS |
| 13. 数据持久化 | 停止前 `POST /agent/conversations`（id=1）；重启后 `GET /agent/conversations` | PASS：`count=1, ids=1` |
| 14. 备份 | `Backup-Database.ps1` | PASS：`backups/scoutmind-20261126-205114.db`，1,134,592 字节，完整性检查 ok |
| 15. 恢复 | 停止 → 用备份替换 `data/scoutmind.db` → 启动 | PASS：会话 id=1 仍在 |

## 8. 本轮在发布工程中修复的问题

| 问题 | 表现 | 修复 |
| --- | --- | --- |
| 前端无生产托管 | 发布包只有 API，界面需要 `npm run dev` | 后端新增可选静态托管 + SPA fallback（未配置时行为不变，CI 不受影响） |
| 启动脚本误判成功 | 目标端口被其它实例占用时，健康检查会连到旧实例并报成功 | 启动前检查端口占用，被占用直接失败 |
| PID 不可靠 | `Start-Process` 返回的进程与实际监听进程不一致，停止脚本找不到 | 启动后按端口解析实际监听 PID 写入 PID 文件 |
| 停止脚本误拒 | venv `python.exe` 重定向到基础解释器，按可执行文件路径判断会失败 | 归属判断同时接受命令行中的发布包路径 |

## 9. 环境依赖（必须写进安装说明）

- Windows 10/11 x64
- PowerShell 7+
- Python 3.11+（首次启动联网安装后端依赖）
- 运行发布包不要求 .NET / Node（Reader/Agent 为自包含单文件，前端为静态产物）
- 重新发布 C# 组件才需要 .NET 10 SDK

## 10. 结论

发布包已能在干净目录完成「解压 → 诊断 → 启动 → 访问 API/前端 → 停止 → 再启动 → 数据持久化 → 备份 → 恢复」全链路。

状态：**PASS**
