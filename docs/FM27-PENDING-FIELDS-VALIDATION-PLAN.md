# FM27 Pending 字段验证计划（SM-044）

- 生成时间：2026-11-21
- 数据来源：`Diag evidence`（`exports/field-evidence.json`）
- 字段总数：**50**（Verified 0 / Candidate 18 / Pending 32 / Rejected 0）
- 本计划覆盖 **32 个 Pending 字段**；另外 18 个 Candidate 仍缺独立界面证据。

## 规则

1. 每个字段必须同时有 **原始内存值** 与 **游戏界面期望值** 才算有效样本；
2. 至少 1 个一致样本只能升到 Candidate；要升 Verified 必须有注册表证据 + 一致样本；
3. 缺失值、0、默认值不能单独作为证据（0 只有在界面也显示 0 时才算配对样本）；
4. 任何一个不一致样本都会把字段标为 Rejected，必须先解释再继续；
5. 本轮不改偏移、不为了让年份/数值“看起来合理”而调整转换。

## Pending 字段清单

| field_id | 对象类型 | 偏移 | 数据类型 | 界面核对内容 | 预期门槛 |
| --- | --- | --- | --- | --- | --- |
| `DEAL_TO_TEAM` | player | `0x8` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `OBJ_DUNI` | player | `0xC` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `CLUB_TEAMS_BEGIN` | club | `0x18` | 未知 | 在俱乐部页面核对名称、联赛、声誉；与俱乐部解析结果比对。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `DEAL_FROM_TEAM` | player | `0x18` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PERO_GENDER` | person | `0x19` | 未知 | 在球员个人信息页核对姓名、出生日期、国籍；与扫描值逐项记录。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `CLUB_TEAMS_END` | club | `0x20` | 未知 | 在俱乐部页面核对名称、联赛、声誉；与俱乐部解析结果比对。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `NATION_SHORT_NAME` | player | `0x20` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `CON_JOB` | contract | `0x26` | 未知 | 在合同页核对到期日、周薪、球衣号、所属球队；必须记录原始字节与转换结果。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `DEAL_SENT1` | player | `0x2C` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `NATION_NAME` | player | `0x30` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `DEAL_SENT2` | player | `0x34` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_PLAYERS_BEGIN` | team | `0x38` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_PLAYERS_END` | team | `0x40` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `DEAL_DATE` | player | `0x44` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_COMP` | team | `0x50` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `DEAL_STATUS` | player | `0x55` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_MANAGER` | team | `0x80` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_SCHEDULE` | team | `0xA0` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PERO_FULL_CONTRACT` | person | `0xA8` | 未知 | 在球员个人信息页核对姓名、出生日期、国籍；与扫描值逐项记录。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `TEAM_REP` | team | `0xA8` | 未知 | 在球队/阵容页核对球员所属球队与梯队；注意预备队/青年队语义。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `CLUB_SHORT_NAME` | club | `0xC8` | 未知 | 在俱乐部页面核对名称、联赛、声誉；与俱乐部解析结果比对。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `STAFF_OFFSET` | player | `0x100` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_GUIDE_VALUE` | player | `0x234` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_TRANSFER_VALUE` | player | `0x238` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_CONDITION` | player | `0x258` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_HOME_REP` | player | `0x25E` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_CUR_REP` | player | `0x260` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_WORLD_REP` | player | `0x262` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAO_MORALE` | player | `0x26C` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAYER_OFFSET` | player | `0x288` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `PLAYER_STAFF_OFFSET` | player | `0x380` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |
| `HUMAN_MANAGER_OFFSET` | player | `0x440` | 未知 | 在游戏内球员档案/属性页读取 CA/PA、身高、位置、属性；同一球员连续两次扫描值稳定。 | 1 个一致样本 → Candidate；注册表 + 样本 → Verified |

## 通用验证步骤

1. 打开 FM27，加载真实存档，运行 `ScoutMind.FMReader.Diag evidence <out.json>`；
2. 对每个字段选择 1–3 名球员，在游戏界面读取期望值；
3. 把 `(field_id, raw_value, expected_game_value, observed_at)` 写入证据样本；
4. 重新运行 evidence，确认状态变化符合规则；
5. 把样本与截图归档到 `docs/verification/`，并在 `compatibility-registry.json` 中补证据；
6. 任何一个 Rejected 都要先排查偏移/对象类型，不得直接改期望值迁就读取值。

## 风险

- CA/PA 在游戏界面不可见：这两个字段最多 Candidate，不得声称 Verified；
- 合同对象可能有多套结构：`CON_EXPIRY` 的异常年份见 `docs/CON-EXPIRY-ROOT-CAUSE-REPORT.md`；
- 属性块是整块读取：单个属性不一致可能是对象错位，而不是转换错误；
- 预备队/青年队语义需要结合 `teamType` 与实际界面，不能按整数猜测。

## 本轮结论

32 个 Pending 字段**没有任何真实界面证据**，因此全部保持 Pending；本计划不产生新的 Verified。
