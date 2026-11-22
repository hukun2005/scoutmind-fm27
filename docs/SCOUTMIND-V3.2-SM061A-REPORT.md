# ScoutMind FM27 V3.2 Phase 1 — SM-061A 阶段报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 基线：`3c01093`（main，审计后未漂移）
- 日期：2026-11-22
- 范围：**SM-061A 真实采集与字段证据**
- 状态：**PASS（结构/接口/持久化）**；真实 FM27 采集 **NOT_RUN**

## 1. 修改前审计结论（摘要）

- 工作区干净，main/HEAD 与远程一致；
- 已有 `FieldValidationCapture`、`FieldEvidence`、`Diag capture`，但采样只停留在导出文件，无服务端持久化/API；
- 真实存档只有 1 个 game_date，同日重复 48,089 组，本轮不删除任何历史数据；
- `alembic check` 存在既有 schema 漂移（既有问题，本阶段不扩大修改范围）。

## 2. 技术方案

1. 新增 `field_evidence_samples` 表，按 `(fm_save_id, player_instance_id, field_id, observed_at)` 唯一；
2. 新增 `POST /field-evidence/captures` 与 `GET /field-evidence/summary`；
3. 采样可用 `player_instance_id` 或 `player_instance_uid` 定位，服务端强制存档归属；
4. 模拟样本不得标记 Verified；同一批次重复直接 422；跨批次重复幂等返回 duplicates；
5. 所有校验在写库前完成，失败不产生写入；
6. Reader 现有 `Diag capture` 保持独立，不侵入扫描主路径；真实采集仍 NOT_RUN。

## 3. 修改文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/models.py` | 新增 `FieldEvidenceSample` |
| `backend/alembic/versions/b7c1e2f4a901_field_evidence_samples.py` | 新增表/索引/唯一约束 |
| `backend/app/schemas.py` | 新增批量采样请求模型 |
| `backend/app/api/routes_field_evidence.py` | 新增上传/摘要接口 |
| `backend/app/main.py` | 注册路由 |
| `backend/tests/test_sm061a_field_evidence_capture.py` | 新增 7 项测试 |
| `scripts/pg_migration_validation.py` | 期望 head 更新到 `b7c1e2f4a901`，加入新表检查 |

## 4. 数据库变更

新增：

- 表 `field_evidence_samples`（save/instance 外键、字段、原始值、期望值、build/plugin/layout、game_date、observed_at、source、status、simulated、时间戳）；
- 唯一约束 `uq_field_evidence_save_instance_field_time`；
- 索引：save、instance、`(save,status)`、`(save,field)`。

未修改任何历史迁移；未删除历史数据。

### 验证

- SQLite 空库：`upgrade head → downgrade -1 → upgrade head` 成功；
- 真实数据库副本：同一往返成功，`alembic current = b7c1e2f4a901 (head)`；
- PostgreSQL 16：由 CI `postgres-migrations` job 执行（结果见 CI）。

## 5. 自动化测试

`backend/tests/test_sm061a_field_evidence_capture.py`（7 项）：

1. 上传成功 + 重复幂等；
2. 同字段不同观测时间算独立样本；
3. UID 解析成功/未知 UID 404；
4. 其他用户实例 404 且无写入；
5. 模拟样本 Verified 422 且无写入；
6. 批次内重复 422 且无写入；
7. 摘要区分 real/simulated。

结果：**7 passed**（本地）；阶段结束全量后端 **368 passed, 3 skipped**。

## 6. 代码审查

- 权限：复用 `get_active_save` + `instance_in_save_or_404`，不信任客户端 save/instance；
- 写入前校验；批量失败不产生部分写入；
- 不修改 Reader 扫描、不改内存偏移、不删除原始快照；
- 模拟/真实通过 `simulated` 与 `source` 区分；
- 摘要只读，不篡改原始数据。

## 7. 未解决问题

1. 真实 FM27 采集 **NOT_RUN**（游戏未运行），没有真实样本入库；
2. Reader 尚未自动上传采样（当前为 Diag 导出 + API 导入，避免侵入扫描主路径）；
3. 既有 `alembic check` 漂移未在本阶段处理（留给 SM-061B/后续迁移治理）；
4. 真实存档同日冲突治理不在本阶段范围。

## 8. 状态

| 项 | 状态 |
| --- | --- |
| SM-061A 结构/接口/持久化 | **PASS** |
| SM-061A 真实采集 | **NOT_RUN** |
| PostgreSQL 16 | CI 验证（见 run 链接） |
| 下一阶段 SM-066A | **NOT_STARTED**（等待本阶段审查） |

完成后停止，不进入 SM-066A。
