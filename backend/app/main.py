from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# ---------- infra ----------
def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def resolve_db_path() -> Path:
    src_candidate = Path(__file__).resolve().parents[2] / "backend" / "wm.db"
    if src_candidate.parent.exists():
        return src_candidate
    return Path.cwd() / "wm.db"


DB_PATH = resolve_db_path()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Content-Length 非法") from exc
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("JSON 格式错误") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def must_str(data: dict[str, Any], key: str) -> str:
    v = str(data.get(key, "")).strip()
    if not v:
        raise ValueError(f"字段缺失: {key}")
    return v


def to_num(v: Any, field: str, min_val: float | None = None) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"字段 {field} 必须是数字") from exc
    if min_val is not None and x < min_val:
        raise ValueError(f"字段 {field} 必须 >= {min_val}")
    return x


# ---------- db ----------
def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                spec TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'PCS',
                hs_code TEXT NOT NULL DEFAULT '',
                customs_name TEXT NOT NULL DEFAULT '',
                material TEXT NOT NULL DEFAULT '',
                origin_country TEXT NOT NULL DEFAULT 'CN',
                qty_per_carton REAL NOT NULL DEFAULT 0,
                carton_length REAL NOT NULL DEFAULT 0,
                carton_width REAL NOT NULL DEFAULT 0,
                carton_height REAL NOT NULL DEFAULT 0,
                net_weight REAL NOT NULL DEFAULT 0,
                gross_weight REAL NOT NULL DEFAULT 0,
                safety_stock REAL NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                country TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'USD',
                trade_term TEXT NOT NULL DEFAULT '',
                default_port TEXT NOT NULL DEFAULT '',
                payment_term TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                country TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT 'USD',
                payment_term TEXT NOT NULL DEFAULT '',
                tax_scheme TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_no TEXT NOT NULL UNIQUE,
                supplier_id INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                eta TEXT NOT NULL DEFAULT '',
                port TEXT NOT NULL DEFAULT '',
                payment_term TEXT NOT NULL DEFAULT '',
                transport_mode TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'CONFIRMED',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            );

            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                spec_snapshot TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'PCS',
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL DEFAULT 0,
                carton_count REAL NOT NULL DEFAULT 0,
                line_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS sales_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sales_no TEXT NOT NULL UNIQUE,
                customer_id INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                port TEXT NOT NULL DEFAULT '',
                etd TEXT NOT NULL DEFAULT '',
                payment_term TEXT NOT NULL DEFAULT '',
                transport_mode TEXT NOT NULL DEFAULT '',
                shipping_mark TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'CONFIRMED',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS sales_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sales_order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                spec_snapshot TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'PCS',
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL DEFAULT 0,
                carton_no TEXT NOT NULL DEFAULT '',
                line_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS inventory_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL, -- PURCHASE_IN / SALES_OUT / ADJUST_IN / ADJUST_OUT
                ref_type TEXT NOT NULL,
                ref_id INTEGER,
                quantity REAL NOT NULL,      -- V1规则：一律存正数
                unit_cost REAL NOT NULL DEFAULT 0,
                movement_date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )
        conn.commit()


def stock_available(conn: sqlite3.Connection, product_id: int) -> float:
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN movement_type IN ('PURCHASE_IN','ADJUST_IN') THEN quantity ELSE 0 END),0) AS total_in,
          COALESCE(SUM(CASE WHEN movement_type IN ('SALES_OUT','ADJUST_OUT') THEN quantity ELSE 0 END),0) AS total_out
        FROM inventory_movements
        WHERE product_id=?
        """,
        (product_id,),
    ).fetchone()
    return float(row["total_in"] - row["total_out"])


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WMV1/1.1"

    def _write(self, code: int, payload: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if code != 204:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def ok(self, data: Any, code: int = 200) -> None:
        self._write(code, {"ok": True, "data": data})

    def err(self, message: str, code: int = 400) -> None:
        self._write(code, {"ok": False, "error": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._write(204, {})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/health":
                return self.ok({"status": "ok"})

            if path == "/api/products":
                with closing(get_conn()) as conn:
                    rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/products/"):
                pid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
                return self.ok(dict(row)) if row else self.err("商品不存在", 404)

            if path == "/api/customers":
                with closing(get_conn()) as conn:
                    rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/customers/"):
                cid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    row = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
                return self.ok(dict(row)) if row else self.err("客户不存在", 404)

            if path == "/api/suppliers":
                with closing(get_conn()) as conn:
                    rows = conn.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/suppliers/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    row = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
                return self.ok(dict(row)) if row else self.err("供应商不存在", 404)

            if path == "/api/purchases":
                with closing(get_conn()) as conn:
                    rows = conn.execute(
                        "SELECT p.*, s.name AS supplier_name FROM purchase_orders p JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.id DESC"
                    ).fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/purchases/"):
                pid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    head = conn.execute("SELECT * FROM purchase_orders WHERE id=?", (pid,)).fetchone()
                    if not head:
                        return self.err("采购单不存在", 404)
                    items = conn.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id=?", (pid,)).fetchall()
                return self.ok({"header": dict(head), "items": [dict(i) for i in items]})

            # /api/orders 语义：销售出库单
            if path == "/api/orders":
                with closing(get_conn()) as conn:
                    rows = conn.execute(
                        "SELECT o.*, c.name AS customer_name FROM sales_orders o JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC"
                    ).fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/orders/"):
                oid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    head = conn.execute("SELECT * FROM sales_orders WHERE id=?", (oid,)).fetchone()
                    if not head:
                        return self.err("销售出库单不存在", 404)
                    items = conn.execute("SELECT * FROM sales_order_items WHERE sales_order_id=?", (oid,)).fetchall()
                return self.ok({"header": dict(head), "items": [dict(i) for i in items]})

            if path == "/api/inventory/movements":
                with closing(get_conn()) as conn:
                    rows = conn.execute(
                        """
                        SELECT m.*, p.product_code, p.name AS product_name
                        FROM inventory_movements m
                        JOIN products p ON p.id=m.product_id
                        ORDER BY m.id DESC
                        """
                    ).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/inventory/summary":
                with closing(get_conn()) as conn:
                    rows = conn.execute(
                        """
                        SELECT
                          p.id AS product_id,
                          p.product_code,
                          p.name,
                          p.spec,
                          p.unit,
                          p.safety_stock,
                          COALESCE(SUM(CASE WHEN m.movement_type IN ('PURCHASE_IN','ADJUST_IN') THEN m.quantity ELSE 0 END), 0) AS total_in,
                          COALESCE(SUM(CASE WHEN m.movement_type IN ('SALES_OUT','ADJUST_OUT') THEN m.quantity ELSE 0 END), 0) AS total_out
                        FROM products p
                        LEFT JOIN inventory_movements m ON m.product_id = p.id
                        GROUP BY p.id
                        ORDER BY p.id DESC
                        """
                    ).fetchall()
                data = []
                for r in rows:
                    d = dict(r)
                    d["on_hand"] = float(d["total_in"] - d["total_out"])
                    d["stock_status"] = "LOW" if d["on_hand"] < d["safety_stock"] else "OK"
                    data.append(d)
                return self.ok(data)

            # V1占位
            if path == "/api/shipments":
                return self.ok([])

            return self.err("Not Found", 404)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = parse_json_body(self)

            if path == "/api/products":
                now = now_iso()
                with closing(get_conn()) as conn:
                    conn.execute(
                        """
                        INSERT INTO products(product_code,name,spec,unit,hs_code,customs_name,material,origin_country,
                          qty_per_carton,carton_length,carton_width,carton_height,net_weight,gross_weight,safety_stock,is_active,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            must_str(data, "product_code"),
                            must_str(data, "name"),
                            data.get("spec", ""),
                            data.get("unit", "PCS"),
                            data.get("hs_code", ""),
                            data.get("customs_name", ""),
                            data.get("material", ""),
                            data.get("origin_country", "CN"),
                            to_num(data.get("qty_per_carton", 0), "qty_per_carton", 0),
                            to_num(data.get("carton_length", 0), "carton_length", 0),
                            to_num(data.get("carton_width", 0), "carton_width", 0),
                            to_num(data.get("carton_height", 0), "carton_height", 0),
                            to_num(data.get("net_weight", 0), "net_weight", 0),
                            to_num(data.get("gross_weight", 0), "gross_weight", 0),
                            to_num(data.get("safety_stock", 0), "safety_stock", 0),
                            int(data.get("is_active", 1)),
                            now,
                            now,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "商品创建成功"})

            if path == "/api/customers":
                with closing(get_conn()) as conn:
                    conn.execute(
                        "INSERT INTO customers(code,name,country,currency,trade_term,default_port,payment_term,contact,phone,email,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            must_str(data, "code"),
                            must_str(data, "name"),
                            data.get("country", ""),
                            data.get("currency", "USD"),
                            data.get("trade_term", ""),
                            data.get("default_port", ""),
                            data.get("payment_term", ""),
                            data.get("contact", ""),
                            data.get("phone", ""),
                            data.get("email", ""),
                            data.get("note", ""),
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "客户创建成功"})

            if path == "/api/suppliers":
                with closing(get_conn()) as conn:
                    conn.execute(
                        "INSERT INTO suppliers(code,name,country,currency,payment_term,tax_scheme,contact,phone,email,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            must_str(data, "code"),
                            must_str(data, "name"),
                            data.get("country", ""),
                            data.get("currency", "USD"),
                            data.get("payment_term", ""),
                            data.get("tax_scheme", ""),
                            data.get("contact", ""),
                            data.get("phone", ""),
                            data.get("email", ""),
                            data.get("note", ""),
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "供应商创建成功"})

            if path == "/api/purchases":
                items = data.get("items", [])
                if not isinstance(items, list) or not items:
                    raise ValueError("items 必须是非空数组")
                now = now_iso()
                with closing(get_conn()) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO purchase_orders(purchase_no,supplier_id,currency,eta,port,payment_term,transport_mode,status,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            must_str(data, "purchase_no"),
                            int(data.get("supplier_id")),
                            data.get("currency", "USD"),
                            data.get("eta", ""),
                            data.get("port", ""),
                            data.get("payment_term", ""),
                            data.get("transport_mode", ""),
                            data.get("status", "CONFIRMED"),
                            data.get("note", ""),
                            now,
                        ),
                    )
                    po_id = cur.lastrowid

                    for it in items:
                        product_id = int(it.get("product_id"))
                        qty = to_num(it.get("quantity"), "quantity", 0.0001)
                        unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                        cur.execute(
                            "INSERT INTO purchase_order_items(purchase_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_count,line_note) VALUES(?,?,?,?,?,?,?,?)",
                            (
                                po_id,
                                product_id,
                                it.get("spec_snapshot", ""),
                                it.get("unit", "PCS"),
                                qty,
                                unit_price,
                                to_num(it.get("carton_count", 0), "carton_count", 0),
                                it.get("line_note", ""),
                            ),
                        )
                        # 统一规则：quantity 一律正数，方向由 movement_type 决定
                        cur.execute(
                            "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                product_id,
                                "PURCHASE_IN",
                                "PURCHASE",
                                po_id,
                                qty,
                                unit_price,
                                now,
                                f"采购入库 {data.get('purchase_no','')}",
                                now,
                            ),
                        )
                    conn.commit()
                return self.ok({"message": "采购单创建成功", "id": po_id})

            # /api/orders 语义：销售出库单
            if path == "/api/orders":
                items = data.get("items", [])
                if not isinstance(items, list) or not items:
                    raise ValueError("items 必须是非空数组")
                now = now_iso()
                with closing(get_conn()) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO sales_orders(sales_no,customer_id,currency,port,etd,payment_term,transport_mode,shipping_mark,status,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            must_str(data, "sales_no"),
                            int(data.get("customer_id")),
                            data.get("currency", "USD"),
                            data.get("port", ""),
                            data.get("etd", ""),
                            data.get("payment_term", ""),
                            data.get("transport_mode", ""),
                            data.get("shipping_mark", ""),
                            data.get("status", "CONFIRMED"),
                            data.get("note", ""),
                            now,
                        ),
                    )
                    so_id = cur.lastrowid

                    for it in items:
                        product_id = int(it.get("product_id"))
                        qty = to_num(it.get("quantity"), "quantity", 0.0001)
                        unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                        available = stock_available(conn, product_id)
                        if qty > available:
                            conn.rollback()
                            return self.err(f"product_id={product_id} 库存不足，available={available}", 400)

                        cur.execute(
                            "INSERT INTO sales_order_items(sales_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_no,line_note) VALUES(?,?,?,?,?,?,?,?)",
                            (
                                so_id,
                                product_id,
                                it.get("spec_snapshot", ""),
                                it.get("unit", "PCS"),
                                qty,
                                unit_price,
                                it.get("carton_no", ""),
                                it.get("line_note", ""),
                            ),
                        )
                        cur.execute(
                            "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                product_id,
                                "SALES_OUT",
                                "SALES",
                                so_id,
                                qty,  # 正数
                                unit_price,
                                now,
                                f"销售出库 {data.get('sales_no','')}",
                                now,
                            ),
                        )
                    conn.commit()
                return self.ok({"message": "销售出库单创建成功", "id": so_id})

            if path == "/api/inventory/adjust":
                now = now_iso()
                direction = must_str(data, "direction").upper()
                if direction not in ("IN", "OUT"):
                    raise ValueError("direction 必须是 IN 或 OUT")
                movement_type = "ADJUST_IN" if direction == "IN" else "ADJUST_OUT"
                with closing(get_conn()) as conn:
                    conn.execute(
                        "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            int(data.get("product_id")),
                            movement_type,
                            "MANUAL",
                            None,
                            to_num(data.get("quantity"), "quantity", 0.0001),
                            to_num(data.get("unit_cost", 0), "unit_cost", 0),
                            now,
                            data.get("note", ""),
                            now,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "库存调整成功"})

            return self.err("Not Found", 404)
        except sqlite3.IntegrityError as exc:
            return self.err(f"数据约束错误: {exc}", 400)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = parse_json_body(self)

            if path.startswith("/api/products/"):
                pid = int(path.split("/")[-1])
                now = now_iso()
                with closing(get_conn()) as conn:
                    conn.execute(
                        """
                        UPDATE products
                        SET product_code=?,name=?,spec=?,unit=?,hs_code=?,customs_name=?,material=?,origin_country=?,
                            qty_per_carton=?,carton_length=?,carton_width=?,carton_height=?,net_weight=?,gross_weight=?,
                            safety_stock=?,is_active=?,updated_at=?
                        WHERE id=?
                        """,
                        (
                            must_str(data, "product_code"),
                            must_str(data, "name"),
                            data.get("spec", ""),
                            data.get("unit", "PCS"),
                            data.get("hs_code", ""),
                            data.get("customs_name", ""),
                            data.get("material", ""),
                            data.get("origin_country", "CN"),
                            to_num(data.get("qty_per_carton", 0), "qty_per_carton", 0),
                            to_num(data.get("carton_length", 0), "carton_length", 0),
                            to_num(data.get("carton_width", 0), "carton_width", 0),
                            to_num(data.get("carton_height", 0), "carton_height", 0),
                            to_num(data.get("net_weight", 0), "net_weight", 0),
                            to_num(data.get("gross_weight", 0), "gross_weight", 0),
                            to_num(data.get("safety_stock", 0), "safety_stock", 0),
                            int(data.get("is_active", 1)),
                            now,
                            pid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "商品更新成功"})

            if path.startswith("/api/customers/"):
                cid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        "UPDATE customers SET code=?,name=?,country=?,currency=?,trade_term=?,default_port=?,payment_term=?,contact=?,phone=?,email=?,note=? WHERE id=?",
                        (
                            must_str(data, "code"),
                            must_str(data, "name"),
                            data.get("country", ""),
                            data.get("currency", "USD"),
                            data.get("trade_term", ""),
                            data.get("default_port", ""),
                            data.get("payment_term", ""),
                            data.get("contact", ""),
                            data.get("phone", ""),
                            data.get("email", ""),
                            data.get("note", ""),
                            cid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "客户更新成功"})

            if path.startswith("/api/suppliers/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        "UPDATE suppliers SET code=?,name=?,country=?,currency=?,payment_term=?,tax_scheme=?,contact=?,phone=?,email=?,note=? WHERE id=?",
                        (
                            must_str(data, "code"),
                            must_str(data, "name"),
                            data.get("country", ""),
                            data.get("currency", "USD"),
                            data.get("payment_term", ""),
                            data.get("tax_scheme", ""),
                            data.get("contact", ""),
                            data.get("phone", ""),
                            data.get("email", ""),
                            data.get("note", ""),
                            sid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "供应商更新成功"})

            if path.startswith("/api/purchases/"):
                pid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        "UPDATE purchase_orders SET currency=?,eta=?,port=?,payment_term=?,transport_mode=?,status=?,note=? WHERE id=?",
                        (
                            data.get("currency", "USD"),
                            data.get("eta", ""),
                            data.get("port", ""),
                            data.get("payment_term", ""),
                            data.get("transport_mode", ""),
                            data.get("status", "CONFIRMED"),
                            data.get("note", ""),
                            pid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "采购单更新成功"})

            if path.startswith("/api/orders/"):
                oid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        "UPDATE sales_orders SET currency=?,port=?,etd=?,payment_term=?,transport_mode=?,shipping_mark=?,status=?,note=? WHERE id=?",
                        (
                            data.get("currency", "USD"),
                            data.get("port", ""),
                            data.get("etd", ""),
                            data.get("payment_term", ""),
                            data.get("transport_mode", ""),
                            data.get("shipping_mark", ""),
                            data.get("status", "CONFIRMED"),
                            data.get("note", ""),
                            oid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "销售出库单更新成功"})

            return self.err("Not Found", 404)
        except sqlite3.IntegrityError as exc:
            return self.err(f"数据约束错误: {exc}", 400)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"WM backend running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
