# wm

简易进销存系统原型（SaaS ERP 方向）。

## 本次实现（按你的最新要求）

- 使用 **Vue 3 + Element Plus** 做了一个 SPA 原型页面：`frontend/spa.html`。
- 每个业务功能独立路由：
  - `/base-data` 基础资料
  - `/purchase` 采购入库
  - `/sales` 销售出库
  - `/inventory` 库存查询
- 基础资料模型：
  - Products（ID、名称、规格、单位、默认单价）
  - Suppliers（ID、供应商名称、联系人、电话）
- 关键联动（采购入库页）已实现：
  - 选择商品后自动带出“规格、单位、默认单价”
  - 数量可手工录入
- 使用响应式 store 做状态管理，模拟数据库（内存态）。

## 运行方式

> 说明：该原型依赖 CDN 加载 Vue / Vue Router / Element Plus。

```bash
cd /workspace/wm
python3 -m http.server 5500 -d frontend
```

浏览器访问：

- `http://127.0.0.1:5500/spa.html`

## 架构说明（原型阶段）

- 前端：Vue SPA + 路由 + 组件化页面
- 状态：单一 reactive store（可替换为 Pinia）
- 后端：后续可对接现有 Python API 或直接升级为多租户 SaaS 后端

## 下一步建议

1. 把内存 store 换成真实 API 持久化。
2. 加入登录与角色权限（采购/销售/仓库/财务）。
3. 加入客户、销售订单、应收应付等模块。
4. 增加租户字段 company_id，支持多公司隔离。
