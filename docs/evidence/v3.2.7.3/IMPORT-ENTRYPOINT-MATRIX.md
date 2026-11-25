# 写入入口清单与统一保护（V3.2.7.3）

所有入口最终都落到 `ScanImporter` 或采集记录服务；保护统一在入口层与提交层两道：

1. 入口层：`backend/app/api/routes_core.py::_require_write_fence()` → `resolve_write_context()`。
2. 提交层：`backend/app/services/write_safety.py::WriteFence.assert_current()`，在业务事务内执行。

| 入口 | 代码位置 | V3.2.7.2 身份验证 | V3.2.7.3 策略 | 结论 |
|---|---|---|---|---|
| 自动采集（Agent auto） | `desktop-agent/ScoutMind.Agent/AgentApplication.cs` → `POST /imports/scan` | `EnsureAsync` 后带 identity/session，但无最终原子校验 | 带 identity/session/operation_id；服务端 fence 原子校验 | 强制 WriteContext |
| 手动 sync | `AgentApplication.SyncOneAsync` → 同一 HTTP 入口 | 不带上下文 | 带 `SaveContextQuery` + `operation_id`；gated 存档缺上下文 409 | 强制 WriteContext |
| `scan --sync` | `scripts/*` / Reader CLI → `POST /imports/scan` | 不带上下文 | 同上；首个会话建立后自动进入强制模式 | 强制 WriteContext |
| CLI 导入 | `POST /imports/scan` | 可绕过 | 统一入口；缺上下文且存档已有 gate → 409 | 强制 WriteContext |
| HTTP：`POST /imports/scan` | `routes_core.py` | `final_guard` 独立事务 | `_require_write_fence` + `WriteFence` | 强制 WriteContext + Epoch |
| HTTP：`POST /imports/transfers` | `routes_core.py` | 仅 `resolve_save_context` | 同 scan；缺上下文 409 | 强制 WriteContext + Epoch |
| HTTP：`POST /imports/squad-csv` | `routes_core.py` | 无校验 | 提交前 `fence.assert_current()` | 强制 WriteContext + Epoch |
| HTTP：`POST/PATCH /captures` | `routes_capture.py` | 允许仅身份 | `resolve_write_context`；gated 存档必须带会话 | 强制 WriteContext |
| 后台 Worker（导入线程） | `asyncio.to_thread(ScanImporter.import_*)` | `final_guard` 独立连接 | 同一事务内 fence UPDATE 后 commit | 强制 Epoch Fencing |
| 重试（重新提交） | 客户端再次 POST | 无约束 | 同 `operation_id` 幂等；`rejected` 不可重试，需新 operation | 重新验证上下文 |
| 存档切换 | `POST /save-sessions/{id}/switch`；`invalidate` 内部 | 仅改会话状态 | CAS 递增 generation + 失效全部旧会话 + 审计 | 原子切换 |

## 兼容性边界

* `save_write_gates` 行存在 = 存档已进入 V3.2.7.3 协议，此后所有导入必须携带完整上下文，**没有**“缺上下文自动绑定当前存档”的回退。
* 从未建立过 gate 的历史存档保留旧写入路径，但：
  * 每次旧写入都记录 `legacy_write_allowed` 审计事件；
  * `SCOUTMIND_WRITE_SAFETY_LEGACY_ALLOWED=false` 可整体关闭旧写入（返回 409 `write_context_required`）；
  * 旧写入不会自动切换到其他存档（`save_id` 必须显式给出）。

## 任务状态

沿用现有 `import_jobs.status`：`running → succeeded / partial / failed`，V3.2.7.3 新增 `rejected`。

* `rejected`：fence 失败，事务已回滚，`rejected_reason` 记录稳定错误码；
* `GET /imports/{job_id}` 的 `retryable` 不包含 `rejected`；
* 同一 `operation_id` 的成功/拒绝结果会被幂等复用，不会重复写入。
