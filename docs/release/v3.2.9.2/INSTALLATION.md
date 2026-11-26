# ScoutMind FM27 V3.2.9.2 — 安装与启动

发布类型：First Public Preview
适用平台：Windows 10 / Windows 11（x64）

## 1. 系统要求

| 项 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 或 Windows 11（64 位） |
| PowerShell | 7.0 及以上（`pwsh`） |
| Python | 3.11 及以上，且 `python` 在 PATH 中 |
| 磁盘 | 至少 2 GB 可用空间（依赖与数据库另计） |
| 网络 | 仅首次启动安装后端依赖时需要 |
| FM27 | 仅支持已验证构建，见 `COMPATIBILITY.md` |

运行发布包**不需要**安装 Node.js 或 .NET；前端是静态产物，读取器与代理是自包含单文件程序。

## 2. 解压

1. 解压 `ScoutMind-FM27-V3.2.9.2-Windows-x64.zip` 到任意目录（路径不要包含中文以外的特殊字符更稳妥）；
2. 不要解压到需要管理员权限的目录（如 `C:\Program Files`），建议 `D:\ScoutMind`；
3. 解压后目录应包含 `backend/`、`frontend/`、`live-reader/`、`scripts/`、`data/`、`logs/`。

## 3. 环境诊断

```powershell
cd D:\ScoutMind\ScoutMind-FM27-V3.2.9.2
pwsh -File .\scripts\Check-Environment.ps1
```

输出中 `FAIL` 必须为 0。常见 `FAIL`：

- 未找到 `python`：安装 Python 3.11+ 并勾选 "Add python.exe to PATH"；
- 缺少发布文件：重新完整解压 ZIP。

## 4. 启动

```powershell
pwsh -File .\scripts\Start-ScoutMind.ps1
```

首次启动会：

1. 在 `backend/.venv` 创建虚拟环境；
2. 安装 `backend/requirements.txt` 依赖（需要联网）；
3. 执行数据库迁移，创建 `data/scoutmind.db`；
4. 启动后端并自动打开浏览器。

默认地址：<http://127.0.0.1:8000>

其它参数：

```powershell
pwsh -File .\scripts\Start-ScoutMind.ps1 -Port 8010 -NoBrowser
```

端口被占用时脚本会直接报错并提示更换端口，不会误连其它服务。

## 5. 停止

```powershell
pwsh -File .\scripts\Stop-ScoutMind.ps1
```

只停止本发布包启动的进程（校验命令行与路径），不会结束其它 Python/Node 程序。

## 6. 备份与恢复

备份：

```powershell
pwsh -File .\scripts\Backup-Database.ps1
```

- 输出到 `backups/scoutmind-<时间戳>.db`，不会覆盖已有备份；
- 使用 SQLite 在线备份 API，WAL 模式下安全；
- 备份完成会做 `PRAGMA integrity_check`。

恢复：

1. 停止服务；
2. 把备份文件复制为 `data/scoutmind.db`（先移走现有文件）；
3. 删除同目录残留的 `scoutmind.db-wal`、`scoutmind.db-shm`；
4. 重新启动。

## 7. 接入真实 FM27

1. 启动 FM27 并进入存档；
2. 运行环境诊断确认 `live-reader/` 文件完整；
3. 验证读取器识别：

```powershell
cd .\live-reader
.\ScoutMind.LiveReader.exe status
.\ScoutMind.LiveReader.exe probe
```

4. 扫描并同步到本地后端：

```powershell
.\ScoutMind.Agent.exe scan --sync
```

如果 `live-reader/agent.json` 不存在，代理默认连接 `http://127.0.0.1:8000/api/v1`。自定义端口时创建：

```json
{
  "backendBaseUrl": "http://127.0.0.1:8010/api/v1",
  "apiToken": "",
  "saveName": "默认存档"
}
```

5. 首次扫描 4 万名以上球员时导入需要数分钟，期间界面可正常访问导入状态。

## 8. 数据位置

| 数据 | 路径 |
| --- | --- |
| 数据库 | `data/scoutmind.db` |
| 原始扫描报文 | `data/raw/` |
| 后端日志 | `logs/backend.out.log`、`logs/backend.err.log` |
| 备份 | `backups/` |
| 代理队列 | `live-reader/queue/` |

升级或卸载前请先备份 `data/` 与 `backups/`。

## 9. 常见问题

**启动时报 "端口已被占用"**
换一个端口：`Start-ScoutMind.ps1 -Port 8010`。不要结束不认识的进程。

**首次启动很慢**
正在下载并安装 Python 依赖，通常几分钟；失败时查看 `logs/` 与终端输出。

**页面能打开但没有数据**
需要先用读取器完成一次扫描并导入；内置演示数据默认不加载。

**读取器提示不兼容**
当前 FM27 构建不在已验证列表内，读取器会拒绝读取。见 `COMPATIBILITY.md`。

**导入中断**
重新运行 `ScoutMind.Agent.exe sync`；同一 `scan_id` 重传会被识别为重复，不会产生重复数据。
