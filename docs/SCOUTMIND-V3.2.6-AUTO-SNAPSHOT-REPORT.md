# ScoutMind FM27 V3.2.6 自动快照报告

**状态：BLOCKED（不得启用）**

## 1. 依赖链

```text
日期定位（heuristic）
    → 日期可信度（需要 session_verified / build_verified）
    → 存档身份（只有一个真实存档）
    → 持久化 Worker（未实现）
    → 自动快照
```

## 2. 当前阻塞原因

1. **日期只有启发式**：`world-date` 明确标注 `heuristic`，未达到自动采集门槛；
2. **没有可信度状态机**：`session_verified` / `build_verified` 未落库，也没有证据记录；
3. **没有持久化 Worker**：导入仍占用一次请求（已移出事件循环，但没有 202/进度/取消/重试）；
4. **没有存档切换检测**：真实多存档未验证。

## 3. 已就绪的部分

- 导入幂等：`(fm_save_id, scan_id)`，重复上传返回 `duplicate=true`；
- 启动恢复：`running` → `failed` + `interrupted` 行；
- CaptureRun 日期来源字段：`date_source` / `date_confidence` / `date_read_status`；
- 文件校验：SHA-256 + 大小 + manifest（Agent 三件套）。

## 4. 功能开关要求

RC 中 `enable_automatic_snapshot` 必须默认 **false**，前端显示：

```text
自动快照暂不可用：日期定位尚未完成真实环境验证。
你仍然可以使用手动导入与已有数据分析。
```

## 5. 验收

| 项 | 状态 |
| --- | --- |
| 日期变化触发 | NOT_RUN |
| 同日幂等（save+date） | 未实现 |
| 日期倒退保护 | 未实现 |
| 存档切换保护 | NOT_RUN |
| Worker 恢复 | NOT_RUN |
