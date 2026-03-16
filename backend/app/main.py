from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "backend" / "wm.db"

app = FastAPI(title="WM 外贸订单库存系统", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                category_name TEXT NOT NULL,
                category_hs_code TEXT NOT NULL,
                color TEXT NOT NULL,
                size TEXT NOT NULL,
                default_packing_qty INTEGER NOT NULL,
                carton_length_cm REAL NOT NULL,
                carton_width_cm REAL NOT NULL,
                carton_height_cm REAL NOT NULL,
                standard_gross_weight_kg REAL NOT NULL,
                standard_net_weight_kg REAL NOT NULL,
                customer_hs_code TEXT NOT NULL,
                customs_cn_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_balances (
                sku TEXT PRIMARY KEY,
                on_hand_qty INTEGER NOT NULL DEFAULT 0,
                shipped_qty INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (sku) REFERENCES products(sku)
            );

            CREATE TABLE IF NOT EXISTS inventory_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                event_type TEXT NOT NULL,
                qty_change INTEGER NOT NULL,
                reference_no TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sku) REFERENCES products(sku)
            );

            CREATE TABLE IF NOT EXISTS sales_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_po TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sales_order_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                sku TEXT NOT NULL,
                ordered_qty INTEGER NOT NULL,
                shipped_qty INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (order_id) REFERENCES sales_orders(id),
                FOREIGN KEY (sku) REFERENCES products(sku)
            );

            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                shipment_no TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES sales_orders(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                box_code TEXT NOT NULL UNIQUE,
                gross_weight_kg REAL NOT NULL,
                net_weight_kg REAL NOT NULL,
                volume_cbm REAL NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_box_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_id INTEGER NOT NULL,
                sku TEXT NOT NULL,
                qty INTEGER NOT NULL,
                FOREIGN KEY (box_id) REFERENCES shipment_boxes(id),
                FOREIGN KEY (sku) REFERENCES products(sku)
            );
            """
        )
        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


class ProductIn(BaseModel):
    sku: str
    category_name: str
    category_hs_code: str
    color: str
    size: str
    default_packing_qty: int = Field(gt=0)
    carton_length_cm: float = Field(gt=0)
    carton_width_cm: float = Field(gt=0)
    carton_height_cm: float = Field(gt=0)
    standard_gross_weight_kg: float = Field(gt=0)
    standard_net_weight_kg: float = Field(gt=0)
    customer_hs_code: str
    customs_cn_name: str


class ReceiptIn(BaseModel):
    sku: str
    qty: int = Field(gt=0)
    reference_no: str


class OrderLineIn(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class SalesOrderIn(BaseModel):
    customer_name: str
    customer_po: str
    lines: List[OrderLineIn]


class BoxItemIn(BaseModel):
    sku: str
    qty: int = Field(gt=0)


class BoxIn(BaseModel):
    box_code: str
    gross_weight_kg: float = Field(gt=0)
    net_weight_kg: float = Field(gt=0)
    volume_cbm: float = Field(gt=0)
    items: List[BoxItemIn]


class ShipmentIn(BaseModel):
    order_id: int
    shipment_no: str
    boxes: List[BoxIn]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/products")
def create_product(payload: ProductIn) -> dict:
    with closing(get_conn()) as conn:
        try:
            conn.execute(
                """
                INSERT INTO products (
                    sku, category_name, category_hs_code, color, size,
                    default_packing_qty, carton_length_cm, carton_width_cm, carton_height_cm,
                    standard_gross_weight_kg, standard_net_weight_kg,
                    customer_hs_code, customs_cn_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.sku,
                    payload.category_name,
                    payload.category_hs_code,
                    payload.color,
                    payload.size,
                    payload.default_packing_qty,
                    payload.carton_length_cm,
                    payload.carton_width_cm,
                    payload.carton_height_cm,
                    payload.standard_gross_weight_kg,
                    payload.standard_net_weight_kg,
                    payload.customer_hs_code,
                    payload.customs_cn_name,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO inventory_balances (sku, on_hand_qty, shipped_qty) VALUES (?, 0, 0)",
                (payload.sku,),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=400, detail=f"商品创建失败: {exc}") from exc
    return {"message": "商品创建成功", "sku": payload.sku}


@app.get("/api/products")
def list_products() -> list[dict]:
    with closing(get_conn()) as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/inventory/receipt")
def receive_stock(payload: ReceiptIn) -> dict:
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn:
        product = conn.execute("SELECT sku FROM products WHERE sku = ?", (payload.sku,)).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="SKU 不存在")

        conn.execute(
            "UPDATE inventory_balances SET on_hand_qty = on_hand_qty + ? WHERE sku = ?",
            (payload.qty, payload.sku),
        )
        conn.execute(
            "INSERT INTO inventory_ledger (sku, event_type, qty_change, reference_no, created_at) VALUES (?, 'RECEIPT', ?, ?, ?)",
            (payload.sku, payload.qty, payload.reference_no, now),
        )
        conn.commit()

    return {"message": "入库成功", "sku": payload.sku, "qty": payload.qty}


@app.post("/api/orders")
def create_order(payload: SalesOrderIn) -> dict:
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sales_orders (customer_name, customer_po, created_at) VALUES (?, ?, ?)",
            (payload.customer_name, payload.customer_po, now),
        )
        order_id = cur.lastrowid
        for line in payload.lines:
            exists = conn.execute("SELECT sku FROM products WHERE sku = ?", (line.sku,)).fetchone()
            if not exists:
                conn.rollback()
                raise HTTPException(status_code=404, detail=f"SKU 不存在: {line.sku}")
            cur.execute(
                "INSERT INTO sales_order_lines (order_id, sku, ordered_qty, shipped_qty) VALUES (?, ?, ?, 0)",
                (order_id, line.sku, line.qty),
            )
        conn.commit()

    return {"message": "订单创建成功", "order_id": order_id}


@app.get("/api/orders/{order_id}")
def get_order(order_id: int) -> dict:
    with closing(get_conn()) as conn:
        order = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        lines = conn.execute("SELECT sku, ordered_qty, shipped_qty FROM sales_order_lines WHERE order_id = ?", (order_id,)).fetchall()

    return {"order": dict(order), "lines": [dict(r) for r in lines]}


@app.post("/api/shipments")
def create_shipment(payload: ShipmentIn) -> dict:
    now = datetime.utcnow().isoformat()
    with closing(get_conn()) as conn:
        order = conn.execute("SELECT id FROM sales_orders WHERE id = ?", (payload.order_id,)).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")

        order_line_rows = conn.execute(
            "SELECT sku, ordered_qty, shipped_qty FROM sales_order_lines WHERE order_id = ?",
            (payload.order_id,),
        ).fetchall()
        line_map = {row["sku"]: {"ordered": row["ordered_qty"], "shipped": row["shipped_qty"]} for row in order_line_rows}

        picked: dict[str, int] = {}
        total_gross_weight = 0.0
        total_net_weight = 0.0

        for box in payload.boxes:
            total_gross_weight += box.gross_weight_kg
            total_net_weight += box.net_weight_kg
            for item in box.items:
                picked[item.sku] = picked.get(item.sku, 0) + item.qty

        # 校验库存与订单剩余
        for sku, qty in picked.items():
            if sku not in line_map:
                raise HTTPException(status_code=400, detail=f"SKU {sku} 不在订单中")
            remaining = line_map[sku]["ordered"] - line_map[sku]["shipped"]
            if qty > remaining:
                raise HTTPException(status_code=400, detail=f"SKU {sku} 发货超订单剩余")

            bal = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE sku = ?", (sku,)).fetchone()
            if not bal or bal["on_hand_qty"] < qty:
                raise HTTPException(status_code=400, detail=f"SKU {sku} 库存不足")

        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO shipments (order_id, shipment_no, created_at) VALUES (?, ?, ?)",
                (payload.order_id, payload.shipment_no, now),
            )
            shipment_id = cur.lastrowid

            for box in payload.boxes:
                cur.execute(
                    "INSERT INTO shipment_boxes (shipment_id, box_code, gross_weight_kg, net_weight_kg, volume_cbm) VALUES (?, ?, ?, ?, ?)",
                    (shipment_id, box.box_code, box.gross_weight_kg, box.net_weight_kg, box.volume_cbm),
                )
                box_id = cur.lastrowid
                for item in box.items:
                    cur.execute(
                        "INSERT INTO shipment_box_items (box_id, sku, qty) VALUES (?, ?, ?)",
                        (box_id, item.sku, item.qty),
                    )

            for sku, qty in picked.items():
                cur.execute("UPDATE inventory_balances SET on_hand_qty = on_hand_qty - ?, shipped_qty = shipped_qty + ? WHERE sku = ?", (qty, qty, sku))
                cur.execute(
                    "UPDATE sales_order_lines SET shipped_qty = shipped_qty + ? WHERE order_id = ? AND sku = ?",
                    (qty, payload.order_id, sku),
                )
                cur.execute(
                    "INSERT INTO inventory_ledger (sku, event_type, qty_change, reference_no, created_at) VALUES (?, 'SHIPMENT', ?, ?, ?)",
                    (sku, -qty, payload.shipment_no, now),
                )

            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise HTTPException(status_code=400, detail=f"发货失败: {exc}") from exc

    return {
        "message": "发货成功",
        "shipment_no": payload.shipment_no,
        "total_gross_weight_kg": round(total_gross_weight, 3),
        "total_net_weight_kg": round(total_net_weight, 3),
        "sku_shipped": picked,
    }


@app.get("/api/inventory/summary/{sku}")
def inventory_summary(sku: str) -> dict:
    with closing(get_conn()) as conn:
        bal = conn.execute("SELECT on_hand_qty, shipped_qty FROM inventory_balances WHERE sku = ?", (sku,)).fetchone()
        if not bal:
            raise HTTPException(status_code=404, detail="SKU 不存在")

        rows = conn.execute(
            "SELECT SUM(ordered_qty) AS ordered_total, SUM(shipped_qty) AS shipped_total FROM sales_order_lines WHERE sku = ?",
            (sku,),
        ).fetchone()

    ordered = int(rows["ordered_total"] or 0)
    shipped_so = int(rows["shipped_total"] or 0)
    return {
        "sku": sku,
        "on_hand": bal["on_hand_qty"],
        "shipped_total": bal["shipped_qty"],
        "ordered_total": ordered,
        "remaining_order_qty": ordered - shipped_so,
    }
