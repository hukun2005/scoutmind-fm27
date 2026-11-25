# V3.2.9 Phase 0：全库身份数据审计（只读）

## 1. 审计范围与方法

- 只读代码与模型：`backend/app/models.py`、`backend/app/services/save_identity.py`、`live-reader` 校准与作用域代码。
- 只读真实环境：FM27 进程/构建/布局、Save Identity 诊断、`players` 诊断命令。
- 不启动全库扫描（任务书要求实现后才有全库批处理；本阶段未实现）。
- 历史数字一律标注为「历史」，不作为当前结果。

## 2. 当前真实环境

| 项目 | 值 |
| --- | --- |
| FM27 进程 | pid 72012 |
| 构建号 | 26620374 |
| 插件版本 | 27.1 |
| 布局 | FM27_1（闸门 Verified，allow_scan=true） |
| Save Identity | `si:v1:file:b887415a…`（VERIFIED，snapshot_eligible=true） |
| 自动快照 | 关闭 |

## 3. 当前可测数据（只读、有限样本）

| 指标 | 本次观测 | 口径 |
| --- | --- | --- |
| 诊断命令定位到的球员记录 | 60 | `players` 命令默认上限样本 |
| 该命令读到的姓名 | 0（`name: null`） | 该命令路径不读取姓名，不代表姓名不可读 |
| 姓名/生日精确匹配 | 0/2 名历史核对球员 | 当前存档与历史核对存档不同，工具拒绝自动选择 |
| Person 候选总数 | UNKNOWN | 未执行全库扫描 |
| 属性记录总数 | UNKNOWN | 未执行全库扫描 |
| UID 可读数量 | UNKNOWN（本次未逐条读取） | V3.2.8 历史样本为 1500/1500，不能当作当前结果 |
| UID 重复数量 | UNKNOWN | 同上 |
| 冲突数量 | UNKNOWN | 未执行全库关联 |
| Verified / Stale / 未验证 | 0 / 0 / UNKNOWN | 进程内无 Canonical 持久化；Stale 为新增状态 |

## 4. 现有模型审计

| 概念 | 现有实现 | 可复用性 |
| --- | --- | --- |
| 球员实体 | `Player` | 可复用 |
| 存档内实例 | `PlayerInstance`（`fm_save_id + save_local_uid + uid_occurrence` 唯一） | 已具备存档内 UID 作用域 |
| 身份匹配审计 | `IdentityMatch` | 可扩展，不新建同义表 |
| 身份冲突 | `IdentityConflict` / `IdentityConflictAction`（追加写） | 可直接承载同名/UID 冲突 |
| 观测 canonical | `PlayerObservationCanonical`（按存档+实例+游戏日） | 可复用，不等于 Canonical Player |
| 未解析球员 | `UnresolvedPlayerCandidate/Observation/Action` | 可作为待审核候选 |
| 转会候选 | `TransferEventCandidate`（俱乐部变化不自动升级为成交） | 可复用 |
| 存档身份 | `SaveIdentity` / `SaveEvidence` / `SaveSession` | Verified 作用域的权威来源 |
| Verified 球员身份 | 仅 C# 决策 + 审计行，无持久化表 | 需在合并后设计（本阶段不实现） |

## 5. 关键结论

1. 现有模型已经区分「存档内 UID」与「球员实体」，不存在“把 UID 当全球 ID”的既有实现。
2. 缺少的是：跨存档 Canonical Identity 的持久化与人工审核队列；本阶段不得在旧模型上并行开发。
3. 全库统计必须在 V3.2.8.1 合并、批处理实现之后重新采集；当前只读审计不能给出全库数字。

## 6. 未解决问题

- 真实全库 Person/属性记录/UID 统计（NOT_RUN）。
- 同名冲突的当前数量（NOT_RUN）。
- 跨存档候选（NOT_RUN，需多存档）。
