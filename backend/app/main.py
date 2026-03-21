from __future__ import annotations

import json
import os
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
    env_path = os.environ.get("WM_DB_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
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


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def ensure_column(conn: sqlite3.Connection, table: str, column_name: str, column_def: str) -> None:
    if column_name not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


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

            CREATE TABLE IF NOT EXISTS shipment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                sales_order_item_id INTEGER,
                product_id INTEGER NOT NULL,
                spec_snapshot TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT 'PCS',
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL DEFAULT 0,
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id),
                FOREIGN KEY (sales_order_item_id) REFERENCES sales_order_items(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_id INTEGER NOT NULL,
                box_no TEXT NOT NULL,
                box_length REAL NOT NULL DEFAULT 0,
                box_width REAL NOT NULL DEFAULT 0,
                box_height REAL NOT NULL DEFAULT 0,
                gross_weight REAL NOT NULL DEFAULT 0,
                net_weight REAL NOT NULL DEFAULT 0,
                volume REAL NOT NULL DEFAULT 0,
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE (shipment_id, box_no),
                FOREIGN KEY (shipment_id) REFERENCES shipments(id)
            );

            CREATE TABLE IF NOT EXISTS shipment_box_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_box_id INTEGER NOT NULL,
                shipment_item_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                qty REAL NOT NULL,
                remark TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (shipment_box_id) REFERENCES shipment_boxes(id),
                FOREIGN KEY (shipment_item_id) REFERENCES shipment_items(id),
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

            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_shipment_items_shipment_id ON shipment_items(shipment_id);
            CREATE INDEX IF NOT EXISTS idx_shipment_boxes_shipment_id ON shipment_boxes(shipment_id);
            CREATE INDEX IF NOT EXISTS idx_shipment_box_items_box_id ON shipment_box_items(shipment_box_id);
            CREATE INDEX IF NOT EXISTS idx_shipment_box_items_shipment_item_id ON shipment_box_items(shipment_item_id);
            """
        )
        ensure_column(conn, "shipment_boxes", "box_length", "box_length REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "shipment_boxes", "box_width", "box_width REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "shipment_boxes", "box_height", "box_height REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "shipment_boxes", "remark", "remark TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "shipment_box_items", "shipment_item_id", "shipment_item_id INTEGER")
        ensure_column(conn, "shipment_box_items", "qty", "qty REAL NOT NULL DEFAULT 0")
        ensure_column(conn, "shipment_box_items", "remark", "remark TEXT NOT NULL DEFAULT ''")
        box_cols = table_columns(conn, "shipment_boxes")
        if "length" in box_cols:
            conn.execute(
                "UPDATE shipment_boxes SET box_length=COALESCE(NULLIF(box_length, 0), length), box_width=COALESCE(NULLIF(box_width, 0), width), box_height=COALESCE(NULLIF(box_height, 0), height)"
            )
        if "note" in box_cols:
            conn.execute("UPDATE shipment_boxes SET remark=CASE WHEN remark='' THEN note ELSE remark END")
        item_cols = table_columns(conn, "shipment_box_items")
        if "quantity" in item_cols:
            conn.execute("UPDATE shipment_box_items SET qty=CASE WHEN qty=0 THEN quantity ELSE qty END")
        if "note" in item_cols:
            conn.execute("UPDATE shipment_box_items SET remark=CASE WHEN remark='' THEN note ELSE remark END")
        conn.execute(
            """
            INSERT OR IGNORE INTO system_settings(setting_key, setting_value, updated_at)
            VALUES('enforce_sales_shipment_limit', '1', ?)
            """,
            (now_iso(),),
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


def ensure_shipment_editable(current_status: str) -> None:
    if current_status == "SAVED":
        raise ValueError("发货单已保存，箱和装箱明细只读")
    if current_status == "VOIDED":
        raise ValueError("已作废发货单不允许修改")


def get_shipment_header(conn: sqlite3.Connection, shipment_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT sh.*, so.sales_no
        FROM shipments sh
        JOIN sales_orders so ON so.id=sh.sales_order_id
        WHERE sh.id=?
        """,
        (shipment_id,),
    ).fetchone()


def get_shipment_totals(conn: sqlite3.Connection, shipment_id: int) -> dict[str, float]:
    row = conn.execute(
        """
        SELECT
          COALESCE(COUNT(*), 0) AS total_boxes,
          COALESCE(SUM(gross_weight), 0) AS total_gross_weight,
          COALESCE(SUM(volume), 0) AS total_volume
        FROM shipment_boxes
        WHERE shipment_id=?
        """,
        (shipment_id,),
    ).fetchone()
    qty_row = conn.execute(
        """
        SELECT COALESCE(SUM(qty), 0) AS total_qty
        FROM shipment_box_items sbi
        JOIN shipment_boxes sb ON sb.id=sbi.shipment_box_id
        WHERE sb.shipment_id=?
        """,
        (shipment_id,),
    ).fetchone()
    return {
        "total_boxes": float(row["total_boxes"]),
        "total_qty": float(qty_row["total_qty"]),
        "total_gross_weight": float(row["total_gross_weight"]),
        "total_volume": float(row["total_volume"]),
    }


def get_shipment_items(conn: sqlite3.Connection, shipment_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          si.*,
          p.product_code,
          p.name AS product_name,
          COALESCE(SUM(sbi.qty), 0) AS boxed_qty
        FROM shipment_items si
        JOIN products p ON p.id=si.product_id
        LEFT JOIN shipment_box_items sbi ON sbi.shipment_item_id=si.id
        WHERE si.shipment_id=?
        GROUP BY si.id
        ORDER BY si.id ASC
        """,
        (shipment_id,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["shipment_qty"] = float(item["quantity"])
        item["boxed_qty"] = float(item["boxed_qty"])
        item["remaining_qty"] = float(item["shipment_qty"] - item["boxed_qty"])
        items.append(item)
    return items


def get_shipment_boxes(conn: sqlite3.Connection, shipment_id: int) -> list[dict[str, Any]]:
    boxes = conn.execute(
        """
        SELECT *
        FROM shipment_boxes
        WHERE shipment_id=?
        ORDER BY CAST(box_no AS INTEGER), id
        """,
        (shipment_id,),
    ).fetchall()
    box_data: list[dict[str, Any]] = []
    for box in boxes:
        items = conn.execute(
            """
            SELECT
              sbi.*,
              si.quantity AS shipment_qty,
              si.unit,
              p.product_code,
              p.name AS product_name
            FROM shipment_box_items sbi
            JOIN shipment_items si ON si.id=sbi.shipment_item_id
            JOIN products p ON p.id=sbi.product_id
            WHERE sbi.shipment_box_id=?
            ORDER BY sbi.id ASC
            """,
            (box["id"],),
        ).fetchall()
        entry = dict(box)
        entry["items"] = [dict(item) for item in items]
        box_data.append(entry)
    return box_data


def setting_enabled(conn: sqlite3.Connection, setting_key: str, default: bool = True) -> bool:
    row = conn.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key=?",
        (setting_key,),
    ).fetchone()
    if not row:
        return default
    return str(row["setting_value"]).strip().lower() not in {"0", "false", "off", "no"}


def set_setting(conn: sqlite3.Connection, setting_key: str, enabled: bool) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT INTO system_settings(setting_key, setting_value, updated_at)
        VALUES(?,?,?)
        ON CONFLICT(setting_key) DO UPDATE SET
          setting_value=excluded.setting_value,
          updated_at=excluded.updated_at
        """,
        (setting_key, "1" if enabled else "0", now),
    )


def get_sales_order_shipping_statuses(
    conn: sqlite3.Connection,
    sales_order_id: int,
    exclude_shipment_id: int | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [sales_order_id]
    shipment_filter = ""
    if exclude_shipment_id is not None:
        shipment_filter = " AND sh.id<>?"
        params.append(exclude_shipment_id)
    params.append(sales_order_id)
    rows = conn.execute(
        f"""
        SELECT
          soi.*,
          p.product_code,
          p.name AS product_name,
          COALESCE(shipped.shipped_qty, 0) AS shipped_qty
        FROM sales_order_items soi
        JOIN products p ON p.id=soi.product_id
        LEFT JOIN (
          SELECT
            si.sales_order_item_id,
            SUM(si.quantity) AS shipped_qty
          FROM shipment_items si
          JOIN shipments sh ON sh.id=si.shipment_id
          WHERE sh.sales_order_id=? AND sh.status<>'VOIDED'{shipment_filter}
          GROUP BY si.sales_order_item_id
        ) shipped ON shipped.sales_order_item_id=soi.id
        WHERE soi.sales_order_id=?
        ORDER BY soi.id ASC
        """,
        params,
    ).fetchall()
    data: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["quantity"] = float(item["quantity"])
        item["unit_price"] = float(item["unit_price"])
        item["shipped_qty"] = float(item["shipped_qty"])
        item["remaining_to_ship"] = max(float(item["quantity"] - item["shipped_qty"]), 0.0)
        data.append(item)
    return data


def build_shipment_create_items(
    conn: sqlite3.Connection,
    sales_order_id: int,
    raw_items: Any,
) -> list[dict[str, Any]]:
    enforce_limit = setting_enabled(conn, "enforce_sales_shipment_limit", True)
    shipping_statuses = get_sales_order_shipping_statuses(conn, sales_order_id)
    item_map = {int(item["id"]): item for item in shipping_statuses}
    if not item_map:
        raise ValueError("销售单明细不存在")

    requested_items: list[dict[str, Any]] = []
    if raw_items is None:
        requested_items = [
            {"sales_order_item_id": int(item["id"]), "quantity": float(item["remaining_to_ship"])}
            for item in shipping_statuses
            if float(item["remaining_to_ship"]) > 1e-9
        ]
    else:
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("发货单 items 不能为空")
        seen_ids: set[int] = set()
        for raw in raw_items:
            sales_order_item_id = int(raw.get("sales_order_item_id"))
            if sales_order_item_id in seen_ids:
                raise ValueError("发货单 items 中销售单明细不能重复")
            seen_ids.add(sales_order_item_id)
            sales_item = item_map.get(sales_order_item_id)
            if not sales_item:
                raise ValueError("发货单 items 中存在无效销售单明细")
            qty = to_num(raw.get("quantity"), "quantity", 0)
            if qty <= 1e-9:
                continue
            requested_items.append({"sales_order_item_id": sales_order_item_id, "quantity": qty})

    if not requested_items:
        if raw_items is not None:
            raise ValueError("发货单必须至少包含一个数量大于 0 的商品")
        raise ValueError("当前销售单已无可发数量")

    shipment_items: list[dict[str, Any]] = []
    for requested in requested_items:
        sales_item = item_map[requested["sales_order_item_id"]]
        qty = float(requested["quantity"])
        remaining_to_ship = float(sales_item["remaining_to_ship"])
        if enforce_limit and qty > remaining_to_ship + 1e-9:
            raise ValueError(f"商品 {sales_item['product_code']} 累计发货数量不能大于销售数量")
        shipment_items.append(
            {
                "sales_order_item_id": int(sales_item["id"]),
                "product_id": int(sales_item["product_id"]),
                "spec_snapshot": sales_item["spec_snapshot"],
                "unit": sales_item["unit"],
                "quantity": qty,
                "unit_price": float(sales_item["unit_price"]),
                "remark": sales_item["line_note"],
            }
        )
    return shipment_items


def validate_shipment_box_item(
    conn: sqlite3.Connection,
    shipment_id: int,
    shipment_item_id: int,
    qty: float,
    exclude_box_item_id: int | None = None,
) -> sqlite3.Row:
    shipment_item = conn.execute(
        """
        SELECT *
        FROM shipment_items
        WHERE id=? AND shipment_id=?
        """,
        (shipment_item_id, shipment_id),
    ).fetchone()
    if not shipment_item:
        raise ValueError("发货明细不存在")
    params: list[Any] = [shipment_item_id]
    sql = "SELECT COALESCE(SUM(qty), 0) AS boxed_qty FROM shipment_box_items WHERE shipment_item_id=?"
    if exclude_box_item_id is not None:
        sql += " AND id<>?"
        params.append(exclude_box_item_id)
    row = conn.execute(sql, params).fetchone()
    boxed_qty = float(row["boxed_qty"])
    shipment_qty = float(shipment_item["quantity"])
    if boxed_qty + qty > shipment_qty + 1e-9:
        raise ValueError("装箱数量累计不能大于发货数量")
    return shipment_item


def shipment_inventory_written(conn: sqlite3.Connection, shipment_id: int, ref_type: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM inventory_movements WHERE ref_type=? AND ref_id=? LIMIT 1",
        (ref_type, shipment_id),
    ).fetchone()
    return row is not None


def apply_shipment_inventory(conn: sqlite3.Connection, shipment_id: int) -> None:
    if shipment_inventory_written(conn, shipment_id, "SHIPMENT"):
        return
    product_rows = conn.execute(
        """
        SELECT product_id, SUM(quantity) AS total_qty
        FROM shipment_items
        WHERE shipment_id=?
        GROUP BY product_id
        """,
        (shipment_id,),
    ).fetchall()
    for row in product_rows:
        available = stock_available(conn, int(row["product_id"]))
        if float(row["total_qty"]) > available + 1e-9:
            raise ValueError(f"商品ID {row['product_id']} 库存不足")
    shipment = get_shipment_header(conn, shipment_id)
    if not shipment:
        raise ValueError("发货单不存在")
    items = conn.execute(
        """
        SELECT *
        FROM shipment_items
        WHERE shipment_id=?
        ORDER BY id ASC
        """,
        (shipment_id,),
    ).fetchall()
    now = now_iso()
    for item in items:
        conn.execute(
            """
            INSERT INTO inventory_movements(
              product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                item["product_id"],
                "SALES_OUT",
                "SHIPMENT",
                shipment_id,
                item["quantity"],
                item["unit_price"],
                now,
                f"发货出库 {shipment['shipment_no']}",
                now,
            ),
        )


def reverse_shipment_inventory(conn: sqlite3.Connection, shipment_id: int) -> None:
    if shipment_inventory_written(conn, shipment_id, "VOID_SHIPMENT"):
        return
    if not shipment_inventory_written(conn, shipment_id, "SHIPMENT"):
        return
    shipment = get_shipment_header(conn, shipment_id)
    if not shipment:
        raise ValueError("发货单不存在")
    items = conn.execute(
        """
        SELECT *
        FROM shipment_items
        WHERE shipment_id=?
        ORDER BY id ASC
        """,
        (shipment_id,),
    ).fetchall()
    now = now_iso()
    for item in items:
        conn.execute(
            """
            INSERT INTO inventory_movements(
              product_id,movement_type,ref_type,ref_id,quantity,unit_cost,movement_date,note,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                item["product_id"],
                "ADJUST_IN",
                "VOID_SHIPMENT",
                shipment_id,
                item["quantity"],
                item["unit_price"],
                now,
                f"作废回冲发货单 {shipment['shipment_no']}",
                now,
            ),
        )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WMV1/1.0.2"

    def _write(self, code: int, payload: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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

            if path == "/api/settings/shipment-limit":
                with closing(get_conn()) as conn:
                    return self.ok(
                        {
                            "enabled": setting_enabled(conn, "enforce_sales_shipment_limit", True),
                        }
                    )

            if path.startswith("/api/orders/"):
                oid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    head = conn.execute(
                        """
                        SELECT o.*, c.name AS customer_name
                        FROM sales_orders o
                        JOIN customers c ON c.id=o.customer_id
                        WHERE o.id=?
                        """,
                        (oid,),
                    ).fetchone()
                    if not head:
                        return self.err("销售单不存在", 404)
                    items = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM sales_order_items WHERE sales_order_id=?",
                        (oid,),
                    ).fetchone()
                    if int(items["cnt"]) == 0:
                        return self.ok({"header": dict(head), "items": []})
                    item_rows = get_sales_order_shipping_statuses(conn, oid)
                return self.ok({"header": dict(head), "items": item_rows})

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
                  (
                    SELECT COALESCE(COUNT(*), 0)
                    FROM shipment_boxes sb
                    WHERE sb.shipment_id=sh.id
                  ) AS total_boxes,
                  (
                    SELECT COALESCE(SUM(sbi.qty), 0)
                    FROM shipment_box_items sbi
                    JOIN shipment_boxes sb ON sb.id=sbi.shipment_box_id
                    WHERE sb.shipment_id=sh.id
                  ) AS total_qty,
                  (
                    SELECT COALESCE(SUM(sb.gross_weight), 0)
                    FROM shipment_boxes sb
                    WHERE sb.shipment_id=sh.id
                  ) AS total_gross_weight,
                  (
                    SELECT COALESCE(SUM(sb.volume), 0)
                    FROM shipment_boxes sb
                    WHERE sb.shipment_id=sh.id
                  ) AS total_volume
                FROM shipments sh
                JOIN sales_orders so ON so.id=sh.sales_order_id
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

            if path.startswith("/api/shipments/") and path.endswith("/summary"):
                sid = int(path.split("/")[-2])
                with closing(get_conn()) as conn:
                    head = get_shipment_header(conn, sid)
                    if not head:
                        return self.err("发货单不存在", 404)
                    return self.ok(
                        {
                            "header": dict(head),
                            "items": get_shipment_items(conn, sid),
                            "totals": get_shipment_totals(conn, sid),
                        }
                    )

            if path.startswith("/api/shipments/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    head = get_shipment_header(conn, sid)
                    if not head:
                        return self.err("发货单不存在", 404)
                    return self.ok(
                        {
                            "header": dict(head),
                            "items": get_shipment_items(conn, sid),
                            "boxes": get_shipment_boxes(conn, sid),
                            "totals": get_shipment_totals(conn, sid),
                        }
                    )

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
                            WHEN m.ref_type IN ('SHIPMENT','VOID_SHIPMENT') THEN sh.shipment_no
                            ELSE ''
                          END AS ref_no
                        FROM inventory_movements m
                        JOIN products p ON p.id=m.product_id
                        LEFT JOIN purchase_orders po ON po.id=m.ref_id
                        LEFT JOIN sales_orders so ON so.id=m.ref_id
                        LEFT JOIN shipments sh ON sh.id=m.ref_id
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
                        cur.execute(
                            "INSERT INTO sales_order_items(sales_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_no,line_note) VALUES(?,?,?,?,?,?,?,?)",
                            (so_id, product_id, it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, it.get("carton_no", ""), it.get("line_note", "")),
                        )
                    conn.commit()
                return self.ok({"message": "销售单创建成功", "id": so_id})

            if path == "/api/shipments":
                sales_order_id = int(data.get("sales_order_id"))
                with closing(get_conn()) as conn:
                    so = conn.execute("SELECT * FROM sales_orders WHERE id=?", (sales_order_id,)).fetchone()
                    if not so:
                        return self.err("销售单不存在", 404)
                    shipment_items = build_shipment_create_items(conn, sales_order_id, data.get("items"))
                    shipment_no = str(data.get("shipment_no", "")).strip() or f"SH-{so['sales_no']}"
                    cur = conn.execute(
                        "INSERT INTO shipments(shipment_no,sales_order_id,status,note,created_at) VALUES(?,?,?,?,?)",
                        (shipment_no, sales_order_id, "DRAFT", data.get("note", ""), now),
                    )
                    shipment_id = cur.lastrowid
                    for item in shipment_items:
                        conn.execute(
                            """
                            INSERT INTO shipment_items(
                              shipment_id,sales_order_item_id,product_id,spec_snapshot,unit,quantity,unit_price,remark,created_at
                            ) VALUES(?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                shipment_id,
                                item["sales_order_item_id"],
                                item["product_id"],
                                item["spec_snapshot"],
                                item["unit"],
                                item["quantity"],
                                item["unit_price"],
                                item["remark"],
                                now,
                            ),
                        )
                    conn.commit()
                return self.ok({"message": "发货单创建成功", "id": shipment_id})

            if path.startswith("/api/shipments/") and path.endswith("/boxes"):
                sid = int(path.split("/")[3])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    box_no = must_str(data, "box_no")
                    gross = to_num(data.get("gross_weight", 0), "gross_weight", 0)
                    net = to_num(data.get("net_weight", 0), "net_weight", 0)
                    length = to_num(data.get("box_length", data.get("length", 0)), "box_length", 0)
                    width = to_num(data.get("box_width", data.get("width", 0)), "box_width", 0)
                    height = to_num(data.get("box_height", data.get("height", 0)), "box_height", 0)
                    volume = to_num(data.get("volume", 0), "volume", 0)
                    cur = conn.execute(
                        """
                        INSERT INTO shipment_boxes(
                          shipment_id,box_no,box_length,box_width,box_height,gross_weight,net_weight,volume,remark,created_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (sid, box_no, length, width, height, gross, net, volume, data.get("remark", data.get("note", "")), now),
                    )
                    conn.commit()
                return self.ok({"message": "箱信息创建成功", "id": cur.lastrowid})

            if "/boxes/" in path and path.startswith("/api/shipments/") and path.endswith("/items"):
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    box = conn.execute("SELECT * FROM shipment_boxes WHERE id=? AND shipment_id=?", (box_id, sid)).fetchone()
                    if not box:
                        return self.err("箱不存在", 404)
                    qty = to_num(data.get("qty", data.get("quantity")), "qty", 0.0001)
                    shipment_item_id = int(data.get("shipment_item_id"))
                    shipment_item = validate_shipment_box_item(conn, sid, shipment_item_id, qty)
                    product_id = int(data.get("product_id", shipment_item["product_id"]))
                    if product_id != int(shipment_item["product_id"]):
                        raise ValueError("箱内商品必须与发货明细商品一致")
                    cur = conn.execute(
                        """
                        INSERT INTO shipment_box_items(
                          shipment_box_id,shipment_item_id,product_id,qty,remark,created_at
                        ) VALUES(?,?,?,?,?,?)
                        """,
                        (box_id, shipment_item_id, product_id, qty, data.get("remark", data.get("note", "")), now),
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
            if path == "/api/settings/shipment-limit":
                enabled = bool(data.get("enabled", True))
                with closing(get_conn()) as conn:
                    set_setting(conn, "enforce_sales_shipment_limit", enabled)
                    conn.commit()
                return self.ok({"message": "累计发货数量控制更新成功", "enabled": enabled})

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
                        for it in items:
                            qty = to_num(it.get("quantity"), "quantity", 0.0001)
                            unit_price = to_num(it.get("unit_price", 0), "unit_price", 0)
                            product_id = int(it.get("product_id"))
                            conn.execute(
                                "INSERT INTO sales_order_items(sales_order_id,product_id,spec_snapshot,unit,quantity,unit_price,carton_no,line_note) VALUES(?,?,?,?,?,?,?,?)",
                                (oid, product_id, it.get("spec_snapshot", ""), it.get("unit", "PCS"), qty, unit_price, it.get("carton_no", ""), it.get("line_note", "")),
                            )

                    new_status = validate_doc_status(data.get("status", current_status))
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

            if path.startswith("/api/shipments/") and "/boxes/" in path and "/items/" in path:
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                item_id = int(parts[7])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    box_item = conn.execute(
                        """
                        SELECT sbi.*
                        FROM shipment_box_items sbi
                        JOIN shipment_boxes sb ON sb.id=sbi.shipment_box_id
                        WHERE sbi.id=? AND sbi.shipment_box_id=? AND sb.shipment_id=?
                        """,
                        (item_id, box_id, sid),
                    ).fetchone()
                    if not box_item:
                        return self.err("箱内商品不存在", 404)
                    shipment_item_id = int(data.get("shipment_item_id", box_item["shipment_item_id"]))
                    qty = to_num(data.get("qty", box_item["qty"]), "qty", 0.0001)
                    shipment_item = validate_shipment_box_item(conn, sid, shipment_item_id, qty, item_id)
                    product_id = int(data.get("product_id", shipment_item["product_id"]))
                    if product_id != int(shipment_item["product_id"]):
                        raise ValueError("箱内商品必须与发货明细商品一致")
                    conn.execute(
                        """
                        UPDATE shipment_box_items
                        SET shipment_item_id=?, product_id=?, qty=?, remark=?
                        WHERE id=?
                        """,
                        (
                            shipment_item_id,
                            product_id,
                            qty,
                            data.get("remark", box_item["remark"]),
                            item_id,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "箱内商品更新成功"})

            if path.startswith("/api/shipments/") and path.endswith("/boxes"):
                return self.err("接口不存在", 404)

            if path.startswith("/api/shipments/") and "/boxes/" in path:
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    box = conn.execute(
                        "SELECT * FROM shipment_boxes WHERE id=? AND shipment_id=?",
                        (box_id, sid),
                    ).fetchone()
                    if not box:
                        return self.err("箱不存在", 404)
                    conn.execute(
                        """
                        UPDATE shipment_boxes
                        SET box_no=?, box_length=?, box_width=?, box_height=?, gross_weight=?, net_weight=?, volume=?, remark=?
                        WHERE id=?
                        """,
                        (
                            must_str(data, "box_no"),
                            to_num(data.get("box_length", box["box_length"]), "box_length", 0),
                            to_num(data.get("box_width", box["box_width"]), "box_width", 0),
                            to_num(data.get("box_height", box["box_height"]), "box_height", 0),
                            to_num(data.get("gross_weight", box["gross_weight"]), "gross_weight", 0),
                            to_num(data.get("net_weight", box["net_weight"]), "net_weight", 0),
                            to_num(data.get("volume", box["volume"]), "volume", 0),
                            data.get("remark", box["remark"]),
                            box_id,
                        ),
                    )
                    conn.commit()
                return self.ok({"message": "箱信息更新成功"})

            if path.startswith("/api/shipments/"):
                sid = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    current = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not current:
                        return self.err("发货单不存在", 404)
                    current_status = str(current["status"])
                    if current_status == "VOIDED":
                        raise ValueError("已作废发货单不允许修改")
                    new_status = validate_doc_status(data.get("status", current_status))
                    if current_status == "SAVED" and new_status == "DRAFT":
                        raise ValueError("已保存发货单不允许改回草稿")
                    if current_status == "DRAFT" and new_status == "SAVED":
                        apply_shipment_inventory(conn, sid)
                    if current_status == "SAVED" and new_status == "VOIDED":
                        reverse_shipment_inventory(conn, sid)
                    conn.execute(
                        "UPDATE shipments SET shipment_no=?, status=?, note=? WHERE id=?",
                        (
                            str(data.get("shipment_no", current["shipment_no"])).strip() or current["shipment_no"],
                            new_status,
                            data.get("note", current["note"]),
                            sid,
                        ),
                    )
                    conn.commit()
                message = "发货单更新成功"
                if current_status == "DRAFT" and new_status == "SAVED":
                    message = "发货单已保存并完成扣库存"
                if current_status == "SAVED" and new_status == "VOIDED":
                    message = "发货单已作废并完成库存回补"
                return self.ok({"message": message})

            return self.err("接口不存在", 404)
        except sqlite3.IntegrityError as exc:
            m = str(exc)
            if "products.product_code" in m:
                return self.err("商品编码已存在", 400)
            if "customers.code" in m:
                return self.err("客户编码已存在", 400)
            if "suppliers.code" in m:
                return self.err("供应商编码已存在", 400)
            if "shipments.shipment_no" in m:
                return self.err("发货单号已存在", 400)
            if "shipment_boxes.shipment_id, shipment_boxes.box_no" in m:
                return self.err("同一发货单下箱号已存在", 400)
            return self.err("数据约束错误", 400)
        except Exception as exc:  # noqa: BLE001
            return self.err(str(exc), 400)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/shipments/") and "/boxes/" in path and "/items/" in path:
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                item_id = int(parts[7])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    deleted = conn.execute(
                        """
                        DELETE FROM shipment_box_items
                        WHERE id=? AND shipment_box_id=? AND shipment_box_id IN (
                          SELECT id FROM shipment_boxes WHERE id=? AND shipment_id=?
                        )
                        """,
                        (item_id, box_id, box_id, sid),
                    )
                    if deleted.rowcount == 0:
                        return self.err("箱内商品不存在", 404)
                    conn.commit()
                return self.ok({"message": "箱内商品删除成功"})

            if path.startswith("/api/shipments/") and "/boxes/" in path:
                parts = path.split("/")
                sid = int(parts[3])
                box_id = int(parts[5])
                with closing(get_conn()) as conn:
                    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (sid,)).fetchone()
                    if not shipment:
                        return self.err("发货单不存在", 404)
                    ensure_shipment_editable(str(shipment["status"]))
                    exists = conn.execute(
                        "SELECT 1 FROM shipment_boxes WHERE id=? AND shipment_id=?",
                        (box_id, sid),
                    ).fetchone()
                    if not exists:
                        return self.err("箱不存在", 404)
                    item_exists = conn.execute(
                        "SELECT 1 FROM shipment_box_items WHERE shipment_box_id=? LIMIT 1",
                        (box_id,),
                    ).fetchone()
                    if item_exists:
                        raise ValueError("箱内已有商品，不能直接删除非空箱")
                    conn.execute("DELETE FROM shipment_boxes WHERE id=? AND shipment_id=?", (box_id, sid))
                    conn.commit()
                return self.ok({"message": "箱删除成功"})

            return self.err("接口不存在", 404)
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
