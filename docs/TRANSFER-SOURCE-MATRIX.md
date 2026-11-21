# 历史转会来源能力矩阵（SM-045）

- 日期：2026-11-21
- 结论：**BLOCKED**（没有可靠、可授权的完整历史转会来源；保留 CSV/JSON 导入）
- 不允许：把当前俱乐部变化推断为已完成转会、把 agreed 当 completed、把租借当永久、伪造金额、无许可抓取

## 1. 来源能力矩阵

| 来源 | 版本/方式 | 历史转会 | 已达成协议 | 字段覆盖率 | 许可 | 自动化 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FMSuperScout 导出 | 1.7.3，`Dumper.ScanAgreedTransfers` | **无** | 有（`transferTo`/`transferDate`） | 球员 + 目标俱乐部 + 日期 | MIT | 手动导出 | 只能标 agreed，不能当历史 |
| Native Reader | 27.1 内存扫描 | **未定位** | 无 | 球员/俱乐部/合同/属性 | 自有 | 运行时扫描 | 无转会结构 |
| FM 存档文件 | 未实现解析 | 未知 | 未知 | 未知 | 未确认 | 否 | 不可行（本轮不实施） |
| 官方/授权 API | 不存在公开接口 | — | — | — | — | — | 不可用 |
| 手工 CSV/JSON | 用户/分析师提供 | **有**（由数据决定） | 有 | 取决于文件 | 用户提供 | 半自动 | **采用** |
| 第三方数据站抓取 | 未授权 | 声称有 | — | — | 多数禁止自动抓取 | 否 | 不使用 |

### 1.1 FMSuperScout 证据

`Dumper.cs` 只有 `ScanAgreedTransfers`（已达成但未生效的转会），没有历史交易数组；导出字段
`transferTo`/`transferDate` 被适配层映射为 `status=agreed`，不计入 completed。

### 1.2 存档文件可行性

- 需要解析 FM 存档容器、压缩/加密与版本差异；
- 没有公开格式文档或授权库；
- 不同版本布局可能变化；
- 本轮只做可行性判断，**不实现**，也不把猜测写成事实。

## 2. 字段覆盖率（若来源提供数据）

| 字段 | CSV/JSON 导入 | FMSuperScout | Native Reader |
| --- | --- | --- | --- |
| 球员姓名 | 是 | agreed 记录有 | 是 |
| 转会日期 | 是 | agreed 日期 | 否 |
| 状态（completed/agreed/...） | 是（受限） | 仅 agreed | 否 |
| 类型（永久/租借/自由/买断） | 是（受限） | 部分 | 否 |
| 转出/转入俱乐部 | 是 | 仅转入 | 是（当前俱乐部） |
| 转会费/附加条款 | 是（解析+原始值） | 无 | 否 |
| 币种 | 是 | 无 | 否 |
| 工资分摊/二转分成 | 是（可选） | 无 | 否 |

## 3. 独立 Transfer Source Adapter 设计

现有 `backend/app/ingestion/transfer_history.py` 已按来源名/批次记录；建议的接口（本轮不强制迁移）：

```python
class TransferSourceAdapter(Protocol):
    name: str
    capabilities: set[str]  # history / agreed / fees / loans
    def read(self, raw: bytes) -> Iterable[TransferRow]: ...
```

- CSV/JSON 适配器：现有导入器，保留；
- FMSuperScout 适配器：若未来上游新增 `transfers` 数组，必须逐字段核对后再启用；
- 存档适配器：需要独立立项（格式、许可、版本）；
- 所有适配器输出必须带 `source_record_id`、原始行与币种，未知状态拒绝。

## 4. 下一步需要的真实输入

1. 一份**带来源与记录号**的历史转会 CSV/JSON（至少 completed 记录）；
2. 若上游新增导出字段，提供样本与版本说明；
3. 若要做存档解析，需要合法样本、格式文档与许可确认。

在获得这些输入前，SM-013 继续保持 **BLOCKED**；不能把 agreed 或俱乐部变化自动升级为 completed。
