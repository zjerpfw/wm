# wm

wm 外贸订单与库存系统，当前为 **Web SPA + Python + SQLite 真数据** 实现。

## 当前状态

已完成模块：
- 基础资料：商品、客户、供应商。
- 采购入库、销售出库。
- 库存汇总 / 库存流水。
- V1.0.1 / V1.0.2 收口规则。
- V1.1 发货装箱第一版。

## V1.0.2 规则说明

- 唯一性校验：商品编码、客户编码、供应商编码、采购单号、销售单号。
- 中文错误提示。
- 采购单 / 销售单在 `SAVED` 后明细只读。
- 采购单 / 销售单在 `VOIDED` 时自动生成反向库存流水。
- 库存流水支持 `ref_type` / `ref_id` / `ref_no` 追溯。

## V1.1 发货装箱模块

- `shipments`：发货单，可从销售单创建。
- `shipment_items`：发货明细，创建发货单时从销售单明细快照生成。
- `shipment_boxes`：箱信息，同一 `shipment_id` 下 `box_no` 唯一。
- `shipment_box_items`：箱内商品明细。
- 支持一个发货单多个箱、一个箱多个商品、同一商品拆分到多个箱。
- 后端校验同一发货明细的累计装箱数量不能大于发货数量。
- 发货单 `DRAFT` 可编辑，`SAVED` 只读，`VOIDED` 不可编辑。
- 建箱 / 改箱本身不直接写库存流水。

## SQLite 文件位置与备份

- 默认数据库文件：`backend/wm.db`。
- 建议先停止后端再备份：

```bash
cp backend/wm.db backend/wm.db.bak.$(date +%Y%m%d_%H%M%S)
```

## 最短启动步骤

```bash
cd /workspace/wm
python3 backend/app/main.py
python3 -m http.server 5500 -d frontend
```

访问地址：
- `http://127.0.0.1:5500/spa.html`

## API 概览

- 主数据
  - `GET/POST /api/products`
  - `PUT /api/products/{id}`
  - `GET/POST /api/customers`
  - `PUT /api/customers/{id}`
  - `GET/POST /api/suppliers`
  - `PUT /api/suppliers/{id}`
- 采购 / 销售
  - `GET/POST /api/purchases`
  - `PUT /api/purchases/{id}`
  - `GET/POST /api/orders`
  - `GET /api/orders/{id}`
  - `PUT /api/orders/{id}`
- 发货装箱
  - `GET/POST /api/shipments`
  - `GET /api/shipments/{id}`
  - `GET /api/shipments/{id}/summary`
  - `PUT /api/shipments/{id}`
  - `POST /api/shipments/{id}/boxes`
  - `PUT /api/shipments/{id}/boxes/{box_id}`
  - `DELETE /api/shipments/{id}/boxes/{box_id}`
  - `POST /api/shipments/{id}/boxes/{box_id}/items`
  - `PUT /api/shipments/{id}/boxes/{box_id}/items/{item_id}`
  - `DELETE /api/shipments/{id}/boxes/{box_id}/items/{item_id}`
- 库存
  - `GET /api/inventory/summary`
  - `GET /api/inventory/movements`
  - `POST /api/inventory/adjust`

## 手动测试建议

1. 新建商品、客户、供应商。
2. 创建采购单补库存。
3. 创建销售单。
4. 在“发货装箱”页面从销售单创建发货单。
5. 新增多个箱，并在不同箱中录入同一个发货明细商品。
6. 验证发货明细中的 `shipment_qty / boxed_qty / remaining_qty` 是否正确。
7. 故意让累计装箱量超过发货量，确认后端返回中文报错。
8. 将发货单改为 `SAVED`，确认箱与箱内商品不可再编辑。
9. 尝试删除非空箱，确认后端阻止删除并返回中文提示。
