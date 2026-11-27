# V3.3.2-08 文件所有权与修改范围

本版本由单一 Agent 顺序执行（任务书允许的降级路径），仍按责任域划分文件，避免后续并行开发冲突。

| 责任域 | 所有者 | 文件 | 说明 |
|---|---|---|---|
| 主控 / 架构 / 契约 | Agent 0 | `docs/transfer-director/online-learning-*.md`、`backend/alembic/versions/<08>.py` | 只新增迁移；不改历史迁移 |
| 在线监控与任务 | Agent 1 | `backend/app/services/background_scan.py`（最小扩展）、`backend/app/services/transfer_learning.py`（会话/游标/检查点）、`backend/app/api/routes_core.py`（导入完成后触发，单点） | 不新建调度器；`desktop-agent` 只读复用 |
| 事件识别 | Agent 2 | `backend/app/services/transfer_learning.py`（事件段）、`backend/app/models.py`（新增 4 表） | 事件指纹、去重、验证状态、存档隔离 |
| 全球/重点学习 | Agent 3 | `backend/app/services/transfer_learning.py`（画像段） | 复用 `transfer_strategy.confidence_tier` |
| 报价升级 | Agent 4 | `backend/app/services/transfer_director.py`（新增学习调整层）、`backend/app/api/routes_transfer_director.py`（响应透传） | 不另建报价引擎；样本不足回退 |
| API | Agent 0/1 | `backend/app/api/routes_transfer_learning.py`、`backend/app/main.py`（注册路由） | 新命名空间 `/transfer-learning/*` |
| 前端 | Agent 5 | `frontend/src/api/transferLearning.ts`、`frontend/src/views/TransferDirectorView.vue`、必要的 `frontend/src/types/*` | 复用现有页面与样式，不重做框架 |
| 测试 | 全体 | `backend/tests/test_v332_08_*.py` | 先写失败测试；不改既有断言 |

## 共享文件冲突规则

- `backend/app/models.py`：只追加 4 个新类，不改既有类。
- `backend/app/main.py`：只新增一行动态路由注册。
- `frontend/src/views/TransferDirectorView.vue`：只新增学习区块与对应请求，不改既有交互。
- `backend/app/services/transfer_director.py`：只新增函数并在三个 `generate_*_offers` 返回中追加字段；不改既有计算。

## 禁止修改

- `backend/alembic/versions/` 下任何已发布迁移。
- `live-reader/`、`desktop-agent/`（本版本只读复用；确有缺口时记录为后续建议）。
- `backend/tests/` 既有测试的断言与数据构造。
