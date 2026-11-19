# 真实验证记录 · 2026-11-19 晚（加载存档后）

用户在 19:15 重新打开 FM27 并加载存档（pid `88932`），本次按"确定性 + 全量一致性"重新验证，
结论比白天更严格：**整体 Verified，但身高被降级**。

## 1. 环境

| 项 | 值 |
| --- | --- |
| 游戏 | Football Manager 27，Steam Build `26620374`，27.1.0 |
| 插件 | `game_plugin.dll 27.1`（`27.1.0+2505117`） |
| 进程 | `fm.exe` pid 88932（19:15:03 启动，已加载存档） |
| 布局 | `FM27_1`，闸门字段 `Verified` |
| 注册表 | `26620374 = verified`，`verified_fields` 11 项 + `upstream_agreement_fields` 7 项 |

## 2. 探测报告（`Diag report`）

```
整体 Verified | 扫描允许 true | 闸门 Verified
player / club / team / contract / integrity          Passed
attributes.technical / mental / physical             Passed
position / nation / team_relation                    Passed
loan                                                 NotApplicable（布局无字段）
transfer                                             Inconclusive（dump 无 deal）
women_database                                       Inconclusive（上游跳过）
字段状态：Verified 7 · Candidate 42 · Pending 1 · NotSupported 2
证据种类：GameUiAgreement 7 · UpstreamAgreement 42 · InternalCheck 1 · None 2
```

## 3. 确定性：连续两次扫描完全一致

```
scan 1: fmreader-06a97fc8dc0e7cec  48,089 球员 / 51 俱乐部  82,492,885 字节
scan 2: fmreader-16362b88fea29a98  48,089 球员 / 51 俱乐部  82,492,885 字节
scripts/compare_scans.py → 球员差异 {} 俱乐部差异 {} scan 元数据差异 {}
结论：两次扫描数据完全一致
```

`compare_scans.py` 是本轮新增的确定性工具：忽略 `scanId`/`observedAt`，按
`save_local_uid + name + birth_date` 建索引，逐字段比对。

## 4. 全量一致性（按数字 id 对齐 11-18 的参照导出）

```
48,089 / 48,089 配对（按 dump id = save_local_uid）
CA      : 48,089 / 48,089 一致   （0 差异）
PA      : 48,089 / 48,089 一致   （0 差异）
身高    : 48,058 / 48,089 一致   （31 个差异，0.06%，差 1–6cm）
```

31 个身高差异的例子（读取值 vs 11-18 导出值）：
`Neuton Almeida Ferreira 180/174`、`Vital Dias Semedo 185/190`、`Muhamed Lérias 189/188`、
`Adão Languna 187/188`、`Bruno Martina 179/174`。

处理：**`PLAO_HEIGHT` 从 Verified 降为 Candidate，并从扫描闸门字段移除**。
理由：界面上抽查的 3 人一致，但全量比对有 31 个无法解释的差异；不能因为抽查通过就当成全量正确。
身高不是结构字段（不影响对象定位与关系链），因此不阻塞扫描，但也不再声称"已验证"。

## 5. 与白天"主菜单扫描"的差异（为什么主菜单扫描不可作数）

```
12:30 主菜单扫描 : 48,116 球员 / 51 俱乐部
19:16 加载存档后 : 48,089 球员 / 51 俱乐部
差异：仅第一次存在 27 名球员（id 2002077547… 段）；另有 34 名球员身高不同
```

结论：主菜单状态下的数据库并不可靠（多出 27 名、34 人身高不同）。
**只有加载存档后的扫描才能作为验证依据**——这一点现在写进流程。

## 6. 导入后端

```
POST /imports/scan?save_id=2   （49.3 MB 协议报文）
status            : succeeded
players_updated   : 48,089
players_created   : 0
rows_rejected     : 0
snapshots_created : 48,089
coverage          : players=48089, player_fields=0.922
导入耗时          : 242 s（第二轮导入，复用已有实例）
```

数据库现状：`players 48,206`、`player_instances 48,208`、`player_snapshots 97,981`、
`player_attribute_values 4,302,272`、`clubs 66`、`transfer_candidates 0`。

抽查后端字段（与用户界面核对过的球员一致）：

```
Josh Mullin  1992-09-23  苏格兰  MR, AMR, WBR   180cm  合同 2027-05-31  CA84/PA110
Jamie Murphy 1989-08-28  苏格兰  AML, ML, AMC   176cm  合同 2027-05-31  CA85/PA126
Keisuke Honda 1986-06-13 日本    AMC, AMR, MC   182cm  合同 2027-06-30  CA104/PA150
```

## 7. 本轮发现的另一个真实缺口：俱乐部归属覆盖率

- 扫描报文里只有 **103 / 48,089** 名球员带 `club_uid`（与上游 dump 的 squad-walk 结果一致）；
- 但直接探测 `team_relation` 显示 **24/32** 的样本能沿 `合同 → 球队 → 俱乐部` 解析出俱乐部名；
- 说明"内存里能读到"与"dump 里被导出"之间存在差距：映射层目前只用了 dump 的 `club` 字段，
  没有在 dump 缺俱乐部时回退到对象链。

这是下一步最有价值的技术改进（不是偏移问题，是映射策略问题）；在补齐之前，俱乐部归属仍以
"上游能给出的 103 人 + 阵容 CSV 导入"为准。

## 8. 剩余未验证项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 身高（`PLAO_HEIGHT`） | **Candidate** | 31 个差异待解释；已移出闸门字段 |
| CA / PA | Candidate | 界面不可见，无独立来源；与导出 100% 一致 |
| 技术/精神/身体属性 | Candidate | 只做内部检查与导出对照，未逐项对界面属性页 |
| 球队层级语义（0/3/≥10） | Candidate | 未在界面确认 |
| 女子数据库（21,316 对象） | Inconclusive | 上游按性别跳过；未验证 |
| 转会记录 | Inconclusive | 上游 dump 无 deal，导出 0 条 |
| 母队 / 租借 | NotSupported | 布局无字段，只能来自阵容 CSV |
| 俱乐部归属覆盖率 | 已知缺口 | 103/48,089，映射层未回退到对象链 |
