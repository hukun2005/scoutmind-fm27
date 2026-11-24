# V3.2.7.2 验收状态（Save Identity E2E & Capture Safety）

- 任务：`Save Identity E2E & Capture Safety`
- 分支：`codex/v3.2.7.2-save-identity-e2e`
- 基线：`origin/main = 187f4ad`
- 日期：2026-11-25
- Pull Request：<https://github.com/hukun2005/scoutmind-fm27/pull/7>（未合并、未发 Release）
- 状态口径：PASS / PARTIAL / FAIL / NOT_RUN / BLOCKED
- 只读约束：本轮未修改 V3.2.7 已发布迁移，未删除或弱化任何测试断言，未把 CANDIDATE/DISCOVERED/UNKNOWN 写成 VERIFIED。

## 1. 阶段结论

| 阶段 | 结论 | 证据 |
| --- | --- | --- |
| Phase 0 仓库审计 | PASS | [PHASE-0-AUDIT.md](PHASE-0-AUDIT.md) |
| Phase 1 协议 | PASS | `docs/SCOUTMIND-V3.2.7.2-IDENTITY-PROTOCOL.md` |
| Phase 2 后端身份/会话 API | PASS | `backend/app/api/routes_save_identity.py`、`backend/tests/test_save_identity_api.py` |
| Phase 3 Agent 上报 | PASS | `desktop-agent/ScoutMind.Agent/SaveIdentitySync.cs`、`BackendClient.cs` |
| Phase 4 采集切换安全 | PASS（本机协议级） | `AgentApplication.cs`、`routes_capture.py` |
| Phase 5 Worker 回滚/幂等 | PASS | `backend/tests/test_import_transaction_safety.py` |
| Phase 6 审计 | PASS | `save_identity_audit_events` 不可变监听 + 审计查询 |
| Phase 7 迁移 | PASS（SQLite）/ NOT_RUN（PG16 本机） | `d4b7c1e2f9a3`、`migration-safety.json`；PG16 由 CI 的 PostgreSQL service 验证 |
| Phase 8 真实验收 | PARTIAL | [真实 HTTP E2E 24/24](save-identity-e2e/live-http.json)；真实 FM27 游戏内切换 **NOT_RUN** |
| Phase 9 前端诊断页 | PASS | `/save-identity`；`npm run build` 通过 |
| Phase 10 回归 | PASS | 后端 550 passed / 8 skipped；Agent 31；Reader 214 + CLI 57；前端构建通过 |
| Phase 11 CI/旧 PR | PARTIAL | CI 配置覆盖全部套件；PR 后由远端 CI 复跑（本地不冒充远端结果） |
| Phase 12 文档 | PASS | 实施报告、本状态页、FINAL-REPORT 与参考文档更新 |
| Phase 13-15 验收/PR | PARTIAL | 已推送分支并建 PR；未合并 main、未发 Release（等待人工确认） |

## 2. 真实 HTTP 端到端（24/24 PASS）

脚本：`scripts/acceptance-save-identity-e2e.py`（真实 uvicorn + 真实 SQLite + Alembic head，无 Mock 响应）。

覆盖并通过：

1. health / 建两个存档 A、B。
2. 注册 A：仅次证据 → `candidate`；重复注册幂等，证据不重复。
3. 客户端声明 `verified` 但只有次证据 → 仍被服务端封顶为 `candidate`。
4. 未验证身份的会话只能得到 `created`；心跳返回 `409 save_identity_unverified`。
5. `/verify`（actor + basis）后身份 `verified`；新会话 `verified`；心跳通过。
6. 携带身份/会话创建并 PATCH 采集记录成功。
7. 会话身份跨存档 → `409 save_context_mismatch`。
8. 心跳指纹变成 B → `409 save_context_mismatch`，会话 `invalidated`；采集闸门 `capture_allowed=false`。
9. 旧会话再 PATCH → `409 save_session_invalidated`。
10. 切回 A：身份仍 `verified`，新会话恢复，采集闸门放行。
11. 同存档出现不同指纹且声明 `verified` → 新身份 `conflict`，旧 `verified` 不被替换；闸门因未解决冲突阻断。
12. 审计包含 `registered` / `user_confirmed` / `session_started` / `session_invalidated` / `conflict_detected`；存档 B 无 A 的审计事件。

证据目录：[save-identity-e2e](save-identity-e2e/live-http.json)（`environment.json`、`live-http.json`、`server.log`、`SHA256SUMS.txt`、`migration-safety.json`）。

## 3. 未执行项（不得写成 PASS）

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| FM27 游戏内 A 存档 → B 存档真实切换并采集 | NOT_RUN | 本轮未启动 FM27；不伪造游戏内存读取 |
| FM27 真实文件指纹 A/B 重新测量 | NOT_RUN | 沿用 2026-11-24 实测指纹（证据在 `docs/evidence/v3.2.7/save-context/`） |
| Agent `auto` 对真实游戏的长时间循环 | NOT_RUN | 无游戏进程；仅单元测试与本地协议验证 |
| PG16 迁移/并发 | NOT_RUN（本机） | 本机无 PostgreSQL 16；以 CI 的 `postgres:16` service 结果为准 |
| 远端 CI 全绿 | PARTIAL | 推送后由 GitHub Actions 复跑，本地结果不替代远端 |

## 4. 安全约束核对

- 自动快照未被打开：本轮未新增开关，也未运行 `auto` 循环；`auto` 必须显式传 `--interval-minutes`。
- 未修改已发布迁移：新增迁移 `d4b7c1e2f9a3` 仅追加列/表/索引，`downgrade` 只删新增对象。
- 未删除测试、未降低断言：新增 17 个身份 API 测试、2 个迁移测试、6 个 Agent 测试、4 个事务测试。
- 未把未验证状态写为已验证：注册封顶规则、`/verify` 人工确认、冲突阻断均有测试与 E2E 证据。
- 未合并 main、未发 Release、未改任务书外文件。
