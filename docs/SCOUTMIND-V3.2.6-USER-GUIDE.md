# ScoutMind FM27 V3.2.6 用户指南（RC）

## 1. 安装（当前仅开发者方式）

```powershell
git clone https://github.com/hukun2005/scoutmind-fm27.git
cd scoutmind-fm27
pwsh -File scripts/setup.ps1
```

## 2. 启动

```powershell
pwsh -File scripts/run-backend.ps1     # 后端 http://127.0.0.1:8000
pwsh -File scripts/run-frontend.ps1    # 前端
```

## 3. 连接 FM27

1. 启动 FM27 并加载存档；
2. 运行读取器自检：`ScoutMind.LiveReader.exe probe --json`；
3. 兼容时（`scanAllowed=true`）可执行 `scan`。

## 4. 读取游戏日期

```powershell
ScoutMind.LiveReader.exe world-date --json
```

返回 `date` 与 `confidence`。当 `confidence=heuristic` 时表示“结构 + 最新日期”推断，
**不等于官方验证**；请与游戏界面核对。

## 5. 导入数据

```powershell
ScoutMind.Agent.exe sync
```

前端可查看球员、成长、转会页面。

## 6. 自动采集

**当前不可用（默认关闭）。** 原因：日期定位为启发式、没有持久化 Worker。
界面会显示明确提示，不会伪造进度。

## 7. 备份与恢复

```powershell
# 备份
Copy-Item backend/data/scoutmind.db backups/scoutmind-$(Get-Date -f yyyyMMdd).db
# 恢复
Copy-Item backups/scoutmind-YYYYMMDD.db backend/data/scoutmind.db
```

恢复前请停止后端。

## 8. 常见问题

| 现象 | 处理 |
| --- | --- |
| `game_not_running` | 启动 FM27 并加载存档 |
| `unsupported_build` | 当前 Build 未登记，禁止扫描 |
| `world-date` 返回 `ambiguous` | 同一天多条记录，请与界面核对 |
| 导入很慢 | 44k 规模约 7 分钟；属正常 |
