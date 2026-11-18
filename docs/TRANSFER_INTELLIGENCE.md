# Transfer Intelligence 设计说明

历史转会分析的目标不是给出一个“准确身价”，而是把可验证的历史成交变成可解释的参考区间。

## 1. 数据范围（方案 C）

- **全球层**：当前存档里能读取到的全部历史交易，用于市场价格统计与俱乐部行为画像。
- **自家俱乐部层**：本俱乐部参与的买入、卖出、租借、回购与附加条款，用于复盘与资产回报分析。

数据范围以实际扫描覆盖为准。导入时记录 `coverage`，每条统计都带样本量和覆盖率；覆盖不足时界面与 AI 必须明说。

## 2. 交易状态与费用口径

| 状态 | 处理 |
| --- | --- |
| `completed` | 唯一进入成交价统计的状态 |
| `pending` / `future` | 只进入报价/谈判数据，不作为成交样本 |
| `cancelled` / `failed` | 保留记录与原因，不作为成交样本 |
| `unknown` | 保留但不统计 |

费用组件（`transfer_fee_components`）：

| 类型 | 计入已支付 | 说明 |
| --- | --- | --- |
| `base_fee`（status=paid） | 是 | 基础转会费 |
| `installment`（paid） | 是 | 已支付分期 |
| `addon`（triggered） | 是 | 已触发附加条款 |
| `addon`（untriggered / conditional_unknown） | 否 | 潜在金额，单独展示 |
| `signing_bonus` / `agent_fee` | 视 status | 只有在明确 paid 时计入 |
| `loan_fee` / `sell_on` / `buy_back` | 视 status | 租借与二次转售单独口径 |

`effective_fee` 计算顺序：`paid` + `triggered` 组件之和 → `fee_paid` → `base_fee` → `NULL`。
`addons_potential` 永远不计入已支付金额。

## 3. 统计口径

`GET /api/v1/transfers/stats` 返回：

- `sample_size`：进入计算的成交笔数；
- `median` / `p25` / `p75` / `mean` / `min` / `max`（线性插值分位数）；
- `distribution`：等宽直方图；
- `coverage.fee` / `coverage.ca_at_transfer` / `coverage.contract_remaining_months`；
- `excluded.incomplete`（无金额）与 `excluded.non_completed`（非完成）；
- `algorithm_version` 与 `warnings`。

样本 < 20 时置信度为 `low`；覆盖率低于阈值会追加警告，例如“仅 41% 样本带成交时 CA，分位数未按 CA 校正”。

## 4. 相似交易

加权距离（0 最相似，1 最不像）：

| 字段 | 权重 | 归一化尺度 |
| --- | --- | --- |
| 位置组 | 0.15 | 不同位置组记 1.0 |
| 年龄（成交时） | 0.25 | 差值 / 6 年 |
| CA（成交时） | 0.30 | 差值 / 30 |
| PA（成交时） | 0.20 | 差值 / 40 |
| 合同剩余 | 0.10 | 差值 / 24 月 |

规则：

1. 目标球员缺失某字段 → 该字段权重置 0，记入 `missing_fields`。
2. 候选样本该字段覆盖率不足 → 权重按覆盖率打折，再整体归一化，输出 `effective_weights`。
3. 目标球员自身的成交记录被排除（不能用自己过去的价格证明自己现在的价格）。
4. 历史成交缺失成交时 CA/年龄时，该笔交易只能靠剩余字段参与比较，样本量随之下降。

## 5. 估值

`estimate_value` 只在可比成交 ≥ 5 笔时给区间：

```
median/p25/p75 = 可比成交 effective_fee 的分位数
blended = median * 0.6 + 当前身价 * 0.4   （当前身价存在时）
mid     = blended * 合同系数
low     = min(p25 * 合同系数, mid)
high    = max(p75 * 合同系数, mid)
```

合同系数：< 6 个月 0.70，< 12 个月 0.85，≥ 36 个月 1.05，其余 1.00。

样本 < 5 时：`insufficient_sample=true`，`low/mid/high` 全为 `null`，只返回原因与放宽建议。绝不输出“看似精确”的数字。

## 6. 俱乐部画像

`GET /api/v1/clubs/{id}/transfer-profile` 返回买入/卖出笔数、总额、中位数、净投入、23 岁以下签约比例、
租入/租出笔数、已实现利润（同一球员买入与卖出配对）与最大 5 笔交易。没有配对记录时 `avg_profit_per_sale=null`，
并提示无法计算已实现利润。

## 7. 自家交易复盘

`analyze_own_club_deal(transfer_id)` 用「同年龄段 ±2 岁、CA ±20、近两年」的同类成交做参照，给出该笔成交的分位
（≤25% 低价买入、≥75% 高价买入、其余价格合理）。这是相对市场的位置判断，不是对错判断。

## 8. 已知限制

- 早期年份的成交缺少成交时 CA/合同信息，相似度只能靠年龄与位置，样本会显著缩小。
- 不同货币不做换算，统计只使用同一 `currency` 的记录（当前实现以首条样本货币为准，混币场景需先统一）。
- 分期、附加条款的可读性取决于扫描器能提供多少组件；缺失时退化为总额口径，并在 `coverage` 中体现。
- 通胀与年代差异尚未建模（Phase 5 后续）。
