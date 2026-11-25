# Phase 9：测试体系与覆盖矩阵

> 日期：2026-11-25 · 构建 26620374 · 插件 27.1
> 测试命令与结果均为本机真实执行；模拟测试与真实 FM27 测试分开统计。
> 状态取值：PASS / FAIL / PARTIAL / NOT_RUN / UNKNOWN。

## 1. 测试规模

| 测试套件 | 结果 | 说明 |
| --- | --- | --- |
| ScoutMind.FMReader.Tests | **284 / 284 PASS** | 单元 + 模拟集成；本轮新增 3 项 |
| ScoutMind.Reader.Tests | **57 / 57 PASS** | 上游读取器既有测试 |

```text
dotnet run --project live-reader/tests/ScoutMind.FMReader.Tests/ScoutMind.FMReader.Tests.csproj -c Release
dotnet run --project live-reader/tests/ScoutMind.Reader.Tests/ScoutMind.Reader.Tests.csproj -c Release
```

## 2. 单元测试（§11.1）

| 覆盖项 | 代表测试 | 状态 |
| --- | --- | --- |
| 指针验证 | 候选字段：空指针/未对齐/指针目标不可读；指针扫描：越界值不算命中 | PASS |
| 姓名读取 | 候选字段：有效指针 + Unicode 姓名；定位器：姓名槽为空/乱码 | PASS |
| Unicode 解码 | 定位器：Unicode 多词姓名；关联：姓名忽略重音与大小写 | PASS |
| 日期读取 | 日期编码可逆；出生日期由 birthYear + birthDoy 还原 | PASS |
| 日期范围验证 | 日期编码拒绝非法原始值；合同日期年份/序日越界区分 | PASS |
| Person 对象构建 | 定位器：合法对象返回 Candidate；Person 为 0 整体 Rejected | PASS |
| 属性记录关联 | 关联：唯一匹配 / 多候选 / 同名冲突 / UID 冲突 / 俱乐部冲突 | PASS |
| 同名冲突 | 同名不同生日为 ConflictingIdentity；多候选不取第一个 | PASS |
| 缺失 UID | 缺失俱乐部与 UID 不默认为 0；UID 冲突保留证据 | PASS |
| 无效对象 | vtable 不在模块内 / 结构失败 → Rejected | PASS |
| Verified 门控 | 17 项门控测试（含无人工确认、缺证据、不稳定、构建不匹配） | PASS |
| 版本不匹配 | 闸门：未知构建 / 插件版本不一致 / 旧版本候选重新验证 | PASS |
| 多次读取稳定性 | 同一对象重复读取稳定；读取变化标记 Unstable | PASS |

## 3. 集成测试（§11.2）

| 覆盖项 | 证据 | 状态 |
| --- | --- | --- |
| Person Locator 与 Memory Reader 集成 | 定位器测试基于同一内存源完成定位/字段读取；真实运行手动验证 | PARTIAL：缺自动化真实进程集成 |
| Person Locator 与 Attribute Reader 集成 | 诊断摘要测试从 LocatedObject 读取事实并关联；真实运行 60/60 唯一关联 | PASS |
| xref 集成 | 关联器 16 项测试；真实 `xref --link-all` 60/60 唯一、冲突 0 | PASS |
| calibrate 输出 | JSON 默认脱敏、本机模式含指针、Markdown 不含地址；真实运行证据 | PASS |
| dump 输出 | 诊断摘要 4 项测试；真实 summary/xref/calibration/uid 运行证据；CLI JSON 无自动化断言 | PARTIAL |
| Verified 审计记录 | 审计行字段完整且不含内存地址；Phase 7 审计 3 条 Verified | PASS |
| 失败回滚 | 布局 scope 应用后恢复；扫描失败清理临时目录；门控无写入副作用 | PARTIAL：CLI 写入失败注入未自动化 |

## 4. 安全测试（§11.3）

| 覆盖项 | 证据 | 状态 |
| --- | --- | --- |
| 无效地址 | 指针/候选字段不可读；定位器 InvalidPointer | PASS |
| 越界读取 | 候选探测越界失败；日期扫描无区域安全失败 | PASS |
| 不可读内存 | 多处不可读路径均返回失败原因，不崩溃 | PASS |
| 进程退出 | 稳定性：读取失败（进程退出）返回失败而不是空数据；存档切换：游戏退出暂停 | PASS（模拟） |
| 进程句柄失效 | 与不可读路径共用失败处理；无专门注入测试 | UNKNOWN |
| 读取中断 | 新增：读取中断后不得 Verified；取消令牌立即生效 | PASS |
| 不支持的游戏版本 | 闸门：未知构建/无构建号/candidate 构建拒绝 | PASS |
| 不匹配的布局 | 解析器未知构建返回 null；兼容配置冲突检测 | PASS |
| 错误姓名 | 定位器 NameNotFound/InvalidName；匹配诊断 NameMismatch | PASS |
| 错误出生日期 | 定位器 InvalidDateOfBirth；匹配诊断 BirthMismatch；未来日期排除 | PASS |
| 多候选关联 | 多候选为 Conflicted，拒绝自动选择 | PASS |
| 人工未确认 | 保持 HumanReviewPending，mark_verified=false | PASS |
| 重复确认 | 新增：重复确认结果与审计内容一致，不改变状态 | PASS |
| 旧版本候选再次验证 | 新增：旧构建候选重新确认仍为 UnsupportedBuild | PASS |

## 5. 真实 FM27 测试（§11.4，单独统计）

| 覆盖项 | 真实结果 | 状态 |
| --- | --- | --- |
| 真实游戏进程连接 | pid 72012，构建 26620374，插件 27.1，闸门 Verified | PASS |
| 真实 Person 定位 | 800 / 1500 条候选（两次运行） | PASS |
| 真实姓名读取 | 48/60（0.80），空姓名记录保持 null | PASS |
| 真实出生日期读取 | 60/60（1.00） | PASS |
| 真实属性关联 | 60/60 唯一关联，冲突 0 | PASS |
| 2～3 名球员人工核验 | 3 名（Erick Pulgar / Georginio Wijnaldum / Wang Junyang） | PASS |
| Verified 门控 | 3 名 Verified；其余保持 Pending，无误标 | PASS |

证据：`person-dump-summary-2026-11-25.json`、`person-attribute-link-audit-2026-11-25.json`、`person-verification-audit-2026-11-25.jsonl`、`PERSON-VERIFICATION-RESULTS.md`。

模拟测试通过不代替真实 FM27 PASS；上表为真实运行结果，与模拟测试分开统计。

## 6. 本轮新增测试

| 测试 | 目的 |
| --- | --- |
| 验证门控：重复人工确认结果一致且不改变状态 | 重复确认不得绕过或改变门控 |
| 验证门控：旧版本候选重新验证被拒绝 | 旧构建候选重新确认不得升级 |
| 候选字段：读取中断后不得 Verified | 读取中断必须失败或异常，不能产生 Verified |

## 7. 未覆盖与后续

- 进程句柄失效：未做专门注入；当前与不可读内存共用失败路径。
- CLI `dump` / `verify` 的 JSON 结构没有自动化断言，依赖真实运行证据；后续可加进程级集成测试。
- 真实进程退出/重新启动场景仅由既有模拟测试覆盖，未在真实 FM27 上重复执行。
- 真实姓名读取率 0.80 反映部分记录姓名槽为空，不是解码失败；这些记录仍可靠 UID 关联，但不满足 Verified 的姓名前置条件。
