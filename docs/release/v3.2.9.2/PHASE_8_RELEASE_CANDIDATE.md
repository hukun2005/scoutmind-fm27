# Phase 8：发布候选包（V3.2.9.2）

- 产物：`ScoutMind-FM27-V3.2.9.2-Windows-x64.zip`
- 位置：仓库 `dist-release/`（已加入 `.gitignore`，不与源码混提交）
- 构建提交：`d922a21`

## 1. 产物信息

| 项 | 值 |
| --- | --- |
| 文件 | `ScoutMind-FM27-V3.2.9.2-Windows-x64.zip` |
| 大小 | 66,716,790 字节（约 63.6 MB） |
| SHA256 | `2d5e31fc6ce7e62e002edf923b04a38b9d24b9fc551d56823019485f6be1ee91` |
| 校验文件 | `dist-release/SHA256SUMS.txt` |
| 压缩后内部条目 | 14 个关键文件全部存在（构建脚本自动校验） |

## 2. 目录结构

```
ScoutMind-FM27-V3.2.9.2/
├── backend/            app/、alembic/(24 migrations)、alembic.ini、requirements.txt
├── frontend/dist/      index.html + assets/
├── live-reader/        LiveReader.exe、Agent.exe、compatibility.json、scanner.sample.json
├── config/             app.example.json
├── data/               空（首次启动创建数据库）
├── logs/               空
├── scripts/            Start / Stop / Check-Environment / Backup-Database / backup_sqlite.py
├── INSTALLATION.md · RELEASE_NOTES.md · COMPATIBILITY.md · KNOWN_ISSUES.md
├── README.txt · VERSION.txt · LICENSE
```

## 3. 干净目录验收（最终包，真实执行）

目录：`temp_20261124_02/rc-final`（全新解压）

| # | 步骤 | 结果 |
| --- | --- | --- |
| 1 | `Expand-Archive` | PASS |
| 2 | `Check-Environment.ps1` | **PASS 16 / WARN 3 / FAIL 0** |
| 3 | `Start-ScoutMind.ps1 -Port 8030 -NoBrowser` | PASS（自动创建 venv、安装依赖、24 个 migration、健康检查） |
| 4 | `GET /api/v1/health` | `status=ok` |
| 5 | `GET /transfers`（前端深链刷新） | **200**，返回 SPA |
| 6 | `GET /api/v1/transfers` | **200**，`total=0`（Phase 2 修复生效） |
| 7 | PID 文件 vs 实际监听 | 一致：`119984 / 119984` |
| 8 | `Stop-ScoutMind.ps1` | PASS，端口释放 |
| 9 | ZIP 哈希复核 | 与 `SHA256SUMS.txt` 一致 |

## 4. 与上一版候选的差异

- 上一轮候选（`c24c1cfb…`）在验收中发现两个发布工程问题：端口被占用时误报成功、停止脚本因 venv 解释器重定向误拒；
- 已在 `Start-ScoutMind.ps1` / `Stop-ScoutMind.ps1` 修复并重新构建；
- 本最终包的启动/停止与 PID 记录已验证一致。

## 5. 未执行（需用户授权或环境限制）

| 项 | 状态 | 原因 |
| --- | --- | --- |
| 上传到 GitHub Release | NOT_RUN | 等待用户授权 |
| 创建 Tag / Release / Latest | NOT_RUN | 等待用户授权 |
| 在另一台干净机器安装 | NOT_RUN | 仅本机验证 |

## 6. 结论

发布候选包已生成并通过干净目录启动、停止、前端深链、API 与哈希校验。

状态：**PASS（上传与发布动作等待授权）**
