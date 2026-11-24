# ScoutMind V3.2.6.1 跨重启日期验证

- 验证日期：2026-11-24
- 结论：**NOT_RUN / BLOCKED**

> 跨重启验证必须在真实 FM27 上完成。本次环境没有游戏进程，因此只完成逻辑与自动化测试，
> 不在文档中填入任何虚构的重启结果。

## 1. 要证明什么

1. 游戏重启后，同一存档的同一个逻辑日期对象仍能被重新定位；
2. 绝对地址变化不影响识别，逻辑身份（模块 + 结构指纹）保持一致；
3. 每次重启后都能用人工界面日期完成验证；
4. 达到 3 个独立进程会话后才允许 `restart_verified`；
5. 即使 `restart_verified`，只要存档身份未知，自动快照仍为 `BLOCKED`。

## 2. 操作步骤

### 会话 1

```powershell
dotnet run --project live-reader/ScoutMind.Reader -- world-date --diagnostics --json `
  --verify <界面日期> --state "$env:TEMP\scoutmind-date-state.json" |
  Out-File -Encoding utf8 docs/evidence/v3.2.6.1/restart-session-1.json
```

完成后**完全退出游戏**（确认 `fm.exe` 结束），再重新启动并载入同一存档。

### 会话 2

重复上面的命令，保存为 `restart-session-2.json`。

### 会话 3

再次完全退出、重启、载入同一存档，保存为 `restart-session-3.json`。

### 判定

第 3 次执行的输出中：

| 字段 | 期望 |
| --- | --- |
| `status` | `restart_verified` |
| `confidence` | `restart_verified` |
| `session.session_id` | 与前两次不同 |
| `candidates[0].logical_signature` | 三次一致 |
| `candidates[0].first_seen` | 保持在会话 1 的时间 |
| `candidates[0].read_count` | 随会话累计 |
| `snapshot.status` | `BLOCKED`（存档身份未验证） |

## 3. 反向测试（必须做）

| 场景 | 操作 | 期望 |
| --- | --- | --- |
| 地址变化 | 两次会话间发生堆布局变化 | 结构指纹不变，候选仍能关联 |
| 日期推进 | 会话之间推进游戏日期 | `observed_dates` 增加，不降级 |
| 读档回退 | 会话之间回退存档 | `date_rollback`，`last_confirmed_date` 不覆盖 |
| 界面日期不匹配 | 故意传入错误日期 | `verification_mismatch`，不写入确认日期 |
| 构建号变化 | 切换游戏版本 | 旧验证会话作废，重新从 `session_verified` 开始 |

## 4. 状态文件检查

```powershell
Get-Content "$env:TEMP\scoutmind-date-state.json" -Raw | ConvertFrom-Json |
  Select-Object build, last_session_key, last_confirmed_date
```

```powershell
(Get-Content "$env:TEMP\scoutmind-date-state.json" -Raw | ConvertFrom-Json).candidates |
  Select-Object logical_signature, last_address, read_count, verified_session_keys
```

期望：

- `verified_session_keys` 至少 3 个；
- `last_address` 可以变化；
- `logical_signature` 不变；
- `build` 与当前游戏一致。

## 5. 自动化替代验证

| 验证点 | 测试 | 结果 |
| --- | --- | --- |
| 三次独立会话 → `restart_verified` | `DateCandidateTrackerTests` | PASS |
| 地址变化但指纹相同 → 重新关联 | `DateCandidateTrackerTests` | PASS |
| 构建号变化 → 验证证据作废 | `DateCandidateTrackerTests` | PASS |
| `restart_verified` 但存档身份未知 → `BLOCKED` | `SnapshotSafetyGateTests` | PASS |
| 状态持久化往返 | `DateVerificationStoreTests` | PASS |

## 6. 当前阻塞项

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 真实三次进程重启 | NOT_RUN | 无真实游戏环境 |
| 真实地址变化复关联 | NOT_RUN | 同上 |
| 真实日期推进/回退 | NOT_RUN | 同上 |
| 存档身份验证 | NOT_IMPLEMENTED | 安全门保持 BLOCKED |
| 自动快照开放 | BLOCKED | 依赖于以上两项 |

在这三项真实证据齐备之前，V3.2.6.1 不允许声明“日期读取已跨重启验证”。
