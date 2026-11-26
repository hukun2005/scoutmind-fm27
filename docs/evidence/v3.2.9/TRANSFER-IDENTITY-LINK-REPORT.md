# V3.2.9 历史转会身份关联报告

## 1. 目标与边界

为后续 Transfer Intelligence 提供身份基础，本阶段只做「资料补全 + 冲突识别」，不改写任何金额或交易语义。

- 只补齐 `transfer_history.player_instance_id` 为空的记录；
- 唯一姓名匹配才写关联；
- 多匹配进入人工审核，保持未关联；
- 零匹配保持未关联；
- 俱乐部变化、自由球员、退役都不改变身份；
- 租借 / 附加条款 / 未完成交易沿用既有字段，不混入基础转会费。

## 2. 数据模型审计

既有 `transfer_history` 已包含：`transfer_type`（permanent / loan / free 等）、`status`、`base_fee`、`fee_paid`、`addons_potential`、`loan_fee`、`fee_components`、`player_instance_id`。

因此**没有新增交易表**，只新增身份关联能力（复用 `player_identity_links` 与审核队列）。

## 3. 实现

`backend/app/services/transfer_identity.py`：

| 函数 | 作用 |
| --- | --- |
| `link_transfers(db, save_id)` | 补齐空关联；返回扫描/关联/多匹配/未匹配计数 |
| `transfer_link_summary(db, save_id)` | 转会总数、已关联、未关联、按类型/状态分布 |
| `transfer_identity_evidence(transfer)` | 审核界面用脱敏证据 |

API：`POST /identity/transfers/link`，`GET /identity/center/summary` 内含 `transfer_links`。

## 4. 自动化验证

`backend/tests/test_v329_transfer_identity.py`（6 项，全部 PASS）：

| 用例 | 结果 |
| --- | --- |
| 唯一姓名匹配 → 关联 | PASS |
| 同一球员两次转会 → 身份持续 | PASS |
| 多匹配 → 审核条目、不关联 | PASS |
| 无匹配 → 保持未关联 | PASS |
| 租借 / 自由 / 未完成状态保留 | PASS |
| 重复执行幂等 | PASS |

## 5. 真实数据

| 指标 | 结果 |
| --- | --- |
| 真实存档转会总数 | NOT_RUN |
| 真实已关联 / 未关联 | NOT_RUN |
| 真实冲突交易数量 | NOT_RUN |

## 6. 结论

- 转会身份关联工程能力：**PASS（自动化）**。
- 真实 FM27 历史转会关联：**NOT_RUN**。
