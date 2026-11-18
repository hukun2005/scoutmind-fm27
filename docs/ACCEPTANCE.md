# 验收清单（P0-5 / P0-6）

这两个阶段必须在装有 FM27 的机器上跑，因此文档给出**可执行的步骤 + 通过判据**；每跑一次都会在
`docs/acceptance/` 留下带时间戳的记录（该目录的 `.txt` 已被 gitignore，避免把主机名写进仓库）。

## P0-5 自研读取器验收

```powershell
# 1. 发布读取器（自包含单文件，输出到 publish\win-x64）
.\scripts\publish-windows.ps1

# 2. 记录 status + probe（probe 不通过不会 scan）
.\scripts\acceptance-live-reader.ps1

# 3. 只有在 probe 通过后才尝试扫描（产物写到 exports\）
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

## 一步步操作（推荐顺序）

以下命令都在仓库根目录 `C:\Users\hukun\Desktop\FM27` 执行。任何一步的报错都可以原样贴给我。

### 第 0 步：准备一次

```powershell
# 1) 确认后端能起来（另开一个窗口保持运行）
.\scripts\run-backend.ps1
# 没有这个脚本就手动：
#   .\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# 2) 新窗口里确认健康
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

中文显示乱码（常见于 GBK 控制台）时先执行 `chcp 65001`。

### 第 1 步：在 FMSuperScout 里导出一份真实数据

1. 启动 FM27，进入你的存档。
2. 启动 FMSuperScout，按 **F9**（或点 **New data**）。
3. 导出文件默认在 `%LOCALAPPDATA%\FMSuperScout\dump*.json`。确认它在：

```powershell
Get-ChildItem "$env:LOCALAPPDATA\FMSuperScout\dump*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, Length, LastWriteTime
```

### 第 2 步：先审查，不写库（P0-1）

```powershell
.\scripts\import-fmscout.ps1 -Validate
```

会打印 5 节报告：`[1] File`（版本/时间/scan_id）、`[2] Dataset`（球员数/唯一 ID/重复 ID）、`[3] Field coverage`、
`[4] Identity`、`[5] Risks`，最后一行是结论。判断方式：

| 结论 | 含义 | 你要做的 |
| --- | --- | --- |
| `pass` | 字段齐全、无未知字段 | 直接进入第 4 步 |
| `review` | 有需要人判断的项（多为没有伤病/工资字段） | 正常，继续；把报告发我一份 |
| `blocked` | 有阻塞项（例如没有球员、ID 重复） | 先不要导入，把报告发我 |

指定文件：`.\scripts\import-fmscout.ps1 -Validate -Path 'C:\...\dump.json'`

### 第 3 步：把这份导出登记为回归样本（P0-3）

```powershell
.\backend\.venv\Scripts\python.exe scripts\register_fixture.py
```

脚本会：去掉 `meta` 里的主教练/主机名等个人字段 → 复制为 `backend/tests/fixtures/fmsuperscout/real_sample_01.json`
→ 在 `manifest.json` 写入版本、导出时间、球员数、SHA-256、脱敏字段。

然后跑真实样本回归：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_fmscout_real_data.py -v
cd ..
```

`test_real_sample_converts_cleanly` 应该从 `SKIPPED` 变成 `PASSED`。失败就是真实字段和映射不一致，把输出发我。

### 第 4 步：导入并跑端到端（P0-6）

```powershell
# 导入（同一份重复导入会返回 duplicate=true，不会产生重复快照）
.\scripts\import-fmscout.ps1

# 端到端验收
.\scripts\acceptance-e2e.ps1
```

结果里 `FAIL` 必须为 0；`WARN` 通常是数据源没有统计/伤病字段，属于数据边界。

### 第 5 步：读取器 status / probe（P0-5）

```powershell
.\scripts\publish-windows.ps1          # 输出 publish\win-x64\ScoutMind.LiveReader.exe
.\scripts\acceptance-live-reader.ps1  # 自动在该路径查找读取器
```

- `probe` 通过（输出里有 `verified`/`supported`）才继续；脚本只有在这个前提下才会 `scan`。
- 你的构建是 `26620374` + 插件 `27.1.0+2505117`，当前**不在已验证清单**，所以预期结果是
  `UnsupportedVersion` 并拒绝扫描 —— 这是正确行为，不是故障。把 `docs/acceptance/live-reader-*.txt` 发我，
  我按实际 Build 决定补清单还是标注不支持。

### 第 6 步：一条命令收齐三份结果（可选）

```powershell
.\scripts\p0-handoff.ps1                 # 自动找最新 dump
.\scripts\p0-handoff.ps1 -Zip            # 顺手打包成 zip
```

输出目录 `exports\p0-report-<时间戳>\` 内含：

| 文件 | 对应 | 是否发我 |
| --- | --- | --- |
| `fmscout-validate.txt` / `.json` | P0-1 审查报告 | **是** |
| `acceptance-e2e.txt` | P0-6 端到端结果 | **是** |
| `acceptance-live-reader.txt` | P0-5 status/probe 记录 | **是** |
| `dump-raw.json` | 原始导出（含个人信息时不要外发） | 否，用第 3 步的脱敏样本代替 |

### 我拿到之后会做什么

- **审查报告**：核对字段覆盖率与人数；若与游戏内数量不符，改映射或让字段显式缺失。
- **真实样本**：把它固化成回归样本，跑 8 条回归；有失败就按真实字段修适配器，并补测试。
- **读取器记录**：若 Build 不兼容，把 `26620374` 写成明确的「暂不支持」记录；若 probe 通过，则完成 CA/PA、
  属性、合同的抽样核对。
- **E2E 结果**：按 FAIL 项逐个修；WARN 项写进文档的数据边界说明。
