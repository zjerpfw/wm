from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DOC_STATUSES = {"DRAFT", "SAVED", "VOIDED"}


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
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def must_str(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"字段缺失: {key}")
    return value


def to_num(v: Any, field: str, min_val: float | None = None) -> float:
    try:
        value = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"字段 {field} 必须是数字") from exc
    if min_val is not None and value < min_val:
        raise ValueError(f"字段 {field} 必须 >= {min_val}")
    return value


def validate_doc_status(status: str) -> str:
    s = status.upper()
    if s not in DOC_STATUSES:
        raise ValueError("单据状态必须是 DRAFT / SAVED / VOIDED")
    return s


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
                status TEXT NOT NULL DEFAULT 'DRAFT',
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
                status TEXT NOT NULL DEFAULT 'DRAFT',
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

            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_no TEXT NOT NULL UNIQUE,
                sales_order_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (sales_order_id) REFERENCES sales_orders(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                box_no TEXT NOT NULL,
                gross_weight REAL NOT NULL DEFAULT 0,
                net_weight REAL NOT NULL DEFAULT 0,
                length REAL NOT NULL DEFAULT 0,
                width REAL NOT NULL DEFAULT 0,
                height REAL NOT NULL DEFAULT 0,
                volume REAL NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (shipment_id, box_no),
                FOREIGN KEY (shipment_id) REFERENCES shipments(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_box_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_box_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (shipment_box_id) REFERENCES shipment_boxes(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS inventory_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                ref_type TEXT NOT NULL,
                ref_id INTEGER,
                quantity REAL NOT NULL,
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


def ensure_doc_editable(current_status: str) -> None:
    if current_status == "VOIDED":
        raise ValueError("已作废单据不允许修改")


def ensure_saved_items_readonly(current_status: str, payload: dict[str, Any]) -> None:
    if current_status == "SAVED" and "items" in payload:
        raise ValueError("单据已保存，明细只读，不允许修改商品/数量/单价")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WMV1/1.0.2"

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
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)
        keyword = str(q.get("q", [""])[0]).strip()
        status = str(q.get("status", [""])[0]).strip().upper()

        try:
            if path == "/health":
                return self.ok({"status": "ok"})

            if path == "/api/products":
                sql = "SELECT * FROM products"
                args: list[Any] = []
                if keyword:
                    sql += " WHERE product_code LIKE ? OR name LIKE ? OR spec LIKE ?"
                    args += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
                sql += " ORDER BY id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/customers":
                sql = "SELECT * FROM customers"
                args = []
                if keyword:
                    sql += " WHERE code LIKE ? OR name LIKE ?"
                    args += [f"%{keyword}%", f"%{keyword}%"]
                sql += " ORDER BY id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/suppliers":
                sql = "SELECT * FROM suppliers"
                args = []
                if keyword:
                    sql += " WHERE code LIKE ? OR name LIKE ?"
                    args += [f"%{keyword}%", f"%{keyword}%"]
                sql += " ORDER BY id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/purchases":
                sql = "SELECT p.*, s.name AS supplier_name FROM purchase_orders p JOIN suppliers s ON s.id=p.supplier_id"
                args = []
                cond = []
                if keyword:
                    cond.append("(p.purchase_no LIKE ? OR s.name LIKE ?)")
                    args += [f"%{keyword}%", f"%{keyword}%"]
                if status:
                    cond.append("p.status=?")
                    args.append(status)
                if cond:
                    sql += " WHERE " + " AND ".join(cond)
                sql += " ORDER BY p.id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/orders":
                sql = "SELECT o.*, c.name AS customer_name FROM sales_orders o JOIN customers c ON c.id=o.customer_id"
                args = []
                cond = []
                if keyword:
                    cond.append("(o.sales_no LIKE ? OR c.name LIKE ?)")
                    args += [f"%{keyword}%", f"%{keyword}%"]
                if status:
                    cond.append("o.status=?")
                    args.append(status)
                if cond:
                    sql += " WHERE " + " AND ".join(cond)
                sql += " ORDER BY o.id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path == "/api/shipments":
                sql = """
                SELECT
                  sh.id,
                  sh.shipment_no,
                  sh.sales_order_id,
                  sh.status,
                  sh.note,
                  sh.created_at,
                  so.sales_no,
                  COALESCE(COUNT(DISTINCT sb.id), 0) AS total_boxes,
                  COALESCE(SUM(sbi.quantity), 0) AS total_qty,
                  COALESCE(SUM(sb.gross_weight), 0) AS total_gross_weight,
                  COALESCE(SUM(sb.volume), 0) AS total_volume
                FROM shipments sh
                JOIN sales_orders so ON so.id=sh.sales_order_id
                LEFT JOIN shipment_boxes sb ON sb.shipment_id=sh.id
                LEFT JOIN shipment_box_items sbi ON sbi.shipment_box_id=sb.id
                """
                args = []
                cond = []
                if keyword:
                    cond.append("(sh.shipment_no LIKE ? OR so.sales_no LIKE ?)")
                    args += [f"%{keyword}%", f"%{keyword}%"]
                if cond:
                    sql += " WHERE " + " AND ".join(cond)
                sql += " GROUP BY sh.id ORDER BY sh.id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                return self.ok([dict(r) for r in rows])

            if path.startswith("/api/shipments/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    head = conn.execute(
                        "SELECT sh.*, so.sales_no FROM shipments sh JOIN sales_orders so ON so.id=sh.sales_order_id WHERE sh.id=?",
                        (sid,),
                    ).fetchone()
                    if not head:
                        return self.err("发货单不存在", 404)
                    boxes = conn.execute(
                        "SELECT * FROM shipment_boxes WHERE shipment_id=? ORDER BY id ASC",
                        (sid,),
                    ).fetchall()
                    box_data = []
                    for b in boxes:
                        items = conn.execute(
                            """
                            SELECT sbi.*, p.product_code, p.name AS product_name
                            FROM shipment_box_items sbi
                            JOIN products p ON p.id=sbi.product_id
                            WHERE sbi.shipment_box_id=?
                            ORDER BY sbi.id ASC
                            """,
                            (b["id"],),
                        ).fetchall()
                        d = dict(b)
                        d["items"] = [dict(i) for i in items]
                        box_data.append(d)
                    totals = conn.execute(
                        """
                        SELECT
                          COALESCE(COUNT(DISTINCT sb.id), 0) AS total_boxes,
                          COALESCE(SUM(sbi.quantity), 0) AS total_qty,
                          COALESCE(SUM(sb.gross_weight), 0) AS total_gross_weight,
                          COALESCE(SUM(sb.volume), 0) AS total_volume
                        FROM shipment_boxes sb
                        LEFT JOIN shipment_box_items sbi ON sbi.shipment_box_id=sb.id
                        WHERE sb.shipment_id=?
                        """,
                        (sid,),
                    ).fetchone()
                return self.ok({"header": dict(head), "boxes": box_data, "totals": dict(totals)})

            if path == "/api/inventory/summary":
                sql = """
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
                """
                args = []
                if keyword:
                    sql += " WHERE p.product_code LIKE ? OR p.name LIKE ?"
                    args += [f"%{keyword}%", f"%{keyword}%"]
                sql += " GROUP BY p.id ORDER BY p.id DESC"
                with closing(get_conn()) as conn:
                    rows = conn.execute(sql, args).fetchall()
                data = []
                for r in rows:
                    d = dict(r)
                    d["on_hand"] = float(d["total_in"] - d["total_out"])
                    d["stock_status"] = "低库存" if d["on_hand"] < d["safety_stock"] else "正常"
                    data.append(d)
                return self.ok(data)

            if path == "/api/inventory/movements":
                with closing(get_conn()) as conn:
                    rows = conn.execute(
                        """
                        SELECT
                          m.*,
                          p.product_code,
                          p.name AS product_name,
                          CASE
                            WHEN m.ref_type IN ('PURCHASE','VOID_PURCHASE') THEN po.purchase_no
                            WHEN m.ref_type IN ('SALES','VOID_SALES') THEN so.sales_no
                            ELSE ''
                          END AS ref_no
                        FROM inventory_movements m
                        JOIN products p ON p.id=m.product_id
                        LEFT JOIN purchase_orders po ON po.id=m.ref_id
                        LEFT JOIN sales_orders so ON so.id=m.ref_id
                        ORDER BY m.id DESC
                        """
                    ).fetchall()
                return self.ok([dict(r) for r in rows])

            return self.err("接口不存在", 404)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = parse_json_body(self)
            now = now_iso()

            if path == "/api/products":
                with closing(get_conn()) as conn:
                    conn.execute(
                        """
                        INSERT INTO products(product_code,name,spec,unit,hs_code,customs_name,material,origin_country,qty_per_carton,carton_length,carton_width,carton_height,net_weight,gross_weight,safety_stock,is_active,created_at,updated_at)
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
                    raise ValueError("采购单 items 不能为空")
                status = validate_doc_status(data.get("status", "DRAFT"))
                if status == "VOIDED":
                    raise ValueError("新建采购单不允许直接设为 VOIDED")
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
                            status,
                            data.get("note", ""),
                            now,
                        ),
                    )
                    po_id = cur.lastrowid
                    for it in items:
                        qty = to_num(it.get("quantity"), "quantity", 0.0001)
                        unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                        cur.execute(
                            "INSERT INTO purchase_order_items(purchase_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_count,line_note) VALUES(?,?,?,?,?,?,?,?)",
                            (po_id, int(it.get("product_id")), it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, to_num(it.get("carton_count", 0), "carton_count", 0), it.get("line_note", "")),
                        )
                        cur.execute(
                            "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (int(it.get("product_id")), "PURCHASE_IN", "PURCHASE", po_id, qty, unit_price, now, f"采购入库 {data.get('purchase_no', '')}", now),
                        )
                    conn.commit()
                return self.ok({"message": "采购单创建成功", "id": po_id})

            if path == "/api/orders":
                items = data.get("items", [])
                if not isinstance(items, list) or not items:
                    raise ValueError("销售单 items 不能为空")
                status = validate_doc_status(data.get("status", "DRAFT"))
                if status == "VOIDED":
                    raise ValueError("新建销售单不允许直接设为 VOIDED")
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
                            status,
                            data.get("note", ""),
                            now,
                        ),
                    )
                    so_id = cur.lastrowid
                    for it in items:
                        product_id = int(it.get("product_id"))
                        qty = to_num(it.get("quantity"), "quantity", 0.0001)
                        unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                        if qty > stock_available(conn, product_id):
                            raise ValueError(f"商品ID {product_id} 库存不足")
                        cur.execute(
                            "INSERT INTO sales_order_items(sales_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_no,line_note) VALUES(?,?,?,?,?,?,?,?)",
                            (so_id, product_id, it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, it.get("carton_no", ""), it.get("line_note", "")),
                        )
                        cur.execute(
                            "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (product_id, "SALES_OUT", "SALES", so_id, qty, unit_price, now, f"销售出库 {data.get('sales_no', '')}", now),
                        )
                    conn.commit()
                return self.ok({"message": "销售单创建成功", "id": so_id})

            if path == "/api/shipments":
                sales_order_id = int(data.get("sales_order_id"))
                with closing(get_conn()) as conn:
                    so = conn.execute("SELECT * FROM sales_orders WHERE id=?", (sales_order_id,)).fetchone()
                    if not so:
                        return self.err("销售单不存在", 404)
                    shipment_no = str(data.get("shipment_no", "")).strip() or f"SH-{so['sales_no']}"
                    cur = conn.execute(
                        "INSERT INTO shipments(shipment_no,sales_order_id,status,note,created_at) VALUES(?,?,?,?,?)",
                        (shipment_no, sales_order_id, "DRAFT", data.get("note", ""), now),
                    )
                    conn.commit()
                return self.ok({"message": "发货单创建成功", "id": cur.lastrowid})

            if path.startswith("/api/shipments/") and path.endswith("/boxes"):
                sid = int(path.split("/")[3])
                with closing(get_conn()) as conn:
                    existed = conn.execute("SELECT id FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not existed:
                        return self.err("发货单不存在", 404)
                    box_no = must_str(data, "box_no")
                    gross = to_num(data.get("gross_weight", 0), "gross_weight", 0)
                    net = to_num(data.get("net_weight", 0), "net_weight", 0)
                    length = to_num(data.get("length", 0), "length", 0)
                    width = to_num(data.get("width", 0), "width", 0)
                    height = to_num(data.get("height", 0), "height", 0)
                    volume = to_num(data.get("volume", 0), "volume", 0)
                    cur = conn.execute(
                        "INSERT INTO shipment_boxes(shipment_id,box_no,gross_weight,net_weight,length,width,height,volume,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (sid, box_no, gross, net, length, width, height, volume, data.get("note", ""), now),
                    )
                    conn.commit()
                return self.ok({"message": "箱信息创建成功", "id": cur.lastrowid})

            if "/boxes/" in path and path.startswith("/api/shipments/") and path.endswith("/items"):
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                with closing(get_conn()) as conn:
                    box = conn.execute("SELECT * FROM shipment_boxes WHERE id=? AND shipment_id=?", (box_id, sid)).fetchone()
                    if not box:
                        return self.err("箱不存在", 404)
                    qty = to_num(data.get("quantity"), "quantity", 0.0001)
                    product_id = int(data.get("product_id"))
                    cur = conn.execute(
                        "INSERT INTO shipment_box_items(shipment_box_id,product_id,quantity,note,created_at) VALUES(?,?,?,?,?)",
                        (box_id, product_id, qty, data.get("note", ""), now),
                    )
                    conn.commit()
                return self.ok({"message": "箱商品创建成功", "id": cur.lastrowid})

            if path == "/api/inventory/adjust":
                direction = must_str(data, "direction").upper()
                if direction not in ("IN", "OUT"):
                    raise ValueError("direction 必须是 IN 或 OUT")
                with closing(get_conn()) as conn:
                    conn.execute(
                        "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            int(data.get("product_id")),
                            "ADJUST_IN" if direction == "IN" else "ADJUST_OUT",
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

            return self.err("接口不存在", 404)
        except sqlite3.IntegrityError as exc:
            m = str(exc)
            if "products.product_code" in m:
                return self.err("商品编码已存在", 400)
            if "customers.code" in m:
                return self.err("客户编码已存在", 400)
            if "suppliers.code" in m:
                return self.err("供应商编码已存在", 400)
            if "purchase_orders.purchase_no" in m:
                return self.err("采购单号已存在", 400)
            if "sales_orders.sales_no" in m:
                return self.err("销售单号已存在", 400)
            if "shipments.shipment_no" in m:
                return self.err("发货单号已存在", 400)
            if "shipment_boxes.shipment_id, shipment_boxes.box_no" in m:
                return self.err("同一发货单下箱号已存在", 400)
            return self.err("数据约束错误", 400)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = parse_json_body(self)
            if path.startswith("/api/products/"):
                pid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        """
                        UPDATE products SET product_code=?,name=?,spec=?,unit=?,hs_code=?,customs_name=?,material=?,origin_country=?,qty_per_carton=?,carton_length=?,carton_width=?,carton_height=?,net_weight=?,gross_weight=?,safety_stock=?,is_active=?,updated_at=? WHERE id=?
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
                            now_iso(),
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
                        (must_str(data, "code"), must_str(data, "name"), data.get("country", ""), data.get("currency", "USD"), data.get("trade_term", ""), data.get("default_port", ""), data.get("payment_term", ""), data.get("contact", ""), data.get("phone", ""), data.get("email", ""), data.get("note", ""), cid),
                    )
                    conn.commit()
                return self.ok({"message": "客户更新成功"})

            if path.startswith("/api/suppliers/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    conn.execute(
                        "UPDATE suppliers SET code=?,name=?,country=?,currency=?,payment_term=?,tax_scheme=?,contact=?,phone=?,email=?,note=? WHERE id=?",
                        (must_str(data, "code"), must_str(data, "name"), data.get("country", ""), data.get("currency", "USD"), data.get("payment_term", ""), data.get("tax_scheme", ""), data.get("contact", ""), data.get("phone", ""), data.get("email", ""), data.get("note", ""), sid),
                    )
                    conn.commit()
                return self.ok({"message": "供应商更新成功"})

            if path.startswith("/api/purchases/"):
                pid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    current = conn.execute("SELECT * FROM purchase_orders WHERE id=?", (pid,)).fetchone()
                    if not current:
                        return self.err("采购单不存在", 404)
                    current_status = str(current["status"])
                    ensure_doc_editable(current_status)
                    ensure_saved_items_readonly(current_status, data)

                    items = data.get("items")
                    if items is not None:
                        if not isinstance(items, list) or not items:
                            raise ValueError("采购单 items 不能为空")
                        conn.execute("DELETE FROM purchase_order_items WHERE purchase_order_id=?", (pid,))
                        conn.execute("DELETE FROM inventory_movements WHERE ref_type='PURCHASE' AND ref_id=?", (pid,))
                        for it in items:
                            qty = to_num(it.get("quantity"), "quantity", 0.0001)
                            unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                            product_id = int(it.get("product_id"))
                            conn.execute(
                                "INSERT INTO purchase_order_items(purchase_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_count,line_note) VALUES(?,?,?,?,?,?,?,?)",
                                (pid, product_id, it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, to_num(it.get("carton_count", 0), "carton_count", 0), it.get("line_note", "")),
                            )
                            conn.execute(
                                "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (product_id, "PURCHASE_IN", "PURCHASE", pid, qty, unit_price, now_iso(), f"采购入库 {current['purchase_no']}", now_iso()),
                            )

                    new_status = validate_doc_status(data.get("status", current_status))
                    if new_status == "VOIDED" and current_status != "VOIDED":
                        existed = conn.execute(
                            "SELECT 1 FROM inventory_movements WHERE ref_type='VOID_PURCHASE' AND ref_id=? LIMIT 1",
                            (pid,),
                        ).fetchone()
                        if not existed:
                            po_items = conn.execute(
                                "SELECT product_id, quantity, unit_price FROM purchase_order_items WHERE purchase_order_id=?",
                                (pid,),
                            ).fetchall()
                            now = now_iso()
                            for it in po_items:
                                conn.execute(
                                    "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (it["product_id"], "ADJUST_OUT", "VOID_PURCHASE", pid, it["quantity"], it["unit_price"], now, f"作废冲销采购单 {current['purchase_no']}", now),
                                )

                    conn.execute(
                        "UPDATE purchase_orders SET status=?,currency=?,eta=?,port=?,payment_term=?,transport_mode=?,note=? WHERE id=?",
                        (
                            new_status,
                            data.get("currency", current["currency"]),
                            data.get("eta", current["eta"]),
                            data.get("port", current["port"]),
                            data.get("payment_term", current["payment_term"]),
                            data.get("transport_mode", current["transport_mode"]),
                            data.get("note", current["note"]),
                            pid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "采购单更新成功"})

            if path.startswith("/api/orders/"):
                oid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    current = conn.execute("SELECT * FROM sales_orders WHERE id=?", (oid,)).fetchone()
                    if not current:
                        return self.err("销售单不存在", 404)
                    current_status = str(current["status"])
                    ensure_doc_editable(current_status)
                    ensure_saved_items_readonly(current_status, data)

                    items = data.get("items")
                    if items is not None:
                        if not isinstance(items, list) or not items:
                            raise ValueError("销售单 items 不能为空")
                        conn.execute("DELETE FROM sales_order_items WHERE sales_order_id=?", (oid,))
                        conn.execute("DELETE FROM inventory_movements WHERE ref_type='SALES' AND ref_id=?", (oid,))
                        for it in items:
                            qty = to_num(it.get("quantity"), "quantity", 0.0001)
                            unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                            product_id = int(it.get("product_id"))
                            if qty > stock_available(conn, product_id):
                                raise ValueError(f"商品ID {product_id} 库存不足")
                            conn.execute(
                                "INSERT INTO sales_order_items(sales_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_no,line_note) VALUES(?,?,?,?,?,?,?,?)",
                                (oid, product_id, it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, it.get("carton_no", ""), it.get("line_note", "")),
                            )
                            conn.execute(
                                "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (product_id, "SALES_OUT", "SALES", oid, qty, unit_price, now_iso(), f"销售出库 {current['sales_no']}", now_iso()),
                            )

                    new_status = validate_doc_status(data.get("status", current_status))
                    if new_status == "VOIDED" and current_status != "VOIDED":
                        existed = conn.execute(
                            "SELECT 1 FROM inventory_movements WHERE ref_type='VOID_SALES' AND ref_id=? LIMIT 1",
                            (oid,),
                        ).fetchone()
                        if not existed:
                            so_items = conn.execute(
                                "SELECT product_id, quantity, unit_price FROM sales_order_items WHERE sales_order_id=?",
                                (oid,),
                            ).fetchall()
                            now = now_iso()
                            for it in so_items:
                                conn.execute(
                                    "INSERT INTO inventory_movements(product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (it["product_id"], "ADJUST_IN", "VOID_SALES", oid, it["quantity"], it["unit_price"], now, f"作废冲销销售单 {current['sales_no']}", now),
                                )

                    conn.execute(
                        "UPDATE sales_orders SET status=?,currency=?,port=?,etd=?,payment_term=?,transport_mode=?,shipping_mark=?,note=? WHERE id=?",
                        (
                            new_status,
                            data.get("currency", current["currency"]),
                            data.get("port", current["port"]),
                            data.get("etd", current["etd"]),
                            data.get("payment_term", current["payment_term"]),
                            data.get("transport_mode", current["transport_mode"]),
                            data.get("shipping_mark", current["shipping_mark"]),
                            data.get("note", current["note"]),
                            oid,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "销售单更新成功"})

            return self.err("接口不存在", 404)
        except sqlite3.IntegrityError as exc:
            m = str(exc)
            if "products.product_code" in m:
                return self.err("商品编码已存在", 400)
            if "customers.code" in m:
                return self.err("客户编码已存在", 400)
            if "suppliers.code" in m:
                return self.err("供应商编码已存在", 400)
            return self.err("数据约束错误", 400)
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
