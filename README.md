# wm

外贸订单与库存系统 MVP（前后端项目示例，**零外网依赖可运行版**，Excel 风格交互）。
外贸订单与库存系统 MVP（前后端项目示例，**零外网依赖可运行版**）。

## 技术选型建议（当前可直接运行）

- **后端语言：Python（标准库 HTTP Server）**
  - 无需安装 FastAPI / 第三方依赖，受限网络也可直接启动。
- **前端语言：JavaScript（原生 HTML + JS）**
  - 快速验证业务流程，后续可升级到 Vue/React。
- **数据库：SQLite**
  - 单机快速落地，后续可迁移到 MySQL/PostgreSQL。

> 如果你后续网络环境放开，可再升级到 `FastAPI + Vue/React` 结构。

---

## 已实现功能（MVP）

1. 商品主数据管理（SKU、类别、颜色、尺寸、HS、装箱参数）。
2. 入库管理（增加库存、记录库存流水）。
3. 客户下单（销售订单 + 行项目）。
4. 按箱码发货（箱码唯一、每箱SKU明细、毛重净重体积）。
5. 库存与订单剩余查询：
   - 实际库存（on_hand）
   - 已发货（shipped_total）
   - 订单总量（ordered_total）
   - 剩余待发（remaining_order_qty）

---

## 项目结构

```text
wm/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   └── main.py
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   └── app.js
└── scripts/
    └── build_backend.sh
```

---

## 本地运行（无需 pip install）

### 1) 启动后端（源码方式）

```bash
cd /workspace/wm
python3 backend/app/main.py
```

默认监听：
- `http://127.0.0.1:8000`

### 2) 打开前端

```bash
python3 -m http.server 5500 -d frontend
```

访问：
- `http://127.0.0.1:5500`

---

## 编译打包（本地可执行软件包）

你说的“直接编译后本地用”，这里提供 **离线可打包** 方案：把后端打成一个 `pyz` 可执行包。

### 1) 生成可执行包

```bash
cd /workspace/wm
./scripts/build_backend.sh
```

输出文件：
- `dist/wm_backend.pyz`

### 2) 运行打包后的后端

```bash
python3 dist/wm_backend.pyz
```

然后前端照常运行：

```bash
python3 -m http.server 5500 -d frontend
```

---

## API 快速示例

### 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 新建商品

```bash
curl -X POST http://127.0.0.1:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{
    "sku":"SKU-RED-M",
    "category_name":"T恤",
    "category_hs_code":"610910",
    "color":"RED",
    "size":"M",
    "default_packing_qty":50,
    "carton_length_cm":60,
    "carton_width_cm":40,
    "carton_height_cm":35,
    "standard_gross_weight_kg":12,
    "standard_net_weight_kg":10,
    "customer_hs_code":"6109100000",
    "customs_cn_name":"针织T恤"
  }'
```

### 入库

```bash
curl -X POST http://127.0.0.1:8000/api/inventory/receipt \
  -H "Content-Type: application/json" \
  -d '{"sku":"SKU-RED-M","qty":100,"reference_no":"GRN-001"}'
```

### 创建订单

```bash
curl -X POST http://127.0.0.1:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name":"ACME LTD",
    "customer_po":"PO-2026-001",
    "lines":[{"sku":"SKU-RED-M","qty":100}]
  }'
```

### 创建发货（按箱码）

```bash
curl -X POST http://127.0.0.1:8000/api/shipments \
  -H "Content-Type: application/json" \
  -d '{
    "order_id":1,
    "shipment_no":"SHIP-001",
    "boxes":[
      {
        "box_code":"BOX-001",
        "gross_weight_kg":12,
        "net_weight_kg":10,
        "volume_cbm":0.07,
        "items":[{"sku":"SKU-RED-M","qty":50}]
      }
    ]
  }'
```

### 查询库存与剩余

```bash
curl http://127.0.0.1:8000/api/inventory/summary/SKU-RED-M
```

---

## 下一步建议

- 加入用户权限（销售/仓库/报关/财务）。
- 加入客户维度 HS 码映射表与报关模板输出。
- 增加批次、退货、分批发货、对接物流 API。
- 前端升级 Vue/React，支持扫码枪与打印箱唛。
