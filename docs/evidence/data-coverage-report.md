# 数据覆盖率报告（SM-125）

- 生成时间：2026-11-24T14:22:50
- scan_id：`fmreader-9351b4e56e45c504`
- 输入：{"probe": "probe-report.json", "dump": "dump.json", "scan": "e0a2442f8ead441cb607c7444a2f71fb.json", "database": "live-v323.db"}

## 各层计数

| 层 | 总数 | 合法 UID | 哨兵 | 非法/缺失 | 重复 | 导入 | 拒绝 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native_reader | 96 | 96 | 0 | 0 | 0 | — | — |
| upstream_dump | 43640 | 43640 | 0 | 0 | 0 | — | — |
| scan_payload | 43640 | 43640 | 0 | 0 | — | 0 | — |
| importer | 43640 | 43640 | — | — | — | 0 | 0 |

## 层间差异

- `native_reader → upstream_dump`：差值 -43544，原因 `reader_sample_smaller`（上游只导出已识别的球员对象；probe 的 integrity 探测只覆盖它抽样到的对象，因此 probe 数量小于 dump 属于测量范围差异，不是丢数据）
- `upstream_dump → scan_payload`：差值 0，原因 `match`（mapper 只为没有姓名的行丢弃记录；差值应为 0）
- `scan_payload → importer`：差值 0，原因 `match`

## 说明

- 所有数字来自对应层自己的产物；缺失的层不会被补 0，也不会被排除出分母
- 差值必须由上游导出范围、映射规则或导入拒绝解释；不得为了对齐而删除记录
- 报告只含计数与原因，姓名/地址/PID 不落盘
