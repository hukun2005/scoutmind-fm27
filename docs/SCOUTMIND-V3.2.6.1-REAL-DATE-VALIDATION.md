# ScoutMind V3.2.6.1 真实 FM27 日期验证

- 验证日期：2026-11-24（真实 FM27 进程，人机界面日期 `2026-11-06`）
- 环境：Windows + FM27（build 26620374，plugin 27.1），游戏进程真实运行
- 结论：**真实读取已执行，但结论为 BLOCKED** —— 结构签名无法唯一确定“当前世界日期”对象，
  Reader 判定 `ambiguous`，自动快照保持 `BLOCKED`。本文件只记录真实输出，没有任何推测值。

## 1. 验证前检查（真实结果）

| 检查项 | 要求 | 本次结果 |
| --- | --- | --- |
| 游戏进程 | `fm.exe` 正在运行且已载入存档 | PASS（PID 106216 / 重启后 PID 118504） |
| 游戏构建号 | 与兼容清单一致（26620374） | PASS（`build=26620374`） |
| 插件版本 | 与 VersionGate 要求一致 | PASS（`plugin=27.1`） |
| Reader 构建 | `ScoutMind.LiveReader` 可执行 | PASS（本机 Debug 构建） |
| 存档 | 已知存档身份（用于后续能力验证） | **未知**（存档身份尚未实现，安全门保持 BLOCKED） |

## 2. 端到端真实验证

### 2.1 会话 1：基础诊断（2 GB 预算）

```powershell
ScoutMind.LiveReader.exe world-date --diagnostics --json
```

真实输出（`docs/evidence/v3.2.6.1/world-date-diagnostics-01.json`）：

| 字段 | 实际值 |
| --- | --- |
| `status` / `confidence` | `heuristic` / `heuristic` |
| `date_summary.selected_date` | `2026-11-06` |
| 选中候选参考日期 | `2027-02-01`（间隔 87 天） |
| 保留 / 排除候选 | 1 / 1（`2060-11-02` → `OUT_OF_SUPPORTED_RANGE`） |
| `diagnostics.truncated` | `true`（2 GB 预算在 2.87 GB 堆区上被截断） |
| `snapshot.status` | `BLOCKED` |

结论：在截断预算下只能看到极少数命中，`heuristic` 不构成任何可信结论。

### 2.2 会话 1：人工界面日期验证

```powershell
ScoutMind.LiveReader.exe world-date --diagnostics --json --verify 2026-11-06
```

真实输出（`docs/evidence/v3.2.6.1/restart-session-1.json`）：

| 字段 | 实际值 |
| --- | --- |
| `status` / `confidence` | `session_verified` / `session_verified` |
| `candidates[0].classification` | `CURRENT_WORLD_DATE` |
| `candidates[0].read_count` | 9 |
| `candidates[0].logical_signature` | `heap:b16a56d8d23b4675`（**v1 指纹，后被证明不可靠**） |
| `snapshot.status` | `BLOCKED`（未达 `restart_verified` + 存档身份未知） |

> 后续分析证明：v1 指纹把堆指针字节也计入哈希，跨进程必然变化；
> 这次“唯一匹配”建立在地址噪声上，属于**假阳性**。详见
> `docs/SCOUTMIND-V3.2.6.1-RESTART-VALIDATION.md`。

### 2.3 会话 2：完整预算重扫（8 GB 预算，未截断）

完全退出游戏并重启、载入同一存档后（PID 118504）：

```powershell
ScoutMind.LiveReader.exe world-date --diagnostics --json --max-mb 8192 --verify 2026-11-06 `
  --state "$env:TEMP\scoutmind-date-state.json"
```

真实输出（`docs/evidence/v3.2.6.1/world-date-diagnostics-02.json`）：

| 字段 | 实际值 |
| --- | --- |
| 实际扫描字节 | 2.87 GB（未截断） |
| 签名命中 | 142 |
| `status` / `confidence` | `ambiguous` / `discovered` |
| `date_summary.selected_date` | 空（不选择） |
| 保留 / 排除 | 0 / 142（`DUPLICATE_SIGNATURE` 138、`INSUFFICIENT_EVIDENCE` 3、`OUT_OF_SUPPORTED_RANGE` 1） |
| `snapshot.status` / `allowed` | `BLOCKED` / `false` |

`2026-11-06` 候选（`0x1F76D10E8B8`）的逻辑签名为 `heap:v2:70792ff53e1ed6e6`，
该签名同时命中另外 9 条记录：

| 地址 | 日期 | 参考日期 |
| --- | --- | --- |
| `0x1F76D10AB98` | 2026-11-03 | 2027-03-04 |
| `0x1F76D10C638` | 2026-11-02 | 2027-03-04 |
| `0x1F76D10C878` | 2026-11-05 | 2027-02-28 |
| `0x1F76D10CFF8` | 2026-11-02 | 2027-02-28 |
| `0x1F76D10E8B8` | **2026-11-06** | 2027-02-25 |
| `0x1F76D10EB58` | 2026-11-04 | 2027-02-26 |
| `0x1F76D12A518` | 2026-11-04 | 2027-01-03 |
| `0x1F76D146058` | 2026-10-31 | 2026-12-30 |
| `0x1F76D14A378` | 2026-11-03 | 2027-01-02 |
| `0x1F76D14B338` | 2026-11-02 | 2027-01-01 |

这 10 条记录的结构、ID 字段与指针布局完全相同，只有**日期值与参考日期**不同，
而这两者按设计不参与结构指纹。也就是说：这是一组同构的“日期记录”，
结构签名不能证明哪一条是当前世界日期；按“禁止仅按日期值猜语义”的要求，
只能全部排除并判定 `ambiguous`。

## 3. 证据记录（真实值）

```text
日期：2026-11-24
游戏进程 PID：106216（会话 1）/ 118504（会话 2）
进程启动时间：2026-11-24T13:52:44Z（会话 1）/ 2026-11-24T13:57:21Z（会话 2）
构建号：26620374
插件版本：27.1
模块基址：0x7FFD3CA10000（会话 1）
存档：未知
界面日期：2026-11-06
Reader 选中日期：会话 1 = 2026-11-06（v1 假阳性）；会话 2 = 无（ambiguous）
候选总数：会话 1 = 2（截断）；会话 2 = 142
保留候选：会话 1 = 1；会话 2 = 0
排除候选（原因）：见 2.3 表格
可信度：discovered（会话 2）
自动快照：BLOCKED
证据文件：docs/evidence/v3.2.6.1/world-date-diagnostics-01.json、world-date-diagnostics-02.json、
          restart-session-1.json、date-verification-session-1.json、date-verification-v2-session-2.json
```

## 4. 已完成的自动化验证

| 验证项 | 方式 | 结果 |
| --- | --- | --- |
| 候选全部进入诊断 | 模拟内存 + 单元测试 | PASS |
| 日期与参考日期间隔过滤 | 模拟内存 + 单元测试 | PASS |
| 同签名重复 → 歧义 | 模拟内存 + 单元测试 | PASS |
| 对象提示 → 比赛日期排除 | 模拟内存 + 单元测试 | PASS |
| 未来日期 → `FUTURE_EVENT` | 模拟内存 + 单元测试 | PASS |
| 界面日期不一致 → 不写入确认日期 | 追踪器单元测试 | PASS |
| 日期回退 → 降级 | 追踪器单元测试 | PASS |
| 结构指纹与日期/堆指针无关 | 单元测试 | PASS |
| 自动快照安全门默认 BLOCKED | 单元测试 | PASS |

测试命令与结果：

```powershell
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests   # 184 PASS / 0 FAIL
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests     # 55 PASS / 0 FAIL
dotnet test desktop-agent/tests/ScoutMind.Agent.Tests             # 16 PASS / 0 FAIL
```

引用链版本新增自动化验证（`ReferenceChainTests`，全部 PASS）：

| 验证项 | 结果 |
| --- | --- |
| 模块静态槽位一跳解析到日期字段 | PASS |
| 两跳（模块 → 对象 → 对象）解析 | PASS |
| 槽位越界 / 空槽位 / 哨兵不成立 → 不解析 | PASS |
| 同构重复记录中只有带引用链的一条被保留并 `session_verified` | PASS |
| 同一 RVA/偏移链在三次独立进程会话后 `restart_verified` | PASS |

## 5. 未通过/未执行项

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 真实 FM27 基础诊断 | **PASS（已执行）** | 见 2.1 / 2.3 |
| 真实界面日期匹配（结构指纹版） | **BLOCKED** | 同构日期记录 10 条共享签名，无法唯一确定对象 |
| 引用链版真实诊断 | **NOT_RUN / BLOCKED** | 2026-11-24 执行时 FM27 未运行（`game_not_running`） |
| 真实界面日期匹配（引用链版） | **NOT_RUN / BLOCKED** | 依赖游戏运行；尚无真实引用链证据 |
| 日期推进后复验 | NOT_RUN | 身份未建立，推进日期不产生新的有效证据 |
| 日期回退复验 | NOT_RUN | 同上 |
| 真实候选总数 vs 旧实现 | **PASS** | 旧实现 2 GB 截断只见 2 条；完整预算 142 条，证明“最新日期”选择不可靠 |
| 自动快照开放前验证 | BLOCKED | 存档身份未实现 + 候选歧义 |

引用链版阻塞运行的原始输出（`docs/evidence/v3.2.6.1/world-date-reference-chain-blocked.json`）：

```text
status = game_not_running
process_detected = false
confidence = unavailable
date_summary.candidate_count = 0
snapshot.status = BLOCKED
diagnostics[0] = 没有找到正在运行且带 fm_Data 的 fm.exe。
```

在候选无法唯一确定、且引用链版本未取得真实结果之前，任何“当前日期已校准”的表述都不成立，
自动快照必须保持关闭。
