# 校准结果（CALIBRATION-RESULTS）

- 运行日期：2026-11-25
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`5720c88`（报告整理时）
- 关联详细记录：`PERSON-CALIBRATION-REPORT.md`、`PERSON-DIAGNOSTICS.md`

## 1. 运行结果

| 运行 | 定位总数 | 抽样 | 姓名有效 | 生日有效 | 结构通过 | 不稳定 | 置信度 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `calibrate`（Phase 3） | 240 | 24 | 8 | 24 | 8 | 0 | 0.17 | Unverified |
| `dump --calibration`（Phase 6） | 800 | 24 | 19 | 24 | 19 | 0 | 0.40 | Unverified |

- 两次运行使用跨区域等距抽样（`even_stride`），每对象重复读取 3 次。
- 姓名失败原因计数：`zero_pointer=54`（字段级统计；姓名槽为空，不是解码错误）。
- 结构通过数等于“姓名有效且生日有效”的样本数。
- 两次运行的存档状态不同，因此通过率不同（8/24 与 19/24）；不能互相替代。

## 2. 字段结论

| 项目 | 结果 | 状态 |
| --- | --- | --- |
| 姓名偏移 `+0x50/+0x58/+0x60` | 真实锚点 2/2 命中 | PASS |
| 生日偏移 `+0x88`（year<<16 \| day_of_year） | 抽样生日全部可解码 | PASS |
| 身高 `+0x22E`、Block=Person-0x288、步长 0x3C8 | 与真实锚点一致 | PASS |
| 快照内稳定性（3 次读取） | 不稳定 0 | PASS |
| 全库结构覆盖率 | 8/24、19/24，未达全库 | PARTIAL |
| Mark(Verified) | 校准不执行，状态保持 Unverified | NOT_RUN |

## 3. 失败原因

- 姓名槽为零：姓名读取失败的主要原因，相关记录仍可通过 UID 关联。
- 抽样覆盖率低、部分记录姓名缺失，导致整体置信度只能到 0.17 / 0.40。
- 校准结果不作为 Verified 依据；人工核对结果见 `VERIFIED-GATE-REPORT.md`。

## 4. 未完成项

- 未做全库（所有 Person）校准，仅抽样。
- 未做跨存档校准对照。
- 未观察球员生命周期变化后的字段稳定性。

## 5. 复现

```text
ScoutMind.FMReader.Diag.exe calibrate 165 --located 240 --reads 3 --samples 24
ScoutMind.FMReader.Diag.exe dump --calibration --located 800 --samples 24 --reads 3
```
