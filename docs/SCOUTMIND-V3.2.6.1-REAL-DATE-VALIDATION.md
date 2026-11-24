# ScoutMind V3.2.6.1 真实 FM27 日期验证

- 验证日期：2026-11-24
- 环境：当前执行环境 **没有可运行的 FM27 游戏进程**
- 结论：**NOT_RUN / BLOCKED**

> 本文档不伪造任何真实游戏读取结果。所有标注 `NOT_RUN` 的步骤必须在有人值守的 Windows + FM27 环境中完成，
> 并把输出保存到 `docs/evidence/v3.2.6.1/` 后再更新本文件。

## 1. 验证前检查

| 检查项 | 要求 | 本次状态 |
| --- | --- | --- |
| 游戏进程 | `fm.exe` 正在运行且已载入存档 | NOT_RUN（无进程） |
| 游戏构建号 | 与兼容清单一致（26620374） | NOT_RUN |
| 插件版本 | 与 VersionGate 要求一致 | NOT_RUN |
| Reader 构建 | `ScoutMind.LiveReader` 可执行 | PASS（本机构建成功） |
| 存档 | 已知存档身份（用于后续能力验证） | NOT_RUN |

## 2. 端到端验证命令

### 2.1 基础诊断（不提供界面日期）

```powershell
dotnet run --project live-reader/ScoutMind.Reader -- world-date --diagnostics --json `
  --state "$env:TEMP\scoutmind-date-state.json" | Out-File -Encoding utf8 docs/evidence/v3.2.6.1/world-date-diagnostics.json
```

预期：

- `status` 为 `heuristic`、`ambiguous` 或 `unavailable`；
- `snapshot.status` 必须是 `BLOCKED`；
- 报告中每个候选都有 `classification`、`rejection_reason`、`confidence`；
- `candidates` 与 `rejected_candidates` 合计等于 `total_matches`。

### 2.2 人工界面日期验证

1. 在游戏内记录当前世界日期（例如界面显示 `2026-11-06`）；
2. 执行：

```powershell
dotnet run --project live-reader/ScoutMind.Reader -- world-date --diagnostics --json `
  --verify 2026-11-06 `
  --state "$env:TEMP\scoutmind-date-state.json" | Out-File -Encoding utf8 docs/evidence/v3.2.6.1/world-date-verify-01.json
```

预期：

- `date_summary.selected_date` = `2026-11-06`；
- `status` = `session_verified`，`confidence` = `session_verified`；
- 与界面日期不一致的候选必须带 `FUTURE_EVENT` 或 `INSUFFICIENT_EVIDENCE`；
- `snapshot.status` 仍为 `BLOCKED`（存档身份未验证）。

### 2.3 游戏内日期推进后再次验证

推进游戏日期（比赛/训练/继续），在界面确认新日期后重复 2.2，并把文件保存为 `world-date-verify-02.json`。

预期：

- `status` = `session_verified`；
- `verification_evidence` 出现日期变化记录；
- `candidates[0].observed_dates` 至少包含两个日期；
- 旧日期候选不会因为这个变化被错误提升。

### 2.4 日期回退（读档/回滚）测试

读档回到较早日期后执行 2.2。

预期：

- `status` = `date_rollback`；
- `confidence` 降为 `verification_pending`；
- `last_confirmed_date` 不被覆盖；
- `snapshot.status` = `BLOCKED`。

## 3. 证据记录模板

```text
日期：
游戏进程 PID：
进程启动时间：
构建号：
插件版本：
存档（若已知）：
界面日期：
Reader 选中日期：
候选总数：
保留候选：
排除候选（原因）：
可信度：
自动快照：
证据文件：
```

## 4. 本次已完成的替代验证

| 验证项 | 方式 | 结果 |
| --- | --- | --- |
| 候选全部进入诊断 | 模拟内存 + 单元测试 | PASS |
| 日期与参考日期间隔过滤 | 模拟内存 + 单元测试 | PASS |
| 同签名重复 → 歧义 | 模拟内存 + 单元测试 | PASS |
| 对象提示 → 比赛日期排除 | 模拟内存 + 单元测试 | PASS |
| 未来日期 → `FUTURE_EVENT` | 模拟内存 + 单元测试 | PASS |
| 界面日期不一致 → 不写入确认日期 | 追踪器单元测试 | PASS |
| 日期回退 → 降级 | 追踪器单元测试 | PASS |
| 结构指纹与日期无关 | 单元测试 | PASS |
| 自动快照安全门默认 BLOCKED | 单元测试 | PASS |

测试命令：

```powershell
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests   # 177 PASS / 0 FAIL
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests      # 55 PASS / 0 FAIL
dotnet test desktop-agent/tests/ScoutMind.Agent.Tests              # 16 PASS / 0 FAIL
```

## 5. 未通过/未执行项

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 真实 FM27 基础诊断 | NOT_RUN | 当前环境无游戏进程 |
| 真实界面日期匹配 | NOT_RUN | 同上 |
| 日期推进后复验 | NOT_RUN | 同上 |
| 日期回退复验 | NOT_RUN | 同上 |
| 真实候选总数 vs 旧实现 | NOT_RUN | 同上 |
| 自动快照开放前验证 | BLOCKED | 存档身份未实现 + 真实验证未完成 |

在完成上述 NOT_RUN 项之前，任何“当前日期已校准”的表述都不成立。
