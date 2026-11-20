# 历史转会数据来源调查报告（SM-013 第一部分）

- 日期：2026-11-20
- 目标：回答"FM27 的历史转会数据能否被可靠、合法地自动获取"，再决定 SM-013 能走到哪一步。
- 结论先行：**没有任何已实现的自动来源能提供完整历史交易**；本轮实现的是人工/第三方 CSV、JSON 导入管道，
  自动抓取标记为 `BLOCKED`，不以 `transferDate` 或 `transferTo` 推断历史成交。

## 1. 已调查的来源

| 来源 | 获取方式 | 支持 FM 版本 | 字段覆盖 | 准确性 | 更新 | 许可 | 可自动化 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FMSuperScout 导出（当前主力） | 第三方读取器导出 JSON | FM27 | 球员/俱乐部/合同/部分可用性；**没有 transfers 数组** | 与游戏一致（已逐字段核对过） | 手动导出 | MIT | 否（需人工导出） | 历史交易缺失 |
| ScoutMind Native Reader（dump） | 只读进程内存 → dump → 映射 | 27.0 / 27.1 | 球员/俱乐部/属性/合同；`Transfers=0`（未定位转会结构） | 球员数据已验收；转会未验证 | 运行时扫描 | 自有 | 是 | **历史交易 BLOCKED** |
| FM 存档文件解析 | 未实现 | — | 未知 | 未知 | — | — | 否 | 未验证，不采用 |
| 官方/授权数据接口 | 不存在公开接口 | — | — | — | — | — | — | 不可用 |
| 手工整理 CSV | 用户/分析师整理 | 任意 | 取决于文件 | 取决于来源 | 手动 | 用户提供 | 半自动 | **本轮采用** |
| 第三方数据站 | 未授权抓取 | — | — | — | — | 多数禁止自动抓取 | 否 | 不使用 |

## 2. 关键证据

1. `backend/app/ingestion/adapters/fmscout.py`：只有 dump 里存在 `transfers` 数组时才写入 payload，
   否则 `coverage.transfers=false`；球员行里的 `transferTo/transferDate` 只生成 `status='agreed'` 的待生效记录。
2. `live-reader/ScoutMind.FMReader/Engine/FMSuperScoutMemoryEngine.cs`：映射结果 `Transfers: 0`，
   `transfer` 探测长期为 `Inconclusive`（没有定位到转会记录）。
3. 真实导入（2026-11-20，50,365 球员）后 `transfer_history.available=false`，说明扫描数据里没有历史成交。
4. 仓内没有任何存档解析器或转会结构偏移表；`FM27_1_Layout` 的 50 个字段里没有 transfer 对象。

## 3. 已实现的部分（不依赖自动来源）

`POST /api/v1/imports/transfers/history`（CSV/JSON）：

- 状态与类型是两个独立维度，取值受限；`unknown` 状态直接拒绝，绝不默认 completed；
- 必填：球员名、日期、状态、类型、转入俱乐部（release 除外）；
- 去重：来源记录号唯一 + 跨来源自然键（球员/日期/双方/类型）；
- 每条交易保留 `raw_payload_json` 与来源 `transfer_sources`；
- 每次导入写 `transfer_import_runs` 报告（行数/导入/重复/拒绝/内容哈希）；
- 附加条款写入 `transfer_fee_components`，区分 paid/triggered 与 pending；
- 覆盖率接口 `GET /transfers/coverage`：只有存在 completed 记录时 `transfer_history.available=true`。

## 4. 判定

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 自动从游戏/导出获取完整历史转会 | **BLOCKED** | 无已验证来源；不伪造 |
| 人工/第三方 CSV/JSON 导入 | PASS | 有校验、去重、报告、审计 |
| 历史与未来/已达成分离 | PASS | status/type 独立；agreed 不计入历史 |
| 覆盖率表达 | PASS | 缺失明确显示不可用 |

## 5. 后续建议

1. 若后续版本上游导出新增 `transfers` 数组，先做字段核对再启用自动导入。
2. 若要支持 FM 存档解析，需要单独立项（文件格式、加密、版本差异、许可），不在本轮范围内。
3. 手工数据必须带来源名与记录号，禁止把估算值写成实际成交金额。

## 6. 金额与币种（SM-022 补充）

手工/第三方文件里的金额格式不统一，导入器现在按以下规则解析，解析失败即拒绝并给出行号：

| 输入 | 解析结果 | 币种 |
| --- | --- | --- |
| `2500000` / `2,500,000` | 2,500,000 | 由 `currency` 列决定 |
| `£2.5m` | 2,500,000 | GBP（符号优先） |
| `€12.5M` | 12,500,000 | EUR |
| `500K` | 500,000 | 由 `currency` 列决定 |
| `1.2 million` | 1,200,000 | 由 `currency` 列决定 |
| `150万` / `1200万` | 1,500,000 / 12,000,000 | 由 `currency` 列决定 |

- 没有 `currency` 列也没有货币符号 → 拒绝（不默认 EUR）；
- 符号与 `currency` 列冲突 → 拒绝（`mixed_currency`）；
- 原始字符串保留在 `fee_raw` / `addons_raw` / `loan_fee_raw` 与 `raw_payload_json`；
- 统计与情报接口在样本包含多币种时**不汇总金额**，只给出 `cash_by_currency` 与警告；
  汇率来源未配置前不做任何换算。
