# V3.2.9.2 阶段 4 — 转会身份证据组合

## 1. 问题

V3.2.9 的 `link_transfers()` 在“姓名唯一匹配”时直接写 `player_instance_id`，
等价于用姓名确认身份，违反“姓名不是身份”的红线；也没有 `INSUFFICIENT_EVIDENCE` 路径。

## 2. 新的证据规则

`backend/app/services/transfer_identity.py`

姓名匹配只是**必要条件**，写入关联还必须有至少一项独立证据：

| 证据 | 规则 |
| --- | --- |
| 年龄一致性 | `transfer.player_age_at_transfer` 与「生日 → 转会日期」计算年龄误差 ≤ 1 岁 |
| 俱乐部一致性 | 转出/转入俱乐部名 == 实例当前俱乐部名（归一化后） |

判定：

| 情形 | 结果 |
| --- | --- |
| 多名球员同名 | 不关联，审核 `multiple_name_matches` |
| 同一球员多个实例 | 不关联，审核 `multiple_instance_matches`（含全部实例 id） |
| 有年龄或俱乐部证据 | 关联 |
| 有年龄证据且明确不一致 | 不关联，审核 `evidence_conflict` |
| 只有姓名（年龄/俱乐部均未知） | 不关联，审核 `insufficient_evidence` |
| 没有同名球员 | 不关联，计入 `unmatched` |

> 审核条目里的 `insufficient_evidence` 即任务书中的 `INSUFFICIENT_EVIDENCE` 状态；
> 返回汇总字段同名，便于前端/脚本直接判断。

其他约束：

- 只处理 `player_instance_id IS NULL`，不覆盖已有关联；
- 结果幂等，重复执行 `transfers_scanned == 0`；
- 租借 / 自由转会 / 未完成交易的状态与金额字段不被改写；
- 俱乐部变化、自由球员、退役不改变身份；
- 审核项按 `transfer_id` 去重（`extra` 参数），不会把多笔转会压成一条。

## 3. 新增/更新测试

`backend/tests/test_v329_transfer_identity.py`

新增：

- `test_name_only_is_insufficient_evidence`：仅姓名 → 未关联 + 审核项；
- `test_age_mismatch_goes_to_review`：年龄冲突 → 未关联 + `evidence_conflict`；
- `test_club_agreement_is_independent_evidence`：俱乐部一致 → 允许关联。

更新（加强而非放宽）：原有唯一姓名用例显式提供年龄证据后才允许关联。

## 4. 实际结果

```text
python -m pytest tests/test_v329_transfer_identity.py -q
9 passed
```

## 5. 限制

- 当前转会数据模型没有 UID/生日字段，因此“独立证据”只能来自年龄与俱乐部；
  若两者都缺失，系统保持未关联并进入人工审核，而不是猜测。
- 真实 FM27 转会数据验证：`NOT_RUN`（需要用户提供真实存档与转会记录，见 07）。
