# V3.2.7.2 最终验收报告

- 分支：`codex/v3.2.7.2-save-identity-e2e`
- 基线：`origin/main = 187f4ad`
- 日期：2026-11-25
- 结论：**可在人工确认后合并**；真实 FM27 游戏内切换与远端 CI 结果仍未完成，不得对外宣称全部 PASS。

## 1. 验收门槛

| 门槛 | 结果 | 说明 |
| --- | --- | --- |
| 身份/会话协议冻结 | PASS | `save-identity/v1`，状态与错误码固定 |
| 后端身份 API | PASS | 8 个端点 + 审计查询，17 个专项测试 |
| Agent 只报证据 | PASS | 服务端封顶；客户端声明 verified 不生效（E2E 第 3 项） |
| 采集上下文校验 | PASS | `PATCH /captures` 校验身份/会话归属 |
| 切换即停止 | PASS（协议级） | 心跳指纹变化 → 会话失效 → 采集闸门阻断 |
| Worker 回滚 | PASS | 提交前守卫失败/中途异常均无残留行；同 scan_id 可重试 |
| 幂等 | PASS | 重复提交返回 `duplicate=true`，行数不变 |
| 审计不可变 | PASS | ORM 监听拒绝 update/delete；E2E 可查询完整链路 |
| 迁移安全 | PASS（SQLite） | head `d4b7c1e2f9a3`；downgrade 预检 safe；PG16 待 CI |
| 前端诊断 | PASS | `/save-identity` 展示状态/证据/会话/阻断/审计 |
| 全量回归 | PASS | 后端 550 passed / 8 skipped；Agent 31；Reader 214 + CLI 57；前端构建 |
| 真实 FM27 A/B 切换 | NOT_RUN | 无游戏环境；未用 Mock 冒充 |

## 2. 复现命令

```powershell
# 后端
cd backend
python -m pytest -q

# 迁移降级安全性（先 alembic upgrade head 到目标库）
python scripts/check_migration_safety.py <db-path> --json

# 真实 HTTP E2E（自动建临时库、启动 uvicorn、写证据）
python scripts/acceptance-save-identity-e2e.py

# Agent / Reader
dotnet test ScoutMind.sln -c Release
dotnet run -c Release --project live-reader/tests/ScoutMind.FMReader.Tests
dotnet run -c Release --project live-reader/tests/ScoutMind.Reader.Tests

# 前端
cd frontend
npm run build
```

## 3. 关键证据

- 状态总表：[STATUS.md](STATUS.md)
- 真实 HTTP：`live-http.json`（24/24，PASS 21→24 修正记录见脚本断言）、`environment.json`、`server.log`
- 迁移预检：`migration-safety.json`（`downgrade_below_992_safe = true`，`revision = d4b7c1e2f9a3`）
- 校验和：`SHA256SUMS.txt`
- 审计表不可变：`backend/tests/test_save_identity_api.py`
- 事务安全：`backend/tests/test_import_transaction_safety.py`

## 4. 风险与限制

1. **真实游戏内切换未验证**：E2E 使用真实 HTTP 与真实文件指纹，但未在 FM27 中实际 A→B 切换。合并前建议由人工在真实环境执行一次，并补充 `docs/evidence/v3.2.7.2/save-identity-e2e/` 证据。
2. **第一优先级证据可直接确认身份**：按协议，`game_internal_save_id`/`world_id` 可让注册直接落到 `verified`；若 Reader 证据来源被篡改，风险由本地只读边界与审计承担。E2E 已覆盖“仅次证据不能确认”。
3. **未解决冲突需要人工处置**：冲突身份不会被自动替换；当前只提供 `/verify` 与审计，不提供一键合并，避免误合并两个真实存档。
4. **PG16 未在本机验证**：CI 使用 `postgres:16` service；本地 SQLite 通过不代表 PG 全部行为，需以远端结果为准。
5. **手动 `sync` 路径不带上下文**：为兼容旧脚本，只有 `auto` 采集强制携带身份/会话；`sync --file` 仍走历史导入。若需全面强制，应另开任务。

## 5. 回滚方案

- 数据库：`alembic downgrade c3d8f1a2b407` 只删除本轮新增列/表/索引，不动 V3.2.7 结构。
- 代码：回退本分支提交即可；后端旧接口不依赖新表（新字段可空）。
- Agent：不启动 `auto` 即不触发身份注册/会话；手动 `sync` 行为与旧版一致。
- 前端：删除 `/save-identity` 路由即可，其他页面不依赖新 API。

## 6. 合并前人工确认项

- [ ] 在真实 FM27 中执行 A→B 切换，确认会话失效、采集停止、切回 A 后恢复。
- [ ] 查看远端 CI（含 PostgreSQL 16 job）结果。
- [ ] 确认 PR 不含自动合并/Release 动作。
