# 真实 FM27 联调验收手册（V3.2.3）

目标：在真实 FM27 进程上验证「内存读取 → 扫描落盘 → 完整性校验 → 上传 → 导入 → 数据库持久化」的完整闭环。
本手册只做只读探测与正常上传，不改存档、不改内存、不装修改器。

## 0. 前置条件

- Steam 已启动，FM27 已进入**可操作**状态（已加载存档，不是主菜单）。
- 本机已构建：`dotnet build ScoutMind.sln -c Release`。
- 后端已迁移并启动：

```powershell
cd <repo-v323>\backend
$env:SCOUTMIND_DATABASE_URL="sqlite:///<repo-v323>/backend/data/live-v323.db"
$env:SCOUTMIND_DATA_DIR="<repo-v323>\backend\data\live-v323-data"
& <repo-desktop>\backend\.venv\Scripts\python.exe -m alembic upgrade head
& <repo-desktop>\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> 建议使用**新的空数据库**做真实验收，避免污染现有存档数据；验收结束后再决定是否导入正式库。

## 1. 环境确认

```powershell
cd <repo-v323>\publish\win-x64   # 或 dotnet run 的输出目录
.\ScoutMind.LiveReader.exe status --json
```

记录：`process_id`、`build`、`plugin_version`、`layout`、`gate.allow_scan`。

预期：`build=26620374`、`plugin=27.1.0+2505117`、`gate.allow_scan=true`、布局 `FM27_1`。

## 2. Probe 与结构化 UID 诊断

```powershell
.\ScoutMind.LiveReader.exe probe --json --report <repo-v323>\artifacts\live\probe-report.json
```

检查 `probe-report.json`：

- `available=true`，`scan_readiness=true`；
- `uid_diagnostics.totalObjects / validUids / sentinelUids / zeroUids / unreadableUids / duplicateAddresses`；
- `sentinel_samples` 的每一项包含对象地址、UID 原值、合同/俱乐部/姓名读取状态；
- `report.probes[].objectIds` 是同一份数据的完整投影。

**通过标准**：数字来自本次探测；没有硬编码；`scan_readiness` 与 `gate.allow_scan` 一致。
把这些数字与 `docs/evidence/live-probe-report.json`（本次新建）对照；此文件只保留计数与样本，不含姓名。

## 3. 完整扫描

```powershell
$scanDir="<repo-v323>\artifacts\live\scan"
New-Item -ItemType Directory -Force -Path $scanDir | Out-Null
.\ScoutMind.LiveReader.exe scan --output $scanDir --json
```

记录：`players`、`clubs`、`transfers`、`coverage`、`warnings`、`schema_version`（应为 `1.1`）、
信封/meta 的 SHA-256 与大小、导出耗时。

## 4. 上传与导入

```powershell
$env:SCOUTMIND_BACKEND_URL="http://127.0.0.1:8000/api/v1"
$scan = Get-ChildItem "<repo-v323>\artifacts\live\scan\scan-*.json" |
        Where-Object { $_.Name -notmatch 'meta|manifest' } | Select-Object -First 1
cd <repo-v323>\publish\win-x64
.\ScoutMind.Agent.exe sync --file $scan.FullName
```

Agent 现在会：

1. 把三件套移入 `queue\processing\`；
2. 补建/校验 `*.manifest.json`（payload/meta 双 SHA-256）；
3. 上传；超时后查询 `GET /imports?scan_id=…` 核实服务端是否已完成；
4. 只有确认完成才归档到 `sent/`；仍在导入则回 `pending/`，失败进 `failed/` 并附 `failure.json`。

若 44k 规模导入超过 60 s，预期输出类似：

```text
后端仍在导入（任务 #N status=running）：保留待重试，不归档。
```

稍后再次执行同一命令：应得到 `duplicate=true` 并归档。

## 5. 数据库验证

```powershell
$py = "<repo-desktop>\backend\.venv\Scripts\python.exe"
& $py -c @"
import sqlite3
c = sqlite3.connect(r'<repo-v323>/backend/data/live-v323.db')
print('instances', c.execute('select count(*) from player_instances').fetchone()[0])
print('snapshots', c.execute('select count(*) from player_snapshots').fetchone()[0])
print('unresolved', c.execute('select count(*) from unresolved_player_observations').fetchone()[0])
print('jobs', c.execute('select id, scan_id, status, schema_version from import_jobs').fetchall())
"@
```

**通过标准**：`schema_version=1.1`；`snapshots ≈ scan.players`；哨兵 UID 不出现在 `player_instances.save_local_uid`；
`unresolved` 与 probe 的哨兵数一致（本次真实数据可能为 0，需如实记录）。

重启后端后重复查询：数字不变。

## 6. 幂等与多存档

1. 重复上传同一扫描：期望 `duplicate=true`，快照数不变。
2. 若有两个存档：切换存档后重复第 2–5 步，检查 `save_id`、`player_instances`、`unresolved` 互不污染；
   没有第二个存档时记 `MultiSaveLiveTest = NOT_RUN`，不得虚构。

## 7. 游戏日期

1. 记录当前游戏日期（游戏内界面）。
2. 在日期推进后再次 `probe`/`date`，登记 `POST /api/v1/captures`：

```json
{
  "game_date": "2026-08-02",
  "reader_version": "0.1.0",
  "status": "date_detected",
  "date_source": "game_memory",
  "date_confidence": "verified",
  "date_read_status": "detected"
}
```

3. 同一天重复登记 → 更新同一条（`id` 不变）；日期倒退 → 返回 `date_read_status=regressed` 且
   `date_confidence=unverified`。

**注意**：`date_source` 只有经过真实内存字段验证后才允许填 `game_memory`；未验证时填 `reader_date_probe`
并给 `inferred`，或者保持 `unknown/unverified`。

## 8. 数据覆盖率

```powershell
cd <repo-v323>
& $py scripts\data_coverage_report.py --probe artifacts\live\probe-report.json `
    --dump <本次 dump.json> --scan <scan.json> `
    --database backend\data\live-v323.db --scan-id <scan_id>
```

验收：三层计数一致或差异有明确原因；不含姓名/地址/PID。

## 9. 结果登记

| 项目 | 状态 |
| --- | --- |
| FM27 Environment | PASS / NOT_RUN |
| Process / Module Detection | PASS / NOT_RUN |
| Native Reader Probe | PASS / NOT_RUN |
| UID Classification（valid/sentinel/zero/unreadable/duplicate） | PASS / NOT_RUN |
| OBJ_DUNI Applicability | PASS / NOT_RUN |
| 95% Safety Gate | PASS / FAIL / NOT_RUN |
| Dump + SHA256 | PASS / NOT_RUN |
| Backend Upload / Importer | PASS / NOT_RUN |
| PlayerInstance / PlayerSnapshot | PASS / NOT_RUN |
| Unresolved Persistence | PASS / NOT_RUN |
| Canonical Isolation | PASS / NOT_RUN |
| Idempotency / Restart Recovery | PASS / NOT_RUN |
| Game Date Detection / Snapshot | PASS / NOT_RUN |
| MultiSave Isolation | PASS / NOT_RUN |

任何 `NOT_RUN` 必须写原因；不得用模拟进程或系统时间替代真实结果。
