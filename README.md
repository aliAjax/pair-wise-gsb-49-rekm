# 再保险合约与巨灾暴露管理

纯Python标准库实现的再保险合约与巨灾暴露管理原型，使用SQLite持久化，HTTP接口由`http.server`提供。

## 模块结构

- `app.py`：命令行参数、依赖组装和服务启动。
- `src/domain.py`：领域数据类型、错误和基础校验。
- `src/rules.py`：状态转换、分层摊回、赔偿限额、恢复保费、大额复核和冲突检查。
- `src/repository.py`：SQLite建表、迁移、事务和查询。
- `src/service.py`：用例编排、分公司隔离、权限检查、乐观并发和审计。
- `src/identity.py`：用户目录，服务端解析角色与分公司归属。
- `src/http_api.py`：HTTP路由与统一错误响应。
- `src/audit.py`：事件时间线。
- `static/index.html`：最小演示页面。
- `tests/`：完整流程、规则计算、分公司隔离和失败场景测试。

## 启动

```bash
python3 app.py --db ./data.db --port 8325
```

默认端口为`8325`，默认数据库位于项目目录。服务启动时自动建表并迁移旧库（为`records`补充`org`列，旧行置空进入待分配队列）。

## 身份与分公司隔离

除`/health`和`/`外，请求只需提供`X-User-Id`。角色与分公司归属由服务端用户目录解析（`--users`指定JSON文件，缺省为内置演示目录），客户端无法通过伪造请求头切换身份或分公司。

- 创建记录按调用者身份固定分公司归属，请求体中的`org`一律忽略；总公司身份不能直接录单。
- 列表、详情、审计时间线、状态统计和业务动作只受理本分公司数据，越权读写返回`403`。
- 总公司管理员（`admin`角色且归属`HQ`）可见全部数据。

## 主要接口

- `GET /health`：健康检查。
- `GET /`：演示页面。
- `GET /api/records`：本分公司记录列表，可带`state`和`limit`参数。
- `GET /api/records/{id}`：记录详情。
- `GET /api/records/{id}/audit`：审计时间线。
- `GET /api/stats`：本分公司状态统计。
- `POST /api/records`：创建记录，请求体为`{"reference":"...","data":{...}}`。
- `POST /api/records/{id}/actions/{action}`：执行业务动作，请求体为`{"expected_version":1,"data":{...}}`。
- `GET /api/pending-assignments`：待分配队列（仅总公司管理员）。
- `POST /api/records/{id}/assign`：补全分公司归属，请求体为`{"org":"east","expected_version":1}`（仅总公司管理员，逐案补全，不可重复）。

## 业务规则

- 动作流：`bind`→`submit_claim`→`calculate`→（大额需`review`）→`settle`，任意`claim_submitted`/`calculated`状态可`reject`。
- 摊回金额超过500万元时，`settle`前必须由另一名财务执行`review`复核，复核人不能与核定人（`calculate`提交人）相同，否则返回`403`/`409`。
- 所有动作基于`expected_version`乐观并发控制：两人同时提交只接受先到者，后到者收到`409`版本冲突。
- 旧数据缺少分公司归属时自动进入待分配队列，补全前不能核定（`calculate`）或结算（`settle`）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整流程、规则计算、重复引用、权限拒绝、版本冲突、分公司隔离、大额复核和待分配队列。
