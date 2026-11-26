# Phase 2：现有后端 Bug 修复（V3.2.9.2）

- 目标文件：`backend/app/api/routes_transfers.py`、`backend/app/analytics/transfers.py`
- 分支：`release/v3.2.9.2-stabilization`（基于 `main` @ `33882bc`）
- 数据口径：只改现有接口，不新增业务模型，不改 migration

## 1. 问题 1：`GET /api/v1/transfers` 引用未定义变量 `all_rows`

### 原始问题

`backend/app/api/routes_transfers.py` 的 `list_transfers()` 中：

```python
priced = [row for row in all_rows if row.effective_fee is not None]
...
sum(1 for row in all_rows if row.player_ca_at_transfer is not None) / total_rows
sum(1 for row in all_rows if row.contract_remaining_months is not None) / total_rows
```

### 根因

`all_rows` 在整个文件与整个包内都不存在（`grep all_rows` 仅命中这 3 行）。`list_transfers()` 是普通同步函数，没有任何 `all_rows` 定义或参数，因此每次请求都会在组装响应时抛出 `NameError`，FastAPI 返回 500。原有测试只覆盖 `/transfers/stats`，列表接口无测试，问题未被发现。

### 修改文件

- `backend/app/analytics/transfers.py`
- `backend/app/api/routes_transfers.py`

### 修复方式

- 新增 `transfer_list_coverage(session, save_id, filters)`：在**全量筛选结果**上统计 `effective_fee` / `transfer_date` / `player_ca_at_transfer` / `contract_remaining_months` 的非空比例。
  - 无位置/联赛筛选时使用单条聚合 SQL（`COUNT` + `COUNT(column)`），不装载 ORM 实体；
  - 有位置/联赛这类 Python 侧筛选时退回整集遍历，与 `count_transfers()` 的口径一致；
  - 空结果返回全 0，而不是用 `max(total, 1)` 掩盖。
- `list_transfers()` 改用该函数生成 `coverage`，删除对 `all_rows` 的三处引用。

## 2. 问题 2：`sort` 参数被静默忽略

### 原始问题

`GET /transfers` 接受 `sort`（默认 `-transfer_date`），`docs/API.md:172` 也声明了该参数，前端 `TRANSFER_SORT_OPTIONS` 提供 `-transfer_date` / `transfer_date` / `-effective_fee` / `effective_fee`，但 `fetch_transfers()` 始终按 `transfer_date desc, id desc` 排序。用户点「费用 ↓」不会有任何变化，且无任何提示。

### 根因

排序在 analytics 层硬编码，路由层未校验 `sort`。

### 修复方式

- `analytics/transfers.py` 新增白名单 `SORTABLE_TRANSFER_FIELDS = ("transfer_date", "effective_fee")` 与 `sort_key_of()`；
- `fetch_transfers(..., sort="-transfer_date")` 按 `-` 前缀决定升降序，`effective_fee` 使用 `NULLS LAST`，缺失金额不抢占首屏，第二排序键固定为 `id desc` 保证分页稳定；
- `routes_transfers.py` 在任何查询前校验，非法字段返回 `400 {"error": {"code": "invalid_sort"}}`，与 `/players` 的既有行为一致。

## 3. 统计口径复核

| 要求 | 实现 | 验证 |
| --- | --- | --- |
| 列表正常返回 | 已修复 `NameError` | `test_list_returns_rows_total_and_coverage` |
| 分页 / offset / limit | SQL 层 `LIMIT/OFFSET` | `test_limit_one_pages_through_every_row`、`test_offset_beyond_total_is_an_empty_page` |
| 筛选 | status / transfer_type / 日期 / 俱乐部 / 费用 / 年龄 / CA | `test_status_filter_keeps_pending_out_of_default_list`、`test_transfer_type_filter_does_not_merge_loans` |
| 排序 | `transfer_date`、`effective_fee` 双向 | `test_sort_by_effective_fee_both_directions` |
| 统计接口 | `transfer_price_stats` 仅统计 completed + 非租借类 | `test_list_and_stats_agree_on_completed_permanent_sample` |
| 空结果 | 空数组 + total 0 + coverage 0 | `test_empty_list_is_not_an_error` |
| 总数正确 | `COUNT` 子查询 | 上述分页用例 |
| Coverage 正确 | 全量筛选集，与页无关 | `test_coverage_is_stable_across_pages` |
| 当前页与全量不混淆 | coverage 走全量聚合，items 走分页 | 同上 |
| 未完成交易不算成交 | 默认 `status=completed`；stats 再按 status 过滤 | `test_status_filter_keeps_pending_out_of_default_list` |
| 传闻/候选不算成交 | 候选事件仍是 `TransferCandidate`，不进入 `Transfer` 列表 | 既有 `routes_transfers.py` 候选接口未改 |
| 租借与永久不合并 | `transfer_type` 精确筛选；stats 排除 `NON_STAT_TYPES` | `test_transfer_type_filter_does_not_merge_loans` |
| 缺失转会费不当作 0 | `effective_fee=None` 原样返回，coverage 下降 | `test_missing_fee_is_reported_not_zeroed` |
| 附加条款不计入已付 | `compute_effective_fee` 只累计 paid/triggered | `test_addon_components_are_potential_not_paid` |
| 多存档隔离 | `fm_save_id` 过滤 + `save_id` 参数 | `test_transfers_are_isolated_per_save` |

## 4. 新增回归测试

文件：`backend/tests/test_transfers_list_api.py`（13 个用例，覆盖任务书要求的 12 类场景 + 非法排序 + 排序双向）。

未删除任何旧测试，未降低任何断言。

## 5. 测试执行结果（真实输出）

```
python -m pytest -q tests/test_transfers_list_api.py
.............                                                            [100%]
13 passed
```

```
python -m pytest -q tests/test_api.py tests/test_analytics.py tests/test_p2_data_quality.py \
    tests/test_sm005_transfer_perf.py tests/test_sm_phase1.py
...........................................................              [100%]
59 passed
```

全量后端测试在 Phase 6 统一执行。

## 6. 影响面

- 只影响 `GET /api/v1/transfers` 的排序、覆盖率计算和错误码；
- `/transfers/stats`、`/transfers/similar`、`/transfers/valuation`、候选事件接口行为不变；
- 响应字段无删减，仅 `coverage` 的数值改为真实全量口径（原实现从未成功返回过该字段，因为请求直接 500）；
- 不涉及数据库结构、migration、身份治理与存档隔离逻辑。

状态：**PASS**
