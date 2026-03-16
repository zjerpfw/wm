# wm

WM V1：后端 + SQLite 真数据进销存系统。

## V1.0.2（规则收口）

本阶段新增：
- SAVED 后单据明细只读（商品/数量/单价不可改）。
- 单据改为 VOIDED 时自动生成反向库存流水进行冲销。
- PUT 更新单据时避免重复写库存流水（作废冲销幂等）。
- 库存流水增加来源字段：`ref_type`、`ref_id`、`ref_no`。

## V1.0.1（稳定收口）

本阶段完成：
- 唯一性校验：商品编码、客户编码、供应商编码、采购单号、销售单号。
- 数值校验：数量必须大于 0，单价不能为负数。
- 编辑能力：商品/客户/供应商支持编辑。
- 单据状态：采购单、销售单支持 `DRAFT` / `SAVED` / `VOIDED`。
- 列表筛选：基础资料、采购单、销售单、库存支持按关键字段搜索。
- 库存页增强：入库总量、出库总量、当前库存、安全库存、低库存状态。
- 错误提示统一中文。

> 说明：退货场景（采购退货/销售退货）将在后续按“单据类型决定库存增减方向”扩展。

## 数据库位置与备份

- SQLite 文件默认路径：`backend/wm.db`。
- 建议备份方式（先停服务再复制文件）：

```bash
cp backend/wm.db backend/wm.db.bak.$(date +%Y%m%d_%H%M%S)
```

## 最短启动步骤

```bash
cd /workspace/wm
python3 backend/app/main.py
python3 -m http.server 5500 -d frontend
```

浏览器访问：
- `http://127.0.0.1:5500/spa.html`

## API 概览

- 主数据：
  - `GET/POST /api/products`
  - `PUT /api/products/{id}`
  - `GET/POST /api/customers`
  - `PUT /api/customers/{id}`
  - `GET/POST /api/suppliers`
  - `PUT /api/suppliers/{id}`
- 业务单据：
  - `GET/POST /api/purchases`
  - `PUT /api/purchases/{id}`
  - `GET/POST /api/orders`
  - `PUT /api/orders/{id}`
- 库存：
  - `GET /api/inventory/summary`
  - `GET /api/inventory/movements`
  - `POST /api/inventory/adjust`
