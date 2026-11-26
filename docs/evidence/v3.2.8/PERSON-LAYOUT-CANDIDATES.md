# V3.2.8 Phase 1：Person 候选布局调查

- 执行日期：2026-11-25（Asia/Shanghai）
- 状态口径：PASS / FAIL / PARTIAL / NOT_RUN / UNKNOWN
- 内存操作：全部只读。未写游戏内存、未改存档、未注入、未改 DLL。
- 脱敏：本文不包含本机绝对路径与真实内存地址；原始指针仅保留在工作区外的本机诊断文件。

## 1. 环境（本次实际检测）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 进程 | `fm.exe`（已加载存档，能定位到球员对象） | `Diag status` / `probe` |
| Steam 构建 | `26620374` | `Diag status` |
| game_plugin 版本 | `27.1` | `Diag status` |
| 布局 | `FM27_1` | `Diag status` |
| 闸门 | `allow_scan=true`，`status=Verified` | `Diag status` |
| 访问权限 | `access_denied=false` | `Diag status` |

上表为本次运行重新检测，未使用历史记录作为 PASS 依据。

## 2. 调查方法

| 命令 | 作用 | 本次参数 |
| --- | --- | --- |
| `ScoutMind.FMReader.Diag probe` | 结构化探测 32 个样本的字段合理性 | 默认 |
| `ScoutMind.FMReader.Diag calibrate` | 对 60 个定位对象逐偏移（0..0x400，步长 8）尝试嵌套字符串解码 | `calibrate 60 1024` |
| `ScoutMind.FMReader.Diag dump` | 只读转储单条记录的非零指针与内联 ASCII | `dump 0/1 968` |
| `PersonCandidateProbe`（新增） | 对 `+0x50/+0x58/+0x60/+0x88` 逐字段记录原始值/解码值/有效性/失败原因 | 单元测试（模拟内存） |

候选定义见 `live-reader/ScoutMind.FMReader/Calibration/PersonLayoutCandidate.cs`：
`CandidateId=fm27.1.person.2026-11-25`，姓名候选 `0x50/0x58/0x60`，生日候选 `0x88`，
`VerificationStatus=Unverified`，`Confidence=0`。

## 3. 对象结构观测

- `HeapObjectLocator` 命中的是对象基址（vtable 位置）；`Block = 基址 - 0x288`，与 `PLAYER_OFFSET` 一致。
- 记录步长约 `0x3C8`；两条样本在 `0..0x3C8` 均可读。
- 记录内部**没有内联 ASCII 姓名**（`dump` 只出现 3～4 段零散字节串，不是人名）。
- 记录内重复出现 `0x076C0001`（位于 `+0x118/+0x120/+0x128`），形态像两个 32 位索引，而非指针。

| 相对偏移 | 样本 #0 原始值 | 样本 #1 原始值 | 解释 |
| --- | --- | --- | --- |
| `+0x50` | `0x0` | `0x0` | 姓名槽为空 |
| `+0x58` | `0x0` | `0x0` | 姓名槽为空 |
| `+0x60` | `0x0` | `0x0` | 姓名槽为空 |
| `+0x68` | 非零堆指针 | 非零堆指针 | 疑似国籍/其它引用 |
| `+0x88` | `0x060002FF07D80057` | `0x060000FF07D300A7` | 低 32 位为生日 |
| `+0x118` | `0x076C0001076C0001` | `0x076C0001076C0001` | 两个 32 位索引 |
| `+0x270` | 非零堆指针 | 非零堆指针 | 未识别引用 |
| `+0x288` | 模块内指针 | 模块内指针 | 未识别引用 |

## 4. 逐候选字段结果

读取类型说明：
- `nested_string` = `[person+offset] → ptr → ptr → UTF-8 @ inner+4`。
- `u32_fm_date` = 高 16 位年、低 9 位年内序日。

| 候选偏移 | 读取类型 | 原始值（样本） | 解码结果 | 指针有效 | 字符串有效 | 日期有效 | 失败原因 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `+0x50` | `nested_string` | `0x0`（60/60 样本） | `null` | 否 | 否 | — | `zero_pointer` | **FAIL** |
| `+0x58` | `nested_string` | `0x0`（60/60 样本） | `null` | 否 | 否 | — | `zero_pointer` | **FAIL** |
| `+0x60` | `nested_string` | `0x0`（60/60 样本） | `null` | 否 | 否 | — | `zero_pointer` | **FAIL** |
| `+0x88` | `u32_fm_date` | `0x07D80057` / `0x07D300A7` | `y2008 d87` / `y2003 d167` | — | — | 是 | — | **PASS**（结构级） |

补充：`calibrate` 在 `0x0..0x400` 全部 128 个偏移上，60 个对象均未解出任何“像人名”的字符串
（`name_like=0`）。说明姓名不在该对象的直接字段区。

## 5. 聚合探测结果（32 样本）

| 检查 | 结果 | 阈值 | 状态 |
| --- | --- | --- | --- |
| `ca_range` | 32/32 | 95% | PASS |
| `pa_range` | 32/32 | 95% | PASS |
| `ca_le_pa` | 32/32 | 90% | PASS |
| `height_range` | 32/32 | 95% | PASS |
| `dob_range` | 32/32 | 95% | PASS |
| `positions_bytes` | 32/32 | 95% | PASS |
| `attributes_head` | 32/32 | 95% | PASS |
| `person_in_module` | 32/32 | 95% | PASS |
| `name_string` | **0/32** | 95% | **FAIL** |
| `contract_pointer` | **0/1** | 90% | **FAIL** |

数值字段（CA/PA/身高/生日/位置/属性头）在当前布局下结构合理；姓名与合同指针失败。

## 6. 与上一阶段证据的关系

`docs/evidence/v3.2.7.5/manual-e/calibration-notes.json` 记录：

- F2：`HeapObjectLocator` 返回的是属性记录，不是带姓名的 person；80 个样本在 `0x50/0x58/0x60` 全为 0。
- F3：真实姓名出现在独立的“姓名池”对象中（每 8 字节指向一个 wrapper）。
- F4：记录与姓名池之间没有直接或两级指针链路（全内存反查 0 命中）。
- F5/F6：姓名疑似通过索引/哈希表间接引用；把记录内整数当下标的假设不成立。

本次 Phase 1 的独立复现与 F2/F4/F6 一致：`0x50/0x58/0x60` 为空、偏移扫描无命中、记录内存在
`0x076C0001` 形态的重复索引字段。

## 7. 结论与状态

| 项目 | 状态 |
| --- | --- |
| 对象定位（属性记录） | PASS（32/32 结构合理） |
| 出生日期候选 `+0x88` | PASS（结构级；未与界面逐个核对） |
| 姓名候选 `+0x50/+0x58/+0x60` | FAIL（0/32；槽位为空） |
| 姓名直接字段定位 | FAIL（0..0x400 偏移扫描无命中） |
| 姓名池/索引解析 | NOT_RUN（本阶段不做路线 B） |
| Person 身份 Verified | NOT_RUN（本阶段禁止 Mark(Verified)） |

**不得**把 `+0x88` 的成功扩展为“整份 Person 布局已验证”；也**不得**据此修改 `FM27_0/FM27_1`
的生产偏移常量。

## 8. 下一步

- Phase 2：在现有 `PersonCandidateProbe` 基础上补全候选结果状态（InvalidPointer / UnreadableMemory /
  InvalidObject / NameNotFound / InvalidName / DateOfBirthNotFound / InvalidDateOfBirth / Candidate / Verified）。
- Phase 3：扩展 `calibrate`，输出 JSON + Markdown 校准报告，多次读取稳定性检查。
- Phase 4：`xref` 关联属性记录与 Person；同名/多候选不得自动取第一个。
- 姓名解析属于独立问题（姓名池/索引），在取得可靠证据前保持 NOT_RUN，不能靠“单个人名匹配”认定身份。

## 9. 更正（2026-11-25 真实锚点复核，重要）

用户提供两名真实球员界面截图后，用「生日 u32 + 身高」定位到具体记录，再按 `nested_string` 读取：

| 球员 | 界面生日 | 界面身高 | 内存 `+0x50`/`+0x58`/`+0x60` | 结论 |
| --- | --- | --- | --- | --- |
| 多米尼克·卡尔弗特-卢因 | 1997-03-16 | 187 | `Dominic` / `Calvert-Lewin` / `null` | 匹配 |
| 伊桑·阿姆帕杜 | 2000-09-14 | 182 | `Ethan` / `Ampadu` / `null` | 匹配 |

因此：

- `+0x50/+0x58/+0x60` 的**偏移本身是正确的**（与 27.0 一致）。
- 本文第 4/5 节的 `name_string 0/32` 与 `calibrate name_like=0` 是**采样偏差**：
  `HeapObjectLocator` 按地址顺序返回的前若干个对象恰好是一批姓名槽为空的记录（详见第 10 节）。
- 不应据“0/32”修改姓名偏移。

详细证据见 `REAL-ANCHOR-VERIFICATION.md`。

## 10. 采样偏差说明

- 对地址最靠前的一批对象，`+0x38..+0x60` 全部为 0，没有任何姓名指针。
- 锚点球员所在的记录（地址更靠后）在 `+0x50/+0x58` 能稳定解出姓名。
- 说明 `FindPlayers(max)` 的“前 N 个”语义会系统性偏向某一类记录；真实探测必须跨区域采样或先按姓名/生日过滤。
- 该问题不影响姓名偏移结论，但会影响 `probe` 的通过率统计，列入 Phase 3/9 修复项。
