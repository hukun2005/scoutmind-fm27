# 俱乐部解析与阵容归属

这份文档回答三个问题：**俱乐部的身份从哪来**、**本队是怎么确定的**、**阵容分层与租借状态怎么可能有数据**。
所有结论都以真实导出为准，字段依据见 [FMSCOUT_FIELD_COVERAGE.md](FMSCOUT_FIELD_COVERAGE.md)。

## 1. 数据源的真实情况

一份真实 FMSuperScout 导出（FM 27.1，48,089 名球员）里：

| 事实 | 影响 |
| --- | --- |
| 顶层只有 `meta` / `players` / `staff`，**没有 `clubs` 数组** | 俱乐部只能从球员行里派生 |
| 球员的 `club` 是**名称字符串**，没有 `clubId` / `currentClub` | 俱乐部 ID 必须自己造，且要稳定 |
| 只有 0.2%（103 人）的球员带俱乐部 | 其余 47,986 人无法归属，**不能**默认塞给本队 |
| 没有 `parentClub` / `loanClub` / `ownerTeamType` | 租借与所有权只能来自阵容 CSV |
| `teamType` 只出现在有俱乐部的行，取值是整数 `0` | 语义未验证，**不**当作一线队/预备队/青年队 |
| `meta.myClub` 为 `null` | 本队必须由用户指定（或用报文声明） |

## 2. 解析优先级

`backend/app/clubs/resolver.py` 的 `ClubResolver` 按顺序解析每一条俱乐部：

| 优先级 | 来源（`source`） | 可信度 | 说明 |
| --- | --- | --- | --- |
| 1 | `payload_clubs` | 1.0 | 报文里带 uid 的俱乐部对象，最可信 |
| 2 | `player_club_field` | 0.6 | 球员行里的俱乐部名称；生成确定性 uid `name:<slug>` |
| 3 | `squad_csv` | 0.9 | 用户导入的阵容名单里的俱乐部 |
| 4 | `manual` | 1.0 | 用户手动指定的本队 |

规则：

- **稳定 ID 优先**：先按 uid 找，再按归一化名称找。名称归一化去掉大小写、重音、标点和多余空格；
- 只有名称时生成 `name:<slug>`，重复导入**不会**新建第二条；
- 之后报文带来真实 uid 时，**升级**这条记录而不是新插一条，并把外部 ID 记进 `external_ids_json`；
- 已观测到的联赛/声誉不会被更弱的渠道覆盖（只在空值时补）；
- 每条俱乐部都带 `source` 与 `confidence`，界面必须展示，不允许显示成"来源未知"。

## 3. 本队（主执教俱乐部）

- 唯一事实来源是 `fm_saves.user_club_id`，`clubs.is_user_club` 只是派生标记（兼容旧查询）；
- `fm_saves.user_club_source` 记录它是怎么来的：`manual`（用户选的）/ `payload`（报文声明）；
- 手动指定**只改指针，不移动任何球员**：`player_instances.club_id` 不变；
- 自动采用报文声明的前提是"当前还没有指定"，不会覆盖用户选择；
- 没有指定本队时，阵容分析返回"该存档没有标记为「我的俱乐部」的球队"，而不是给一个空阵容。

接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/clubs/search?query=&limit=` | 搜索俱乐部，返回来源、可信度、人数 |
| `GET` | `/saves/{id}/user-club` | 当前本队、记录来源、指定方式 |
| `PUT` | `/saves/{id}/user-club` | 指定本队（body `{club_id}`） |
| `DELETE` | `/saves/{id}/user-club` | 清除本队 |

## 4. 阵容 CSV

FMSuperScout 不提供梯队与租借，所以这两项只能由用户导入。入口：数据中心「阵容名单 CSV」，
或 `POST /imports/squad-csv?save_id=`（multipart 字段 `file`，也接受裸 CSV 文本）。

模板：`GET /imports/squad-csv/template`。

| 列 | 可用列名 | 必填 |
| --- | --- | --- |
| 姓名 | 姓名 / Name / Player / 球员 | 是 |
| 球员 ID | 球员ID / ID / PlayerID / UID | 否（有则优先） |
| 俱乐部 | 俱乐部 / Club / Team | 建议 |
| 阵容 | 阵容 / Squad / TeamType / 梯队 | 否 |
| 租借 | 租借 / Loan / Status | 否 |
| 出生日期 | 出生日期 / DOB / BirthDate | 否（提高置信度） |
| 国籍 | 国籍 / Nation / Nationality | 否（提高置信度） |

阵容取值：`一线队/first team` → `senior`，`预备队/reserves` → `reserve`，`青年队/u18/u21/academy` → `youth`，
其余 → `unknown`（显示"未知"，**不**默认成一线队）。

租借取值：`租入/loaned in` → `loaned_in`，`外租/loaned out` → `loaned_out`，`无/-` → `none`，其余 → `unknown`。

### 匹配与置信度

| 情况 | 分数 | 处理 |
| --- | --- | --- |
| CSV 给了球员 ID 且能对上 `save_local_uid` / `game_unique_id` | 1.0 | 直接关联 |
| 姓名完全一致 | 0.5 | 作为基础分 |
| 出生日期一致 | +0.3 | |
| 国籍一致 | +0.1 | |
| 俱乐部一致 | +0.1 | 与当前快照的俱乐部比对 |
| 同名同分（无法区分） | 压到 0.49 | 只报告，要求人工确认 |
| ≥ 0.80 | — | 自动写入 `squad_assignments` |
| 0.50–0.79 | — | 返回 `review`，**不写入** |
| < 0.50 或没有同名球员 | — | 返回 `unmatched`，**不写入** |

重复导入同一份 CSV 是幂等的：按 `(存档, 球员, 来源)` 更新同一行。

## 5. 阵容分析

`GET /squad/overview` 增加 `composition`：

| 键 | 含义 |
| --- | --- |
| `available` | 是否有阵容名单。为 `false` 时 `missing` 说明原因，不猜 |
| `counts` / `buckets` | `senior` / `reserve` / `youth` / `loaned_out` / `loaned_in` / `unknown` |
| `gaps` | 哪些球员不在名单里、哪些梯队无法确认 |

关键约束：

- **没有名单依据的球员显示为未知**，不会被算成自由球员，也不会被默认归入一线队；
- 外租与租入分开统计，并各自带俱乐部、来源与置信度；
- 租借与所有权仍以 `loan_records`（来自报文）与 CSV 的 `loan_status` 为准，两者都没有时是未知，不是"无租借"。

## 6. 验收结果（2026-11-18，真实数据）

用真实的 1,500 人存档验证：

| 项 | 结果 |
| --- | --- |
| 本队识别 | 导出没有 `meta.myClub`，界面显示"尚未指定"，要求手动选择 |
| 手动指定 | 选 `International Football Club`（17 人，来源 `player_club_field`，可信度 0.6），标记"你手动指定" |
| 阵容评分 | 68.6 分，六个维度全部可计算（17 人） |
| 阵容 CSV | 按球员 ID 关联 17 人，置信度 1.0，0 行待确认 |
| 阵容构成 | 一线队 10 · 预备队 4 · 青年队 1 · 外租 1 · 租入 1 · 未知 0 |
| 自动化测试 | `tests/test_club_resolution.py` 15 个用例（覆盖任务要求的 9 个场景） |

## 7. 已知边界

- 俱乐部之间的层级（母队/卫星队）无法从导出得到，也不推断；
- `teamType` 的整数语义未验证，因此**不使用**它作为梯队依据；
- 名称归一化不会主动合并"FC Naples"与"Napoli"这类别名：合并错比不合并更危险，需要时用 CSV 指定；
- 若本机数据库是早期版本且 `clubs` 表缺少主键（中断的批量迁移会留下这种表），执行
  `scripts/repair_club_table.py --apply` 重建（保留数据、去重、恢复约束）。
