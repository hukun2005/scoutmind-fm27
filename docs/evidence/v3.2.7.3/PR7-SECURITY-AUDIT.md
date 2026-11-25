# PR #7（V3.2.7.2）深度安全审核

审核对象：`6aaaa31`（PR #7 合并提交，`codex/v3.2.7.2-save-identity-e2e` → `main`）
审核方式：逐函数阅读真实代码 + 真实并发测试复现，不依赖 PR 描述。

## 1. 身份验证

| 检查项 | 结论 | 证据 |
|---|---|---|
| 客户端声明是否被直接信任 | 否 | `cap_declared_status()` 按证据封顶：仅 secondary 最多 `candidate`；`verified` 需要 primary 证据，或 `user_confirmed` + secondary |
| 未解析指纹能否成为身份 | 否 | `si:v1:unresolved:` 前缀强制降到 `discovered` |
| 多候选未消歧 | 否 | `payload.ambiguous=True` 时最高 `discovered` |
| 人工确认门槛 | 是 | `verify_identity()` 要求指纹一致且存在 secondary 证据，否则 409 |
| 冲突身份能否被普通上报洗白 | 否 | `_TERMINAL_IDENTITY_STATUSES = {conflict, invalidated}` 只能显式 verify 恢复 |
| 同一存档不同指纹 | 受控 | 新身份与既有 verified 指纹冲突 → 新行直接 `conflict` + 审计，不替换旧身份 |
| 审计不可篡改 | 是 | `SaveIdentityAuditEvent` ORM 层拒绝 update/delete |

结论：身份层设计正确，未发现可利用的提权路径。**保留**。

## 2. Session 生命周期

| 检查项 | 结论 | 证据 |
|---|---|---|
| 会话唯一性 | 是 | `(fm_save_id, session_key)` 唯一，重复 start 复用 |
| 心跳与 build/指纹不一致 | 是 | `heartbeat()` 指纹或 build 不一致 → invalidate + 409 |
| 心跳超时 | 是 | 120s；只在写入口判定 |
| **会话失效是否阻止在途导入** | **否（P0-2）** | `invalidate_session()` 只改状态与审计，不推进任何代次；导入的 `final_guard` 只检查状态，不检查“代次”。切换与导入提交之间存在窗口 |

## 3. Capture 与 Worker

| 检查项 | 结论 | 证据 |
|---|---|---|
| Capture PATCH 上下文 | 部分 | 校验身份/会话归属，但允许“仅身份”写入，未要求会话 |
| `/imports/scan` 上下文 | 部分 | 接受 identity/session，但 `final_guard` 使用**独立 Session**在提交前复核 |
| **检查与提交的原子性** | **否（P0-1）** | `final_guard()` 在另一事务读取；`self.session.commit()` 在其后。经典 TOCTOU 窗口 |
| `/imports/transfers` | **否（P0-3）** | 仅 `resolve_save_context`，无最终复核，也无代次 |
| `/imports/squad-csv` | **否（P0-3）** | 完全不做身份校验，直接 `import_squad_csv` + commit |
| 手动 sync / CLI | **否（P0-3）** | Agent 手动同步调用同一 HTTP 入口但不带上下文；`scripts/*` 同样 |
| 任务幂等 | 部分（P1-1） | `(fm_save_id, scan_id)` 唯一；不同 scan_id 的重复提交可双写 |
| 取消任务 | 无入口 | 导入任务无 cancel API，`rejected` 状态也不存在 |

## 4. 并发实测复现（修复前）

* 两个线程同时导入不同 scan：`ensure_attributes` 与俱乐部创建触发 `UNIQUE constraint failed`，整次导入 500（P2-1）。
* 切换成功提交后，持旧 `final_guard` 的导入仍能 commit（P0-1/P0-2，由 `tests/test_import_concurrency.py` 的确定性窗口测试固化）。

## 5. 缺陷清单

| ID | 级别 | 描述 | V3.2.7.3 处理 |
|---|---|---|---|
| P0-1 | P0 | 最终校验与提交分属两个事务 | `WriteFence.assert_current()` 在同一事务内做条件 UPDATE |
| P0-2 | P0 | 会话失效不推进代次 | `save_write_gates.generation` + CAS 递增；失效即递增 |
| P0-3 | P0 | 手动 sync/CLI/transfers/squad-csv 绕过上下文 | 四个入口统一 `_require_write_fence()` |
| P1-1 | P1 | 无 operation 级幂等 | `import_jobs.operation_id` + `(fm_save_id, operation_id)` 唯一 |
| P1-2 | P1 | 导入进行中不复查心跳 | 上下文解析时校验心跳，fence 时校验代次/会话 |
| P1-3 | P1 | `rejected` 任务可被重试 | `retryable` 排除 `rejected`，重试必须新 operation |
| P2-1 | P2 | 并发导入唯一约束冲突 | `ensure_attributes` / 俱乐部创建改为 savepoint + 复读 |
| P3-1 | P3 | 诊断无代次 | `/save-write-gate` + 身份详情 `write_gate` |

## 6. 未修复/保留项

* `config.py` 中 `min_similar_sample` 等字段缩进位于 `model_post_init` 内（历史问题，与本任务无关，未改动以免扩大范围）。
* PostgreSQL 16 行级锁语义未在本机实测 → 由 CI 迁移与测试覆盖；本报告不声称本地 PG 通过。
