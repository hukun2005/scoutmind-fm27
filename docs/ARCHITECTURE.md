# 总体架构

## 1. 分层

```
FM27（运行中）
  ↓ 只读外部扫描（不注入、不写进程）
C# Live Reader（Steam 检测 → 版本校验 → probe → scan）
  ↓ 原始 JSON / NDJSON（协议见 DATA_PROTOCOL.md）
Desktop Agent（调度、导出、同步）
  ↓ HTTP POST /api/v1/imports/scan（可选本地令牌）
FastAPI 后端（校验 → 身份匹配 → 快照追加 → 交易去重）
  ↓
SQLite / PostgreSQL（球员、快照、交易、报告）
  ↓
确定性分析（分位数、相似度、估值、角色评分） → AI 工具层 → 结构化回答
  ↓
Vue 3 前端（8 个页面）
```

MVP 采用模块化单体：不引入微服务、消息队列、向量数据库。文件交换优先于命名管道/WebSocket，便于复现问题。

## 2. 后端模块

| 模块 | 职责 |
| --- | --- |
| `app/ingestion` | 协议校验、行级拒绝、身份匹配、快照追加、交易去重、原始报文落盘 |
| `app/analytics` | 分位数、成交统计、相似交易、估值、成长归因、角色评分、费用口径 |
| `app/agents` | 问题解析（rule-based）、工具注册、回答组装（数字只来自工具） |
| `app/api` | REST 路由、鉴权、默认用户/存档解析 |
| `app/services` | Watchlist、提醒规则 |
| `app/models.py` | 25 张核心表（身份、快照、交易、评分、审计） |

## 3. 数据模型要点

- `players` 是跨存档的稳定身份；`player_instances` 是某个存档里的实例，主键组合
  `(fm_save_id, save_local_uid, uid_occurrence)`。
- **UID 复用**：同 UID 但出生日期不同时，`uid_occurrence + 1` 新建实例并写 `identity_matches` 与警告，绝不覆盖旧身份。
- `player_snapshots` 追加式写入，`(player_instance_id, observed_at)` 唯一；重复观测被跳过而不是更新。
- `transfer_history` 以 `(fm_save_id, source_record_id)` 去重；`status` 允许 `pending → completed` 的状态推进，其余字段不覆盖。
- 费用口径统一由 `app/analytics/fees.py` 计算：已支付 = `paid` + `triggered` 组件之和，否则用 `fee_paid`，再否则用 `base_fee`；
  `addons_potential` 永远不计入已支付。

## 4. 一次扫描的失败语义

| 失败点 | 行为 |
| --- | --- |
| 报文不是合法 JSON / 缺 `scan_id` / 版本 major 不兼容 | 整包 400，不落库 |
| 单行缺 UID、负金额、日期非法 | 该行拒绝并写 `import_rows`，其余行继续 |
| 数据库写入异常 | 整包回滚，作业标记 `failed`，不产生半份数据 |
| 扫描器超时 / 非零退出 / 输出非法 | 读取器返回 `ProbeFailed` 或扫描失败，不生成成功快照 |
| 版本未知 | 读取器 `Unknown`/`Unsupported`，拒绝扫描 |

## 5. 幂等与重试

- `scan_id` 是整包幂等键：已成功导入的 `scan_id` 再次提交返回 `duplicate=true`，不写任何行。
- 失败的同一 `scan_id` 允许重试：复用作业行、清理旧 `import_rows` 后重新导入。
- 导入在单个事务内完成；`import_jobs` 先以 `running` 提交，成功后更新为 `succeeded/partial`，失败则 `failed`。

## 6. 分析算法

| 算法 | 版本 | 位置 |
| --- | --- | --- |
| 成交价分位数 | `transfer-stats-1` | `analytics/transfers.py` |
| 相似交易加权距离 | `similar-transfers-1` | `analytics/transfers.py` |
| 可比成交估值 | `valuation-1` | `analytics/valuation.py` |
| 战术角色评分 | `role-score-1` | `analytics/scoring.py` |

相似度字段权重：位置 0.15、年龄 0.25、CA 0.30、PA 0.20、合同剩余 0.10。目标缺失字段时权重置 0 并按候选覆盖率重分配，
响应返回 `effective_weights` 与 `missing_fields`，让“证据基础变薄”可见。

## 7. 前端

Vue 3 + TypeScript + Element Plus + ECharts，所有请求经 `src/api/*` 的类型化客户端，遵循 `docs/API.md`。
`null` 一律渲染为 `—`；`synthetic_fixture` 数据触发演示横幅；统计卡片显示样本量、覆盖率与算法版本。

## 8. 扩展点

- `app/agents/tools.py`：新增工具即新增能力，回答组装按工具结果分节。
- LLM 规划器：`SCOUTMIND_AGENT_LLM_ENABLED` 与 `SCOUTMIND_AGENT_LLM_API_KEY` 已预留，接入时应只让模型选择工具与措辞，
  数字仍由工具返回。
- 存档解析器（`.fm`）：实现同一扫描协议即可复用整条导入链路。
- 多用户：`users` / `fm_save_id` 已贯穿所有表，鉴权与租户隔离属于后续阶段。
