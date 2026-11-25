# 网络中断恢复与 operation 幂等验证报告（V3.2.7.4）

- Agent：`desktop-agent/ScoutMind.Agent/BackendClient.cs`、`SaveIdentitySync.cs`、`AgentApplication.cs`
- 后端：`importer.py`、`services/save_identity.py`、`api/routes_core.py`
- 结论：**PASS（协议级真实 HTTP）/ NOT_RUN（真实断网环境）**

## 1. Agent 传输重试

| 场景 | 行为 |
| --- | --- |
| 连接失败（`HttpRequestException`） | 最多 2 次尝试；第 1 次失败后延迟 500ms 再试（单次退避，不无限重试） |
| 上传超时 | **不重试**，返回 `duplicate=false` 的结果，提示「服务端可能仍在导入，将按 scan_id 核实」 |
| 4xx/5xx | 不重试，解析 `detail.code` |
| 409 `import_cancelled` / `operation_rejected` / `operation_conflict` / `scan_payload_mismatch` | 任务移入 `failed`，不无限重试 |
| 后端不可达 | 本轮不写入；`SaveIdentitySync.NetworkLost=true` |

退避上限由调用方轮次控制（`watch` / `auto` 的间隔），避免断网期间高频请求。

## 2. 会话与网络状态

- `POST /save-sessions/{id}/heartbeat` 接受可选 `reconnected: bool`；
- 后端记录 `previous_heartbeat` 与 `gap_seconds`；
- 满足任一条件写 `network_reconnected` 审计：
  - 客户端显式 `reconnected=true`；
  - 心跳间隔 > 60 秒；
  - 首次心跳；
- 常规心跳写 `session_heartbeat`；
- Agent 在连接失败后把 `_networkLost=true`，下一次心跳成功后带回 `reconnected=true` 并清零。

## 3. operation_id 幂等

| 场景 | 结果 | HTTP |
| --- | --- | --- |
| 同 `operation_id` + 同 payload | 返回原结果，`duplicate=true` | 200/201 |
| 同 `operation_id` + 不同 payload | `operation_conflict` | 409 |
| 同 `scan_id` + 不同 payload（不同 operation） | `scan_payload_mismatch` | 409 |
| 被拒绝的 operation 重放 | `operation_rejected`，带原 `rejected_reason` | 409 |
| 每次重放/冲突 | `attempt_count + 1` + 审计 | — |
| 并发同 operation | 唯一约束 + 原子重放，后到者按幂等/冲突处理 | — |

Agent 的 `operation_id` 来自固定任务上下文（`.context.json`），重启不改变；
仅在无上下文的历史任务上退化为 `"op-" + payload_sha256[..32]`。

## 4. 启动恢复

- Agent 启动遍历 `processing → pending → scans`；
- 读取 `.context.json`：
  - 缺失/损坏 → 整组移入 `quarantine/`（code `context_missing`），不上传；
  - 指纹与当前识别结果不一致 → 隔离（code `context_mismatch`）；
  - 一致 → 重新登记身份/新会话，但 **operation_id 与 payload checksum 不变**；
- 不再出现 `context=null` 上传。

## 5. 实测

`tools/runtime-acceptance/verify_operation_idempotency.py`（真实 HTTP）：

- 首次导入 → 重放（duplicate + 同一 job）→ 不同内容 409；
- 同 scan 不同内容 409 `scan_payload_mismatch`；
- `attempt_count ≥ 2`，审计含 `operation_replayed` / `operation_conflict`；
- rejected operation 重放 409；
- `reconnected=true` 心跳 → 审计 `network_reconnected`。

`tools/runtime-acceptance/simulate_network_failure.ps1`：

- `Unreachable` 模式验证连接失败与退避节奏（不需要管理员）；
- `FirewallBlock` 模式需要管理员；权限不足时标记 `BLOCKED_BY_PERMISSION`，不修改系统。

## 6. 未执行项

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 真实断网（拔网线/关路由）下的 FM27 + Agent 恢复 | NOT_RUN | 需要真实游戏与人工操作 |
| Windows 防火墙阻断 | NOT_RUN | 当前会话非管理员；脚本不会自动提权 |
| 多进程 Worker 并发 | NOT_RUN | 部署假设为单写进程（见 CANCELLATION-VALIDATION §7） |

真实恢复验收步骤见 [REAL-FM27-ACCEPTANCE.md](./REAL-FM27-ACCEPTANCE.md)。
