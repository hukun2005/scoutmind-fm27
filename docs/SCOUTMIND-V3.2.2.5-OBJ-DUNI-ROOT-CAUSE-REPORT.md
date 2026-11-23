# ScoutMind FM27 V3.2.2.5 — OBJ_DUNI 根因报告

- 分支：`codex/v3.2.2.3-date-discovery`
- 真实 FM27：pid 105040，build 26620374，plugin 27.1
- 日期：2026-11-23

## 1. 已修复

`ProbeIntegrity` 现在把 DB 块可读与 UID 实际字段可读分开：

- 计算 `uidAddress = player.Db + OBJ_DUNI`；
- 检查地址加法溢出；
- 检查 `uidAddress` 的 4 字节可读性；
- 只在实际 UID 地址读取；
- DB 可读不再等同于 UID 可读；
- 读取失败不再转成 0 或 0xFFFFFFFF；
- `ObjectIdSample` 增加 `UidAddress`。

真实 probe 仍返回：

```text
UID 合法比例（0=0，哨兵=14）：57/71（80%，阈值 95%）
```

## 2. 14 个哨兵对象

当前证据只能确认：

- 去重对象 71；
- 14 个对象的 `OBJ_DUNI` 为 `0xFFFFFFFF`；
- 57 个合法 UID 全部唯一；
- 重复合法 UID 为 0；
- 0 UID 为 0；
- 不可读 UID 为 0。

本轮没有导出 14 个哨兵对象的姓名/类型证据，因为 CLI 的 `probe --json` 只输出汇总，`ObjectIdDiagnostics.Samples` 尚未通过独立诊断命令落盘。因此：

- 无法完成对象类型分类；
- 无法证明哨兵对象是非球员/临时对象；
- 不能静默排除它们；
- 不能降低 95% 阈值。

## 3. 状态

| 任务 | 状态 |
| --- | --- |
| SM-092 UID 实际地址 | PASS |
| SM-093 14 个哨兵取证 | PARTIAL（计数/地址已分离，姓名/类型未落盘） |
| SM-094 对象分类 | BLOCKED |
| SM-095 偏移验证 | PARTIAL（未证明偏移错误） |
| SM-096 类型适用性 | BLOCKED |
| SM-097 安全门禁 | 未修改，保持 95% 拒绝 |

## 4. 测试

- Reader 单元测试：**116 passed**
- 真实 probe：**FAIL**（合法 UID 覆盖率 80%）
- 完整扫描：仍被阻止

## 5. 下一步

需要新增独立诊断输出（不经过 `probe` 汇总），把 14 个哨兵对象的：

- ObjectAddress / DbAddress / UidAddress；
- 姓名、CA/PA、位置、合同/球队关系；
- 原始 UID 字节；

写成报告，再分类。不得在完成前改门禁。

## 6. 结论

**PARTIAL / BLOCKED**：实际 UID 地址检查已修复，但哨兵对象语义未证明，probe 仍失败，不能进入正式扫描或自动采集。未合并 main、未发布。
