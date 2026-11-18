# 验收清单（P0-5 / P0-6）

这两个阶段必须在装有 FM27 的机器上跑，因此文档给出**可执行的步骤 + 通过判据**；每跑一次都会在
`docs/acceptance/` 留下带时间戳的记录（该目录的 `.txt` 已被 gitignore，避免把主机名写进仓库）。

## P0-5 自研读取器验收

```powershell
# 1. 发布读取器
dotnet publish .\live-reader\ScoutMind.LiveReader -c Release -o .\live-reader\publish

# 2. 记录 status + probe（probe 不通过不会 scan）
.\scripts\acceptance-live-reader.ps1

# 3. 只有在 probe 通过后才尝试扫描
.\scripts\acceptance-live-reader.ps1 -IncludeScan
```

| 验收项 | 通过条件 | 当前状态 |
| --- | --- | --- |
| 游戏版本识别 | 能读出真实 Build 与 `game_plugin.dll` 版本 | 你的构建 `26620374` + 插件 `27.1.0+2505117` 可被识别，但不在已验证清单 |
| 进程识别 | 能稳定找到 FM27 进程 | 待你执行 `probe` |
| 球员读取 | 能读到真实 ID、姓名、俱乐部 | 未验证 |
| CA/PA | 与游戏内或可信来源核对一致 | 未验证 |
| 属性 | 抽样球员属性与来源一致 | 未验证 |
| 合同 | 工资、到期时间核对正确 | 未验证 |
| 安全 | 只读；不改存档、不写游戏进程 | 代码无写入路径；待复核 |
| 版本不匹配 | 返回 `UnsupportedVersion` 并拒绝扫描 | 已实现，且当前就是该状态 |

**判据**：`status` 能报出 App ID、Build、插件版本；`probe` 输出 `verified`/`supported`；`scan` 产出的报文
能通过 `docs/DATA_PROTOCOL.md` 校验并成功导入。任何一项不满足，就停在 `probe`，不要为了出数而放宽版本校验。

如果 `probe` 失败：把 `docs/acceptance/live-reader-*.txt` 和游戏版本信息发我，我按实际 Build 补兼容清单或
明确记录「该 Build 暂不支持」。

## P0-6 端到端验收

```powershell
# 真实数据导入之后（FMSuperScout 或自研读取器都可以）
.\scripts\acceptance-e2e.ps1                 # 默认存档
.\scripts\acceptance-e2e.ps1 -SaveId 1       # 指定存档
.\scripts\acceptance-e2e.ps1 -RequireRealData  # 没有非合成数据就判 FAIL（给 CI 用）
```

脚本检查：健康检查、数据来源、导入记录、CA 覆盖率、阵容评分、表现分析、球探模型、交易类型、候选事件、AI 会话。

| 结果 | 含义 |
| --- | --- |
| `PASS` | 该环节有真实数据且接口正常 |
| `WARN` | 接口正常但数据源缺字段（统计、伤病等），属于数据边界 |
| `FAIL` | 接口或数据链路有问题，需要修 |

**判据**：`FAIL = 0`；`数据来源` 不再是 `synthetic_fixture`；阵容评分、球员详情、转会复盘页面上的数字与
游戏内抽样核对一致。

用演示数据跑过一次的结果：`PASS 9 · WARN 1 · FAIL 0`（WARN 是合成数据提示）。

## 还需要你提供的三样东西

1. **一份真实 FMSuperScout 导出**（脱敏后放 `backend/tests/fixtures/fmsuperscout/`，并在 `manifest.json` 登记
   版本与 SHA-256）。这是 P0-1/P0-3 从「工具就绪」变成「已验证」的唯一前提。
2. **P0-5 的 `status` / `probe` 输出**（或直接运行 `acceptance-live-reader.ps1`）。如果 Build 不兼容，我按输出补清单。
3. **一次真实导入后的 E2E 记录**（`acceptance-e2e.ps1` 生成的 txt）。有 FAIL 就贴给我。
