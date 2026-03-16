# wm

外贸订单与库存系统 MVP（SaaS ERP 方向，零外网依赖可运行）。

## 当前形态（你要求的下一步）

- ✅ 每个业务一个页面跳转：基础资料、入库、订单、发货、库存。
- ✅ 输入与基础资料联动：订单选客户、入库/库存选 SKU、发货选订单。
- ✅ 继续保持离线可运行（Python 标准库 + SQLite + 原生前端）。

## 页面导航

- `frontend/index.html`：ERP 导航门户
- `frontend/pages/base-data.html`：基础资料（客户 + 商品）
- `frontend/pages/receipt.html`：入库业务
- `frontend/pages/order.html`：销售订单
- `frontend/pages/shipment.html`：发货装箱
- `frontend/pages/inventory.html`：库存查询

## API（核心）

- 基础资料
  - `GET /api/customers`
  - `POST /api/customers`
  - `GET /api/products`
  - `POST /api/products`
- 业务单据
  - `POST /api/inventory/receipt`
  - `GET /api/orders`
  - `POST /api/orders`
  - `GET /api/shipments`
  - `GET /api/shipments/{id}`
  - `POST /api/shipments`
- 查询
  - `GET /api/inventory/summary/{sku}`

## 本地运行

```bash
cd /workspace/wm
python3 backend/app/main.py
```

新开终端：

```bash
python3 -m http.server 5500 -d frontend
```

访问：

- `http://127.0.0.1:5500`

## 打包后端（可选）

```bash
./scripts/build_backend.sh
python3 dist/wm_backend.pyz
```

## 下一步建议（真正 SaaS ERP）

1. 增加登录与角色权限（销售/仓库/报关/财务）。
2. 增加报关单模块（按发货箱明细自动汇总）。
3. 增加导入导出（Excel 模板导入、报表导出）。
4. 增加多租户（company_id）实现 SaaS 化隔离。
