# ScoutMind FM27 V3.1.1 实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3.1-hardening`
- 起始基线：`3b323b8`（开始前 fetch 确认）
- 范围：**SM-025 / SM-026 / SM-027 / SM-028 / SM-029**
- 日期：2026-11-20
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 |
| --- | --- | --- |
| SM-025 | Recruitment API 权限完整性 | PASS |
| SM-026 | 金额解析与 ROI 计算正确性 | PASS |
| SM-027 | 身份合并跨存档一致性 | PASS |
| SM-028 | 成长预测回测质量 | PASS |
| SM-029 | Recruitment Engine 性能优化 | PASS |

---

## SM-025 Recruitment API 权限完整性 — PASS

### 修改文件

- `backend/app/api/routes_recruitment.py`
- `backend/app/api/routes_scouting.py`
- `backend/app/api/routes_transfers.py`
- `backend/tests/test_sm025_recruitment_permissions.py`（新增）

### 问题原因

- `search` / `compare` / `create_shortlist` 使用 `body.save_id or save.id`：`save` 依赖只校验查询串里的
  `save_id`，请求体里的 `save_id` 没有校验，可指向其他用户存档。
- `compare` 只把属于目标存档的球员筛出来，混合其他用户球员时不报错。
- 旧接口 `GET /transfers/{id}/cost`、`GET /transfers/investment`、`POST /transfers/deal-report`
  没有所有者校验，属于同一类越权。
- `POST /scouting/search` 同样使用未校验的 `body.save_id`。

### 修复方式

1. 三个请求体接口统一 `owned_save_or_404(db, body.save_id, user)`；未传时使用已校验的 active save。
2. `compare` 对每个 `instance_id` 调用 `instance_in_save_or_404`；结果数量不符也返回 404。
3. `deal-report` 校验目标存档 + 球员属于该存档。
4. `transfer cost` 通过交易所属存档校验；`investment` 通过球员实例所属存档校验。
5. 所有拒绝统一 404（不泄露"存在但不属于你"）。
6. AI 服务继续用 `user_id` 校验存档；工具参数禁止 `save_id`。

### 新增测试（9 项）

- `search` 的 `body.save_id` 指向他人存档 → 404；
- `compare` 混合本人与他人球员 → 404；
- `compare` 的 `body.save_id` 指向他人存档 → 404；
- `create_shortlist` 的 `body.save_id` 指向他人存档 → 404；
- `scouting/search` 的 `body.save_id` 指向他人存档 → 404；
- `transfer cost` / `investment` / `deal-report` 跨用户 → 404；
- 自己的第二个存档 search/compare/shortlist 正常；
- AI 工具参数不能改变存档范围；AI 服务拒绝他人存档。

---

## SM-026 金额解析与 ROI 计算正确性 — PASS

### 修改文件

- `backend/app/ingestion/amounts.py`
- `backend/app/ingestion/transfer_history.py`
- `backend/app/analytics/roi.py`
- `backend/tests/test_sm026_amount_roi.py`（新增）

### 问题原因

- 旧解析只去掉逗号后 `float()`：`2,5`、`1,2,3`、`2.5.5` 会被接受或误解。
- `wage_contribution` / `sell_on_pct` 用"删除所有非数字字符"的方式解析，`12k` 会被当成 12。
- 附加条款金额缺失或状态未知时被跳过，`realized_profit` 仍会给出确定值。
- 租借交易使用 `base_fee` 计算现金成本，工资分摊/二转分成没有明确口径。

### 修复方式

1. 严格千分位正则：只接受每三位一组；拒绝 `2,5`、`1,2,3`、`2.5.5`、负数、超大值、未知后缀。
2. 空值保持 NULL；`N/A` 等明确标记为未知并给原因。
3. 新增 `parse_ratio`（0..100，支持 `10%`）与 `parse_plain_number`（不接受单位/符号），
   非法值按行拒绝（`invalid_wage_contribution` / `invalid_sell_on`）。
4. ROI 现金成本增加 `cash_cost_complete` / `cash_cost_lower_bound`：
   - 附加条款金额缺失或状态不在已知集合 → 成本不完整；
   - 成本不完整时 `realized_profit=NULL` 并写明原因；
   - 租借交易按 `loan_fee + paid addons` 计算现金成本，不按标称转会费；
   - 工资分摊明确说明"不是本队现金成本"，不抵扣；
   - 二转分成只在真实触发时才能成为收入，本接口不把比例折算成收入；
   - 跨币种买卖不给已实现收益。
5. 所有返回继续带 `algorithm_version`、`missing`、原因。

### 新增测试（21 项）

- 8 类非法金额（含 `2,5`、`1,2,3`、`2.5.5`、负数、`2,5000`）全部拒绝；
- 合法金额（0、小数、千分位、£/€、万）逐一验证；
- 空值与未知标记；
- 百分比/工资分摊严格解析与导入拒绝；
- 未知附加条款状态 → 现金成本不完整、已实现收益 NULL；
- 完整成本与下界的区分；
- 租借按租借费计算；
- 二转分成不折算收入；
- 缺少金额时全部 NULL + 原因。

---

## SM-027 身份合并跨存档一致性 — PASS

### 修改文件

- `backend/app/api/routes_identity.py`
- `backend/tests/test_sm027_identity_scope.py`（新增）

### 问题原因

`_merge_players` 迁移 `IdentityMatch` 时只按 `player_id` 过滤，同一 `Player` 在其他存档里的匹配证据
也会被改到保留身份，破坏其他存档的身份审计。

### 修复方式

1. 合并只迁移 `fm_save_id == conflict.fm_save_id` 的 `PlayerInstance` 和 `IdentityMatch`。
2. 冲突、审计记录、`Player` 行保留（不删除证据）。
3. 合并整体在一个事务内；异常统一 rollback，返回 500 `merge_failed`。
4. 其他存档的实例和匹配证据不受影响。

### 新增测试（2 项）

- 两个存档共用同一 `Player`：当前存档合并只迁移当前实例/匹配，另一个存档保持不变；
- 模拟 commit 失败：实例、匹配、冲突状态全部回滚。

---

## SM-028 成长预测回测质量 — PASS

### 修改文件

- `backend/app/analytics/forecast.py`
- `backend/tests/test_sm028_backtest_quality.py`（新增）

### 问题原因

- 回测门槛按原始快照数量，同一天多次扫描会虚增样本。
- 训练/验证点只按 `observed_at` 排序，`game_date` 与 `observed_at` 不一致时顺序可能错。
- 报告没有区分原始快照数、独立观测日数、有效样本数。

### 修复方式

1. 门槛改为**独立观测日**数量；同日重复只保留当天最后一次观测（明确策略）。
2. 排序以 `game_date` 优先、`observed_at` 兜底；训练只用验证点之前的数据。
3. 报告 `raw_snapshots`、`distinct_days`、`evaluated`、`skipped_incomplete`；
   MAE/RMSE/区间覆盖率使用同一批有效样本。
4. 缺少 CA 的快照不进入计数。

### 新增测试（5 项）

- 3 条快照但只有 2 个独立日 → 不满足 3 日门槛；
- 同日多条按最后一次观测；
- `game_date` 与插入顺序相反时按日期排序；
- 缺 CA 不计入；
- 计数一致性（raw ≥ distinct ≥ evaluated）。

---

## SM-029 Recruitment Engine 性能优化 — PASS

### 修改文件

- `backend/app/analytics/recruitment.py`
- `backend/tests/test_sm029_recruitment_performance.py`（新增）

### 问题原因

1. `_score_candidate` 每个候选都查一次属性字典（N+1）。
2. 每个候选都重算同位置 form 样本与身价分位（O(n²)）。
3. `candidate_pool` 用 5 万 ID 的 `IN (...)` 查属性，超过 SQLite 变量上限。
4. 搜索先在 Python 过滤，未把年龄/身价/工资/位置下推到 SQL。

### 修复方式

1. `ScoreContext`：属性字典、身价分位、form 样本每个池只算一次。
2. 属性/统计改为基于查询子查询的单条 SQL，不再拼大 `IN` 列表。
3. `_percentile` 改用 `bisect`，避免每个候选线性扫描。
4. `candidate_pool` 接收年龄/身价/工资/位置过滤并在 SQL 执行；搜索只对通过筛选的候选评分。
5. 排序键 `(-score, instance_id)`，分页稳定。
6. `with_stats=True` 返回 `pool_size` / `scored` / `elapsed_ms` / 下推的过滤条件；
   查询次数由测试用 SQLAlchemy 事件统计。

### 性能数据（真实 SQLite，5 万行）

| 场景 | 查询次数 | 耗时 | 池大小 |
| --- | --- | --- | --- |
| search 1 万球员 | 6 | 0.267 s | 6,667 |
| search 5 万球员 | 6 | 2.962 s | 33,334 |
| compare 5 人（5 万池） | 5 | 1.551 s | 50,000 |

查询次数与池大小无关（无 N+1）；5 万规模耗时约 3 秒。

### 新增测试（4 项）

- 1 万球员搜索：20 条结果、查询 ≤10、耗时 <3s；
- 5 万球员搜索：20 条结果、查询 ≤10、按分数稳定排序、耗时 <8s；
- 5 万池 compare 5 人：查询 ≤8；
- 缺失工资的球员仍保留 NULL 语义，不被当成 0。

---

## 质量门禁

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `cd backend; python -m pytest` | **309 passed** |
| 前端 | `cd frontend; npm ci; npm run build` | PASS |
| .NET | `dotnet build ScoutMind.sln -c Release` | 0 error |
| SQLite 迁移 | 数据库副本 `upgrade → downgrade -1 → upgrade` | PASS（当前 head `d2f7a91b64e0`；本轮无新迁移） |
| GitHub Actions | 推送后云端检查 | 见交付说明 |

## 未解决问题

1. **历史迁移 `992f85fb22b8` 仍无法 downgrade 到 base**（真实库跨存档重复 `scan_id`），升级不受影响；
   本轮按要求未修改旧迁移。
2. **SM-013 自动历史转会来源仍 BLOCKED**；本轮只修复金额与 ROI 口径。
3. **SM-018 真实 LLM 未联调**（无 API Key），保持 PARTIAL。
4. **SM-019 真实存档回测 NOT_RUN**：真实存档缺少多观测日数据。
5. **性能测试使用合成但真实的 SQLite 行**（50k 球员/快照），不是内存假对象；
   真实 5 万存档的耗时还会受磁盘与属性数据量影响，报告中的数字是下限参考。
6. 多币种仍不做汇率换算；ROI 对跨币种买卖直接返回 NULL。

## 状态汇总

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-025 | PASS | 权限补齐 + 9 项测试 |
| SM-026 | PASS | 严格金额 + ROI 完整性 + 21 项测试 |
| SM-027 | PASS | 跨存档合并 + 回滚 + 2 项测试 |
| SM-028 | PASS | 独立观测日 + 排序 + 5 项测试 |
| SM-029 | PASS | 6 次查询 / 5 万 3 秒 + 4 项测试 |
| SM-030+ | NOT_RUN | 本轮未授权 |
