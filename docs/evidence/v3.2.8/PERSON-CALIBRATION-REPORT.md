# FM27 Person 校准报告（真实内存，只读）

> 生成时间：2026-11-25 22:56:58 +08:00 · 候选：`fm27.1.person.2026-11-25` · Schema `1.0`

## 1. 本次运行环境（现场检测，未使用历史记录）

| 项目 | 值 |
| --- | --- |
| 游戏版本 | 27.1 |
| 构建号 | 26620374 |
| 进程 | fm (pid 72012) |
| game_plugin.dll | 27.1 |
| 版本闸门 | Verified · allow_scan=True · access_denied=False |

## 2. 候选布局

| 项目 | 值 |
| --- | --- |
| 姓名偏移 | 0x50 / 0x58 / 0x60 |
| 生日偏移 | 0x88 |
| 抽样 | 24/240（even_stride，每对象读取 3 次） |

## 3. 逐样本证据

| # | 名 | 姓 | 常用名 | 生日 | 状态 | 稳定 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | — | — | — | y2002 d176 | Unverified | 是 |
| 1 | — | — | — | y2008 d341 | Unverified | 是 |
| 2 | — | — | — | y2005 d178 | Unverified | 是 |
| 3 | — | — | — | y2008 d25 | Unverified | 是 |
| 4 | — | — | — | y2007 d351 | Unverified | 是 |
| 5 | — | — | — | y2006 d362 | Unverified | 是 |
| 6 | — | — | — | y2007 d285 | Unverified | 是 |
| 7 | — | — | — | y2007 d56 | Unverified | 是 |
| 8 | — | — | — | y2009 d237 | Unverified | 是 |
| 9 | — | — | — | y2009 d25 | Unverified | 是 |
| 10 | — | — | — | y2008 d120 | Unverified | 是 |
| 11 | — | — | — | y2007 d196 | Unverified | 是 |
| 12 | — | — | — | y2008 d13 | Unverified | 是 |
| 13 | — | — | — | y2008 d230 | Unverified | 是 |
| 14 | — | — | — | y2009 d1 | Unverified | 是 |
| 15 | — | — | — | y2005 d161 | Unverified | 是 |
| 16 | Ahmed | Rashid | — | y1997 d19 | StructurallyValid | 是 |
| 17 | Sultan | Al-Mentheri | — | y1995 d5 | StructurallyValid | 是 |
| 18 | Maher | Sabra | — | y1992 d14 | StructurallyValid | 是 |
| 19 | Hussain | Abbas | — | y1994 d334 | StructurallyValid | 是 |
| 20 | Abdalla Ghanim | Jumaa | Abdalla Ghanim | y1995 d141 | StructurallyValid | 是 |
| 21 | Odai Khadr | Al-Qarra | Odai Al-Qarra | y1991 d79 | StructurallyValid | 是 |
| 22 | Salem | Al-Ajalin | — | y1988 d49 | StructurallyValid | 是 |
| 23 | Hasan | Kourani | — | y1995 d22 | StructurallyValid | 是 |

## 4. 汇总与失败原因

| 指标 | 值 |
| --- | --- |
| 姓名有效 | 8/24 |
| 生日有效 | 24/24 |
| 结构校验通过 | 8/24 |
| 多次读取不稳定 | 0 |
| 置信度（结构上限 0.5） | 0.17 |
| 验证状态 | Unverified |

失败原因码：

| 原因 | 次数 |
| --- | --- |
| zero_pointer | 54 |

## 5. 候选偏移扫描（参考）

| 偏移 | 可读 | 像人名 | 去重 | 示例 |
| --- | --- | --- | --- | --- |
| 0x50 | 8 | 8 | 8 | Ahmed；Sultan；Maher；Hussain；Abdalla Ghanim |
| 0x58 | 8 | 8 | 8 | Rashid；Al-Mentheri；Sabra；Abbas；Jumaa |
| 0x60 | 2 | 2 | 2 | Abdalla Ghanim；Odai Al-Qarra |
| 0x0 | 24 | 0 | 0 | — |
| 0x28 | 24 | 0 | 0 | — |
| 0x68 | 24 | 0 | 0 | — |
| 0x78 | 10 | 0 | 0 | — |
| 0x80 | 8 | 0 | 0 | — |

## 6. 结论与限制

抽样 24/240：姓名有效 8，生日有效 24，结构校验通过 8，不稳定 0。结构校验通过不等于人工核对；本报告不构成 Mark(Verified) 依据。

- 本报告只做只读观测，未写入游戏内存、未修改保护属性、未注入 DLL。
- 结构校验通过、多次读取稳定都**不等于**人工核对；未经真实 FM27 人工核对不得 Mark(Verified)。
- 上传时使用脱敏版本：不包含 Person 指针、姓名指针或完整内存地址列表。

复现（在已加载存档的 FM27 上，只读）：

```text
ScoutMind.FMReader.Diag.exe calibrate --output <sanitized.json> --markdown <report.md>
```
