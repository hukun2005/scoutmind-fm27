# V3.2.8 Phase 2：Person 候选定位器设计

- 执行日期：2026-11-25
- 范围：只读；不写内存、不改存档、不注入、不改 DLL。
- 代码位置：
  - `live-reader/ScoutMind.FMReader/Calibration/PersonLayoutCandidate.cs`
  - `live-reader/ScoutMind.FMReader/Calibration/PersonCandidateProbe.cs`
  - `live-reader/ScoutMind.FMReader/Calibration/PersonCandidate.cs`
  - `live-reader/ScoutMind.FMReader/Calibration/PersonCandidateLocator.cs`
  - `live-reader/tests/ScoutMind.FMReader.Tests/PersonLayoutCandidateTests.cs`
  - `live-reader/tests/ScoutMind.FMReader.Tests/PersonCandidateLocatorTests.cs`

## 1. 定位流程

`PersonCandidateLocator.Locate(person, candidate)`：

1. `person == 0` → `InvalidPointer`（`null_person`）。
2. 读对象头 vtable；不可读 → `UnreadableMemory`（`unreadable_object_header`）。
3. vtable 为 0 → `InvalidPointer`（`zero_vtable`）。
4. vtable 不在游戏模块内 → `InvalidObject`（`vtable_not_in_module`）。
5. `PersonCandidateProbe` 逐字段观测 `+0x50/+0x58/+0x60/+0x88`。
6. 姓名校验：`common` 优先，否则 `first + second`。
7. 生日校验：`u32` → 年/年内序日；非法则保留原始值。
8. 汇总状态；**永不产生 `Verified`**。

## 2. 结果状态

| 状态 | 含义 |
| --- | --- |
| `InvalidPointer` | Person 指针为 0，或 vtable 为 0 |
| `UnreadableMemory` | 对象头不可读 |
| `InvalidObject` | vtable 不在 `game_plugin` / `GameAssembly` 内 |
| `NameNotFound` | 姓名槽为空或不可读 |
| `InvalidName` | 读到字符串，但含非姓名字符（纯数字/控制字符等） |
| `DateOfBirthNotFound` | 生日字段不可读 |
| `InvalidDateOfBirth` | 生日原始值无法解码为合法日期 |
| `Candidate` | 姓名与生日都通过内部校验 |
| `Verified` | 人工核对通过；**定位器不会返回** |

`Candidate != Verified`。从 `Candidate` 到 `Verified` 必须经过人工核对与安全门控（Phase 5）。

## 3. 姓名校验

- 非空，长度 1..64。
- 允许字母（含 Unicode/重音）、空格、撇号、连字符、句点。
- 至少包含一个字母。
- 不把乱码“清洗”成合法姓名；非法即 `InvalidName`。
- `common` 为空时拼接 `first + second`，多词姓名保持原顺序。

## 4. 出生日期校验

- 原始值按 `FmDate.Decode`：高 16 位年、低 9 位年内序日。
- 年必须在 1900..2100，年内序日必须在 1..366。
- 始终保留 `DateOfBirthRaw`，失败时 `DateOfBirthYear/DayOfYear` 为 0。
- 不猜测时间起点或其它编码。

## 5. 安全边界

- 所有读取经 `IMemorySource`；不使用任意地址写入。
- 每个字段读取失败只记录原因码，不中断其它字段，不使进程退出。
- 无效指针不交给字符串解码器（先校验非零、对齐、目标可读）。
- 不修改 `FM27_0/FM27_1` 的生产偏移常量。

## 6. 测试

| 测试 | 用例数 | 结果 |
| --- | --- | --- |
| `PersonLayoutCandidateTests` | 12 | PASS |
| `PersonCandidateLocatorTests` | 11 | PASS |
| 全量 `ScoutMind.FMReader.Tests` | 238 | PASS / FAIL 0 |

覆盖：有效对象、空指针、不可读指针槽/目标、未对齐指针、乱码/空/Unicode 姓名、合法/非法生日、多候选偏移、重复读取稳定、vtable 越界、永不 Verified。

模拟测试只验证代码逻辑，**不能替代真实 FM27 验收**。

## 7. 真实 FM27 现状

Phase 1 已确认：当前 `26620374 / 27.1` 的属性记录中 `+0x50/+0x58/+0x60` 为 0，姓名不在直接字段区。

因此对真实对象运行定位器时，预期结果为 `NameNotFound`，而不是 `Candidate`。这是当前真实状态的如实反映，
不得为了让状态好看而调整偏移或放宽校验。

## 8. 状态

| 项目 | 状态 |
| --- | --- |
| 定位器代码 | PASS（单元测试 23 例） |
| 真实对象定位（姓名） | FAIL（真实姓名槽为空，Phase 1 证据） |
| 真实对象定位（生日） | PASS（结构级，未逐人核对） |
| Person Verified | NOT_RUN |
