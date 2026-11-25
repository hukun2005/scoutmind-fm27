# 跨存档与真实 FM27 验收（V3.2.8.1 Phase 6）

## 1. 真实环境观测（只读）

| 项目 | 观测值 |
| --- | --- |
| FM27 进程 | 存在，pid 72012 |
| 构建号 | 26620374 |
| 插件版本 | 27.1 |
| 布局 | FM27_1（闸门字段 Verified） |
| 版本闸门 | `allow_scan = true`，`status = Verified` |
| 存档身份 | `si:v1:file:b887415ab528890d6364a3bb2e5a36e485b8e9a823229ba553863a8c67418083`（用户确认 + 稳定文件元数据） |
| 存档身份状态 | VERIFIED，`snapshot_eligible = true` |
| 自动快照 | 关闭（`automatic_snapshot_enabled = false`） |

说明：存档身份指纹是哈希值，不含存档文件路径或内容。

## 2. 真实 Verified 尝试

命令（只读，不写内存/存档）：

```text
verify --name "<已知人工核对球员>" --human-confirmed --reviewer hukun --source fm27-ui \
       --evidence docs/evidence/v3.2.8.1/CROSS-SAVE-ACCEPTANCE.md \
       --save-identity si:v1:file:b887415a...
```

结果：

- 对历史人工核对过的两名球员（Erick Pulgar、Wang Junyang）均返回
  `没有找到与姓名/生日匹配的球员，拒绝继续`，退出码 3。
- 说明当前加载的存档与历史核对时不是同一份，或该球员不在当前存档；工具按设计**拒绝自动选择**，
  没有产生任何 Verified 结论。

## 3. A/B/A 步骤状态

| # | 步骤 | 状态 | 说明 |
| --- | --- | --- | --- |
| 1 | 在 A 中验证球员 | NOT_RUN | 当前存档无法按姓名唯一定位到已知人工核对球员 |
| 2 | 切换到 B | NOT_RUN | 需要用户在 FM27 内切换存档 |
| 3 | 检查 A 的 Verified 是否被错误复用 | PASS（自动化） | `VerifiedIdentityScopeTests` 跨存档用例 |
| 4 | 在 B 中建立自己的验证记录 | NOT_RUN | 需要人工在 B 中核对 |
| 5 | 返回 A | NOT_RUN | 需要用户操作 |
| 6 | 检查 A 的历史验证记录 | PASS（自动化） | Stale 不删除历史，仅禁止作为当前身份 |
| 7 | 检查旧指针是否失效 | PASS（自动化） | `session_changed` 用例 |
| 8 | 检查是否需要重新读取确认 | PASS（自动化） | `RevalidationRequired` 用例 |
| 9 | 检查 B 是否污染 A | PASS（自动化） | 不同存档指纹 → `Stale`；同 UID 不同存档不合并 |

## 4. 结论

- 自动化跨存档隔离、会话失效、历史保留：PASS。
- 真实 FM27 A/B/A 全流程：NOT_RUN（受限于需要人工切换存档与识别具体球员）。
- 综合状态：**PARTIAL**。不得把 PARTIAL 改写为 PASS。
