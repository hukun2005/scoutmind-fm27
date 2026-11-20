# ScoutMind FM27 V3.1 第一阶段实施报告

- 仓库：`hukun2005/scoutmind-fm27`
- 分支：`codex/scoutmind-v3.1-hardening`
- 基线：`main` @ `d3a698d`（开始前重新 fetch）
- 范围：**SM-021 / SM-022 / SM-023 / SM-024**
- 日期：2026-11-20
- 状态口径：`PASS` / `PARTIAL` / `FAIL` / `NOT_RUN` / `BLOCKED`

## 总览

| 编号 | 任务 | 状态 | 提交 |
| --- | --- | --- | --- |
| SM-021 | 全 API 存档权限隔离 | PASS | 见提交记录 |
| SM-022 | 历史转会金额解析与币种标准化 | PASS | 见提交记录 |
| SM-023 | 转会 ROI 历史成本修正 | PASS | 见提交记录 |
| SM-024 | 成长预测可靠性修正 | PASS | 见提交记录 |

---

## SM-021 全 API 存档权限隔离 — PASS

### 修改文件

- `backend/app/api/deps.py`
- `backend/app/api/routes_recruitment.py`
- `backend/app/api/routes_decision.py`
- `backend/app/api/routes_transfer_intel.py`
- `backend/app/api/routes_transfer_history.py`
- `backend/app/api/routes_identity.py`
- `backend/app/api/routes_agent.py`
- `backend/app/agents/service.py`
- `backend/tests/test_sm021_save_ownership.py`（新增）

### 修复内容

1. `deps.py` 新增统一依赖：`owned_save_or_404`、`instance_in_save_or_404`、`transfer_in_save_or_404`、
   `shortlist_in_save_or_404`、`club_in_save_or_404`；所有分析路由复用它，删除各文件里重复的 `_owned_save`。
2. **短名单详情**原来只按 `shortlist_id` 查询，不校验归属；现在必须属于当前存档，否则 404。
3. **球员详情/模拟/预测/职业轨迹/投资**：先校验实例属于该存档，再分析。
4. **交易 ROI/俱乐部情报/覆盖率**：先校验交易/俱乐部属于该存档。
5. 请求里的 `save_id`：`get_active_save` 与 `owned_save_or_404` 双重校验；改 `save_id` 不能读别人存档。
6. AI：`service.answer_question(..., user_id=...)` 先验证存档归属，`routes_agent` 传入当前用户；
   模型参数仍禁止 `save_id`（服务端注入）。
7. 不再把"全局 API Token"当数据隔离；Token 只是入口授权，数据边界仍按存档所有者。

### 新增测试（10 项）

- 用户 A 不能读取用户 B 的球员详情；
- 不能查询用户 B 的转会 ROI；
- 不能读取用户 B 的短名单；
- 不能通过 `save_id` 访问用户 B 的存档（hidden-value / coverage / club intelligence）；
- 不能模拟/预测/查职业轨迹用户 B 的球员；
- AI 服务拒绝跨用户存档；
- 用户 A 访问自己的第二个存档正常。

---

## SM-022 历史转会金额解析与币种标准化 — PASS

### 修改文件

- `backend/app/ingestion/amounts.py`（新增）
- `backend/app/ingestion/transfer_history.py`
- `backend/app/models.py`
- `backend/alembic/versions/d2f7a91b64e0_transfer_fee_raw_amounts.py`（新增）
- `backend/app/analytics/transfers.py`
- `backend/app/analytics/club_intelligence.py`
- `backend/tests/test_sm022_amounts.py`（新增）

### 修复内容

1. 新增 `parse_amount`：支持 `2500000`、`2,500,000`、`£2.5m`、`€12.5M`、`500K`、
   `1.2 million`、`150万`、`1200万`；单位倍率明确（k=1e3、m=1e6、万=1e4、亿=1e8）。
2. 币种来源：货币符号优先；无符号时用 `currency` 列；两者冲突 → `mixed_currency` 拒绝；
   既无符号也无 `currency` → `missing_currency` 拒绝（不默认 EUR）。
3. 解析失败 → `invalid_amount` + 行号；绝不把 `2.5M` 存成 `2.5`。
4. 原始字符串写入 `fee_raw` / `addons_raw` / `loan_fee_raw`，币种原值写入 `currency_original`；
   `raw_payload_json` 继续保留整行。
5. 统计口径：`transfer_price_stats` 与俱乐部转会情报在样本含多币种时**不汇总金额**：
   `cash`/`median`/`net_cash` 返回 NULL，给出 `cash_by_currency` 与 `mixed_currency` 警告；
   未配置汇率前不做任何换算。
6. 迁移 `d2f7a91b64e0`：新增 4 列（原始金额 3 列 + 原币种），SQLite 往返通过。

### 新增测试（13 项）

- 8 种金额格式逐一断言金额与币种；
- 未知格式、缺币种、未知币种拒绝；
- 导入保留 `fee_raw` 与原币种；
- 非法金额给出行号；
- 符号与 currency 列冲突拒绝；
- 多币种俱乐部情报不求和；
- 价格统计多币种不混合。

---

## SM-023 转会 ROI 历史成本计算修正 — PASS

### 修改文件

- `backend/app/analytics/roi.py`
- `backend/tests/test_sm023_roi_history.py`（新增）
- `backend/tests/test_sm014_sm016_career_intel.py`（补充买入时点快照）

### 修复内容

1. 新增 `_snapshot_at_transfer`：只使用买入日期之前（含当天）最近一次快照作为历史工资/合同来源。
2. 会计成本 = 现金 + **买入时**周薪 × **买入时**合同剩余年限；当前工资/合同单独放在 `current`，
   仅用于展示，不参与历史成本。
3. 没有买入时点快照 / 没有工资 / 没有合同到期日 → `accounting=None`，`missing` 写明原因，
   不再用当前工资冒充历史。
4. 卖出具确定性排序：`transfer_date, id`，只接受 `permanent/loan_buyout/clause_release/swap`；
   `agreed/pending` 不参与已实现收益。
5. 是否"完成卖出"以 `status=completed` 为准；租借后买断按 `loan_buyout` 计入卖出。
6. 已支付附加条款计入现金成本；未触发只作为 `potential_addons`，不重复计入。
7. 买入/卖出币种不同 → `realized_profit=None` + 原因，不做汇率换算。
8. 估值变化仅作为 `valuation`，明确写"不是现金利润"；缺少成本/卖出时全部 NULL + 原因。

### 新增测试（5 项）

- 当前工资 50k、买入时工资 10k → 成本按 10k；
- 续约后合同 2031，买入时合同 2029 → 年限按 2029；
- 缺少买入时快照 → 会计成本 NULL 且有原因；
- 缺少历史转会费 → 现金成本/已实现收益 NULL；
- 未完成卖出被忽略、两笔卖出按日期+id 取最早；
- 租借买断计入卖出；跨币种卖出不给已实现收益。

---

## SM-024 成长预测可靠性修正 — PASS

### 修改文件

- `backend/app/analytics/forecast.py`
- `backend/tests/test_sm024_forecast_evidence.py`（新增）

### 修复内容

1. **同日去重**：同一天的多次扫描只保留当天最后一次，不再当作独立时间观察；提示重复条数。
2. **证据门槛**：
   - 0–1 个独立观测日：不给任何预测（`one_year`/`three_years` 均为 NULL）；
   - 2 个观测日：只给 1 年预测，3 年预测 NULL；
   - ≥3 个观测日：允许 3 年预测。
3. **置信度**：high 需要 ≥5 个观测日、跨度 ≥1 年且无异常；medium 需要 ≥3 个观测日、
   跨度 ≥0.25 年；否则 low，并在 `gaps` 说明原因。
4. **CA/PA 异常**：CA > PA 时标记 `anomalies`，预测不向上突破 PA，也不把 PA 当成必然未来。
5. **年龄曲线回退**：`basis.method` 明确写"年龄曲线统计假设"，`statistical_assumption=true`。
6. **回测**：只用预测时点之前的数据（train=前 N-1 条），同日去重；输出 MAE/RMSE/区间覆盖率；
   无满足样本时 `available=false` + 原因。

### 新增测试（7 项）

- 单快照无预测；
- 两快照无三年预测；
- 同日重复不算独立观测；
- CA>PA 标记且不外推；
- 年龄曲线回退标注假设；
- 5 个观测日 + 跨度 ≥1 年才 high；
- 回测只用历史点（MAE 断言）。

---

## 质量门禁

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端 | `cd backend; python -m pytest` | **267 passed**（本轮新增 35 项） |
| 前端 | `cd frontend; npm ci; npm run build` | PASS |
| .NET | `dotnet build ScoutMind.sln -c Release` | PASS（0 error） |
| 迁移 | SQLite `upgrade → downgrade -1 → upgrade` | 新迁移 `d2f7a91b64e0` 通过；全库 `downgrade base` 在历史迁移 `992f85fb22b8` 失败（见遗留） |
| GitHub Actions | 推送后检查云端 | 见下方 CI 记录 |

### CI

推送分支后通过 `gh run list --branch codex/scoutmind-v3.1-hardening` 检查云端实际结果，记录在此：
推送后运行 `gh run watch`（见交付说明），记录最终结论。

## 未解决问题

1. **历史迁移 `992f85fb22b8` 的 downgrade 在真实数据上失败**：
   它要把 `import_jobs` 的 scan_id 唯一约束改回全局唯一，但真实库中存在跨存档相同 scan_id，
   `UNIQUE constraint failed: _alembic_tmp_import_jobs.scan_id`。升级不受影响；
   修复需要单独设计数据迁移（去重/改名），本轮未改历史迁移。
2. **SM-013 自动历史转会来源仍 BLOCKED**：无已验证的游戏内/授权来源，只能 CSV/JSON 导入。
3. **SM-018 真实 LLM 未联调**（无 API Key），保持 PARTIAL。
4. **SM-019 真实存档回测 NOT_RUN**：真实存档没有 ≥2 个带 CA 的历史快照。
5. **ROI 未包含签字费/经纪人费用**：数据源没有这些字段，保持 NULL 并在 `missing` 说明。
6. **多币种统计**：没有汇率来源，所以只分组不汇总；需要汇率模块后再做跨币种汇总。

## 状态汇总

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| SM-021 | PASS | 权限隔离 + 10 项测试 |
| SM-022 | PASS | 解析/币种/原始值/多币种统计 + 13 项测试 |
| SM-023 | PASS | 历史成本/确定性卖出/币种 + 5 项测试 |
| SM-024 | PASS | 证据门槛/同日去重/CA-PA/回测 + 7 项测试 |
| SM-025+ | NOT_RUN | 本轮未授权 |
