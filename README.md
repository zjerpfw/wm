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
- 同一销售单支持拆分生成多个发货单，并返回每个销售明细的 `remaining_to_ship` 剩余可发数量。
- 支持“累计发货数量控制”开关：开启时，历史未作废发货单 + 当前新发货单数量不能大于销售数量；关闭时允许超量发货。
- 后端校验同一发货明细的累计装箱数量不能大于发货数量。
- 发货单 `DRAFT` 可编辑，`SAVED` 只读，`VOIDED` 不可编辑。
- 建箱 / 改箱本身不直接写库存流水。
- 库存扣减时点已切换为：`发货单 DRAFT -> SAVED` 才扣库存；`SAVED -> VOIDED` 才回补库存。

## V1.2 Packing List / 箱单（第一版）

- 以单张发货单为单位生成 Packing List。
- 支持页面预览与浏览器打印。
- Header 至少显示：`shipment_no`、`shipment_date`、`customer_name`、`note`。
- Box Details 按箱显示：`box_no`、尺寸、毛重、净重、体积，以及每箱商品明细。
- Summary 按商品汇总显示总数量，并展示总箱数、总毛重、总净重、总体积。
- `VOIDED` 发货单仍可预览，但页面会明确显示“已作废 / VOIDED，仅供查看”。

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

## 自动化测试

当前仓库已提供库存时点与发货追溯的后端集成测试，使用 Python 标准库 `unittest`，无需额外安装重型测试框架。

一条命令运行：

```bash
python3 -m unittest discover -s tests -v
```

覆盖重点：
- 采购入库后库存增加。
- 销售单保存不减库存。
- 发货单 `DRAFT` 不减库存，`DRAFT -> SAVED` 才扣库存。
- 装箱增删改本身不影响库存。
- 发货单 `SAVED -> VOIDED` 才回补库存。
- 重复 `SAVED` / 重复 `VOIDED` 不重复记账。
- `DRAFT -> VOIDED` 不回冲未发生库存。
- `inventory_movements` 中 `SHIPMENT / VOID_SHIPMENT` 的 `ref_type / ref_id / ref_no` 追溯正确。
- 同一销售单可拆成多张发货单，且在开启控制参数时累计发货数量不允许超量。
- 发货单作废后会释放销售单的 `remaining_to_ship`。
- Packing List 可从发货单列表或发货单详情页进入，并支持浏览器打印预览。

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
- 参数设置
  - `GET /api/settings/shipment-limit`
  - `PUT /api/settings/shipment-limit`
- 发货装箱
  - `GET/POST /api/shipments`
  - `GET /api/shipments/{id}`
  - `GET /api/shipments/{id}/summary`
  - `GET /api/shipments/{id}/packing-list`
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
4. 确认“销售单保存后库存不减少”。
5. 在“发货装箱”页面从销售单创建发货单。
6. 发货单保持 `DRAFT`，确认库存仍不变化。
7. 新增多个箱，并在不同箱中录入同一个发货明细商品。
8. 验证发货明细中的 `shipment_qty / boxed_qty / remaining_qty` 是否正确。
9. 故意让累计装箱量超过发货量，确认后端返回中文报错。
10. 将发货单改为 `SAVED`，确认库存减少且箱与箱内商品不可再编辑。
11. 再把发货单改为 `VOIDED`，确认库存回补。
12. 尝试删除非空箱，确认后端阻止删除并返回中文提示。
13. 点击发货单列表或详情中的 `Packing List` 入口。
14. 检查 Header / Box Details / Summary 三块内容是否正确。
15. 打开浏览器打印预览，确认打印版布局基本可读。
16. 将发货单作废后再次打开 Packing List，确认页面明确显示“已作废 / VOIDED”语义。
