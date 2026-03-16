# wm

WM V1：后端 + SQLite 真数据进销存系统。

## V1 范围

已启用模块：
- `/base-data` 基础资料（商品/客户/供应商）
- `/purchase` 采购入库
- `/sales` 销售出库
- `/inventory` 库存查询

暂缓模块（页面保留，显示开发中）：
- `/login`
- `/customs`
- `/documents`
- `/io-tools`
- `/analytics`

## 后端说明

- 框架：Python `http.server`（无重依赖）
- 数据库：SQLite（`backend/wm.db`）
- 库存口径：`inventory_movements` 流水制（真相源）
  - quantity 一律存正数
  - 入库类型：`PURCHASE_IN`、`ADJUST_IN`
  - 出库类型：`SALES_OUT`、`ADJUST_OUT`
  - 在手库存 = 入库合计 - 出库合计

## 统一返回格式

- 成功：`{"ok": true, "data": ...}`
- 失败：`{"ok": false, "error": "..."}`

## 本地启动

### 1) 启动后端

```bash
cd /workspace/wm
python3 backend/app/main.py
```

### 2) 启动前端

```bash
python3 -m http.server 5500 -d frontend
```

访问：
- `http://127.0.0.1:5500/spa.html`

## V1 核心 API

- 主数据
  - `GET/POST /api/products`
  - `GET/PUT /api/products/{id}`
  - `GET/POST /api/customers`
  - `GET/PUT /api/customers/{id}`
  - `GET/POST /api/suppliers`
  - `GET/PUT /api/suppliers/{id}`
- 业务
  - `GET/POST /api/purchases`
  - `GET/PUT /api/purchases/{id}`
  - `GET/POST /api/orders`（销售出库语义）
  - `GET/PUT /api/orders/{id}`
- 库存
  - `GET /api/inventory/summary`
  - `GET /api/inventory/movements`
  - `POST /api/inventory/adjust`
- 占位
  - `GET /api/shipments`（返回空数组）
