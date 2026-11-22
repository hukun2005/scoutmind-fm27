# ScoutMind FM27 V3.2 Phase 1 — SM-061A 阶段报告

- 分支：`codex/scoutmind-v3.2-field-capture`
- 基线：`3c01093`（main，审计后未漂移）
- 日期：2026-11-22
- 范围：**SM-061A 真实采集与字段证据**
- 状态：**PARTIAL**（结构/接口/持久化 PASS；真实 FM27 原始值采集成功，界面期望值待补）

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
6. Reader 现有 `Diag capture` 保持独立，不侵入扫描主路径；新增 `Diag capture-live` 从运行中的 FM27 读取真实原始值（不写内存、不改偏移），期望值必须由操作员按游戏界面填写。

## 3. 修改文件

| 文件 | 变更 |
| --- | --- |
| `backend/app/models.py` | 新增 `FieldEvidenceSample` |
| `backend/alembic/versions/b7c1e2f4a901_field_evidence_samples.py` | 新增表/索引/唯一约束 |
| `backend/app/schemas.py` | 新增批量采样请求模型 |
| `backend/app/api/routes_field_evidence.py` | 新增上传/摘要接口 |
| `backend/app/main.py` | 注册路由 |
| `backend/tests/test_sm061a_field_evidence_capture.py` | 新增 7 项测试 |
| `live-reader/ScoutMind.FMReader/Engine/LiveFieldCapture.cs` | 真实原始采样记录 |
| `live-reader/ScoutMind.FMReader/Engine/FMSuperScoutMemoryEngine.cs` | `CaptureLiveAsync` 只读采样 |
| `live-reader/tools/ScoutMind.FMReader.Diag/Program.cs` | `capture-live` 命令 |
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

## 7. 真实 FM27 采集结果（2026-11-22，游戏运行中）

- `Diag status`：pid 113864，build **26620374**，插件 27.1，gate **Verified / allow_scan=true**；
- 新增 `Diag capture-live`，从真实内存读取原始值；先用 5 名球员得到 30 条，再扩大扫描定位到截图中的 Jarrod Bowen（UID 29125842），新增 6 条界面配对样本；
- 通过 API 写入真实存档 `save_id=2`：共 **36 条**，`simulated=false`；
- 证据样例（UID 109160，Paul Ifill）：

| 字段 | 原始值 | 解码 | 说明 |
| --- | --- | --- | --- |
| PLAO_CA | `0x0030` | 48 | 与 2026-11-18 导出 CA=65 不一致，待界面/导出复核 |
| PLAO_PA | `0x007F` | 127 | 与导出 PA=127 一致 |
| PLAO_HEIGHT | `0x00B7` | 183 cm | 与导出 183 一致 |
| PERO_DOB | `0x07BB0125` | y1979 d293 | 与导出 birthYear=1979 一致 |
| CON_EXPIRY | `0x076C0002` | y1900 d2 | 异常年份，重复出现，保持 Candidate |
| CON_WEEKLY_WAGE | `0x00000000` | 0 | 未设置或非标准合同，未当真实 0 填值 |

### Jarrod Bowen（UID 29125842，截图界面核对）

| 字段 | 原始值 | 解码 | 界面期望 | 结果 |
| --- | --- | --- | --- | --- |
| PLAO_HEIGHT | `0x00AE` | 174 | 174 cm | 一致 |
| PERO_DOB | `0x07CC0163` | y1996 d355 | 1996-12-20 | 一致 |
| CON_EXPIRY | `0x07EE00B5` | y2030 d181 | 2030-06-30 | 一致 |
| CON_WEEKLY_WAGE | `0x0003D090` | 250,000 | 300,000/周 | **不一致**，需确认税前/税后或偏移语义 |
| PLAO_CA | `0x009C` | 156 | 界面不可见 | 保持 Pending |
| PLAO_PA | `0x00A0` | 160 | 界面不可见 | 保持 Pending |

单次界面配对只能到 **Candidate**；字段策略要求 2–3 个独立对象/观测才可能 Verified。
工资 250,000 vs 界面 300,000 不得通过改偏移“修正”，需要先确认字段语义。

前 30 条样本 `expected_value` 为空；Jarrod 的 6 条已配对界面值，其中身高/生日/合同到期一致、工资不一致。
所有字段仍为 Pending/Candidate，未达到 Verified 门槛。

## 8. 未解决问题

1. 真实原始值已入库并有 1 名球员的界面配对，但样本数未达字段门槛，Verified 仍为 0；
2. Reader 尚未自动上传采样（当前为 Diag 导出 + API 导入，避免侵入扫描主路径）；
3. 既有 `alembic check` 漂移未在本阶段处理（留给 SM-061B/后续迁移治理）；
4. 真实存档同日冲突治理不在本阶段范围；
5. UID 109160 的 CA 原始值 48 与旧导出 65 不一致，需人工确认是数据变化、对象类型还是偏移问题；不得直接调偏移。

## 8. CI

- run **44989473913**，提交 `b7e2bab`，**success**；
- Backend、PostgreSQL 16、AI isolation、.NET、Frontend 全部 success。

## 9. 状态

| 项 | 状态 |
| --- | --- |
| SM-061A 结构/接口/持久化 | **PASS** |
| SM-061A 真实采集 | **PASS**（真实原始值 + 1 名球员界面配对）；字段 Verified 仍 PARTIAL |
| PostgreSQL 16 | **PASS**（CI run 44989473913） |
| 下一阶段 SM-066A | **NOT_STARTED**（等待本阶段审查） |

完成后停止，不进入 SM-066A。
