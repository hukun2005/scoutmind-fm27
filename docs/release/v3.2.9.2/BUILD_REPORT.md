# ScoutMind FM27 V3.2.9.2 — 构建报告

## 1. 构建信息

| 项 | 值 |
| --- | --- |
| 版本 | `3.2.9.2` |
| 构建提交 | `d922a21`（`release/v3.2.9.2-stabilization`） |
| 构建时间 | 2026-11-26 21:18（Asia/Shanghai） |
| 构建命令 | `pwsh -File scripts/build-release.ps1 -Version 3.2.9.2` |
| 构建机 | Windows 11 x64、PowerShell 7、Python 3.13、Node 22/24、.NET 10 |

## 2. 产物

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `ScoutMind-FM27-V3.2.9.2-Windows-x64.zip` | **66,716,790 字节** | 发布候选包 |
| `SHA256SUMS.txt` | — | 校验文件 |

SHA256：

```
2d5e31fc6ce7e62e002edf923b04a38b9d24b9fc551d56823019485f6be1ee91  ScoutMind-FM27-V3.2.9.2-Windows-x64.zip
```

## 3. 包内关键文件

| 文件 | 大小 |
| --- | --- |
| `live-reader/ScoutMind.LiveReader.exe` | 37,977,302 字节（自包含 win-x64） |
| `live-reader/ScoutMind.Agent.exe` | 38,053,530 字节（自包含 win-x64） |
| `live-reader/compatibility.json` | 954 字节 |
| `live-reader/scanner.sample.json` | 335 字节 |
| `frontend/dist/index.html` | 生产构建 |
| `backend/app/**` | 源码，无 `.venv`、无 `__pycache__` |
| `backend/alembic/**` | 24 个 migration 到 `b2c3d4e5f6a7` |
| `scripts/*.ps1`、`scripts/backup_sqlite.py` | 运行脚本 |

包内不含：`.env`、数据库、备份、`node_modules`、测试数据。

## 4. 可复现步骤

```powershell
git checkout d922a21
cd frontend; npm ci; npm run build
cd ..
pwsh -File scripts/build-release.ps1 -Version 3.2.9.2
```

构建脚本会自动：

1. 前端生产构建（`vue-tsc --noEmit` + `vite build`）；
2. 复制后端源码与 migration；
3. `dotnet publish` 两个自包含单文件程序；
4. 复制配置、脚本与文档；
5. 生成 ZIP、`SHA256SUMS.txt`，并解压校验 14 个关键文件存在。

## 5. 构建校验

| 检查 | 结果 |
| --- | --- |
| ZIP 解压 | PASS |
| 14 个关键文件存在 | PASS |
| 干净目录 `Check-Environment.ps1` | PASS 16 / WARN 3 / FAIL 0 |
| 干净目录启动（8030 端口） | PASS（自动建 venv、迁移、健康检查） |
| 前端根路径与深链刷新 | PASS（`/` 与 `/transfers` 均 200） |
| `/api/v1/transfers` | PASS（200，`total=0`） |
| PID 记录与实际监听进程一致 | PASS（119984 / 119984） |
| 停止脚本 | PASS，端口释放 |

## 6. 注意事项

- 包体主要来自两个自包含 .NET 单文件程序（各约 38 MB），属预期；
- 首次启动需要联网安装 Python 依赖，约几分钟；
- 发布资产尚未上传到 GitHub Release，等待授权。
