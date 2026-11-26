# V3.2.9 全库扫描结果

## 1. 扫描执行状态

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| 扫描引擎实现 | 完成 | `identity_engine.start_scan` / `run_scan` / `resume_scan` |
| 自动化扫描测试 | PASS | 8 项（`test_v329_reconciliation.py`） |
| 真实存档全库扫描 | **PASS（Save A）** | 44,869 实例，Completed，0 失败 |
| 真实扫描耗时 | **870.13 s** | 约 51.6 行/秒（SQLite） |
| 真实扫描冲突数 | 2,674 | 全部为同名冲突；重复 UID 0 |

真实扫描明细见 `REAL-FM27-ACCEPTANCE.md`。

## 2. 自动化扫描可确认的行为

1. 3 个实例 → `processed_count=3`、`matched_count=3`、3 条 Candidate 关联。
2. `batch_size=1` + `max_batches=1` → 状态 `Paused`、游标推进；继续执行 → `Completed`，行数不重复。
3. 批次创建后数据规模变化 → `Failed` + `BATCH_CHECKSUM_MISMATCH`。
4. 存档身份指纹不一致 → `Failed` + `SAVE_IDENTITY_MISMATCH`。
5. 同一 `scan_id` 重复创建 → 返回同一批次，不产生第二行。
6. 扫描只产生 `Candidate`，不产生 `Verified`。
7. 同名 / 重复 UID → 审核条目 + 冲突状态，保留全部球员。

## 3. 数据质量分层（实现）

| 等级 | 条件 |
| --- | --- |
| A | UID Valid，无同名/重复冲突，关联为 Candidate |
| B | UID Valid，但存在跨存档候选或需复核字段 |
| C | UID Missing / Unsupported，或多候选 |
| D | Duplicate / Conflicted，或数据损坏 |

质量等级只用于展示与排序，**不代替 Verified**。

## 4. 报告输出

扫描统计通过 `GET /identity/center/summary` 以 JSON 返回，包含：

- `save_id`、生成时间；
- 球员实体数、存档内实例数；
- UID 统计（唯一、重复、按状态）；
- 身份关联按状态计数；
- 审核队列按状态计数；
- 扫描批次按状态计数；
- 转会关联摘要；
- 当前存档身份指纹（可为空）。

未实现 CSV 导出；任务书的 JSON 报告能力已具备，Markdown 由本证据文件承担。

## 5. 结论

- 扫描能力与可恢复性：**PASS（自动化）**。
- 真实全库统计（Save A）：**PASS**，44,869 实例 / 42,195 匹配 / 2,674 冲突 / 0 失败。
- 真实跨存档 A/B/A：**NOT_RUN**。
