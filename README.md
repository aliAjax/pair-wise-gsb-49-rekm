# 再保险合约与巨灾暴露管理

纯Python标准库实现的再保险合约与巨灾暴露管理原型，使用SQLite持久化，HTTP接口由`http.server`提供。

## 模块结构

- `app.py`：命令行参数、依赖组装和服务启动。
- `src/domain.py`：领域数据类型、错误和基础校验。
- `src/rules.py`：状态转换、分层摊回、赔偿限额和恢复保费和冲突检查。
- `src/repository.py`：SQLite建表、事务和查询。
- `src/service.py`：用例编排、权限检查、乐观并发和审计。
- `src/http_api.py`：HTTP路由与统一错误响应。
- `src/audit.py`：事件时间线。
- `static/index.html`：最小演示页面。
- `tests/`：完整流程、规则计算和失败场景测试。

## 启动

```bash
python3 app.py --db ./data.db --port 8325
```

默认端口为`8325`，默认数据库位于项目目录。服务启动时自动建表。

## 主要接口

- `GET /health`：健康检查。
- `GET /`：演示页面。
- `GET /api/records`：本分公司记录列表，可带`state`和`limit`参数。
- `GET /api/records/{id}`：记录详情，仅限本分公司。
- `GET /api/records/{id}/audit`：审计时间线，仅限本分公司。
- `GET /api/records/pending-assignment`：归属待分配队列，仅总公司管理员。
- `GET /api/stats`：本分公司状态统计。
- `POST /api/records`：创建记录，请求体为`{"reference":"...","data":{...}}`，归属固定为提交人所属分公司。
- `POST /api/records/{id}/actions/{action}`：执行业务动作，请求体为`{"expected_version":1,"data":{...}}`。

## 身份与权限

- 请求只需提供`X-User-Id`；角色与分公司由服务端身份目录（`users`表）解析，客户端改请求头无法越权，未登记身份直接拒绝。
- 列表、详情、审计、统计和动作均按分公司隔离，跨分公司读写返回403；总公司管理员（`admin`）可跨分公司。
- 摊回金额超过500万元时，`settle`前必须由财务执行`review`复核，结算提交人与复核人不能同号；两人同时提交以版本号为准，先到者成功，后到者收到409版本冲突。
- 旧数据缺少分公司归属时自动进入待分配队列，仅总公司管理员可通过`assign_org`动作逐案补全（`data`为`{"org":"华东分公司"}`），补全前不能核定（`calculate`）或结算（`settle`）。
- 内置演示用户：`demo-admin`（总公司管理员）、`demo-underwriter`、`demo-claims`、`demo-finance`、`demo-finance-2`（均为华东分公司）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖完整流程、规则计算、重复引用、权限拒绝、版本冲突、分公司隔离、超限复核和旧数据待分配补全。
