from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

def resolve_db_path() -> Path:
    # source mode: /repo/backend/wm.db
    src_candidate = Path(__file__).resolve().parents[2] / "backend" / "wm.db"
    if src_candidate.parent.exists():
        return src_candidate
    # packaged mode (.pyz): fallback to current working directory
    return Path.cwd() / "wm.db"


DB_PATH = resolve_db_path()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn:
        conn.executescript(
            """
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


def require_positive_number(data: dict[str, Any], key: str, num_type: type = int) -> float | int:
    val = data.get(key)
    if not isinstance(val, (int, float)):
        raise ValueError(f"字段 {key} 必须是数字")
    if val <= 0:
        raise ValueError(f"字段 {key} 必须大于0")
    if num_type is int:
        if int(val) != val:
            raise ValueError(f"字段 {key} 必须是整数")
        return int(val)
    return float(val)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "WMZeroDep/0.2"

    def _set_headers(self, code: int = 200, content_type: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code: int, payload: dict[str, Any] | list[Any]) -> None:
        self._set_headers(code)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length 非法")
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("JSON 格式错误") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers(204)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/health":
                return self._json(200, {"status": "ok"})

            if path == "/api/products":
                with closing(get_conn()) as conn:
                    rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
                return self._json(200, [dict(r) for r in rows])

            if path.startswith("/api/orders/"):
                order_id = int(path.split("/")[-1])
                with closing(get_conn()) as conn:
                    order = conn.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
                    if not order:
                        return self._json(404, {"detail": "订单不存在"})
                    lines = conn.execute(
                        "SELECT sku, ordered_qty, shipped_qty FROM sales_order_lines WHERE order_id = ?",
                        (order_id,),
                    ).fetchall()
                return self._json(200, {"order": dict(order), "lines": [dict(r) for r in lines]})

            if path.startswith("/api/inventory/summary/"):
                sku = unquote(path.split("/api/inventory/summary/", 1)[1])
                with closing(get_conn()) as conn:
                    bal = conn.execute(
                        "SELECT on_hand_qty, shipped_qty FROM inventory_balances WHERE sku = ?", (sku,)
                    ).fetchone()
                    if not bal:
                        return self._json(404, {"detail": "SKU 不存在"})
                    rows = conn.execute(
                        "SELECT SUM(ordered_qty) AS ordered_total, SUM(shipped_qty) AS shipped_total FROM sales_order_lines WHERE sku = ?",
                        (sku,),
                    ).fetchone()
                ordered = int(rows["ordered_total"] or 0)
                shipped_so = int(rows["shipped_total"] or 0)
                return self._json(
                    200,
                    {
                        "sku": sku,
                        "on_hand": bal["on_hand_qty"],
                        "shipped_total": bal["shipped_qty"],
                        "ordered_total": ordered,
                        "remaining_order_qty": ordered - shipped_so,
                    },
                )

            return self._json(404, {"detail": "Not Found"})
        except ValueError:
            return self._json(400, {"detail": "参数错误"})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"detail": f"服务器错误: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        now = datetime.utcnow().isoformat()
        try:
            data = self._read_json()

            if path == "/api/products":
                for k in [
                    "sku",
                    "category_name",
                    "category_hs_code",
                    "color",
                    "size",
                    "customer_hs_code",
                    "customs_cn_name",
                ]:
                    if not data.get(k):
                        return self._json(400, {"detail": f"字段缺失: {k}"})
                default_packing_qty = require_positive_number(data, "default_packing_qty", int)
                carton_length_cm = require_positive_number(data, "carton_length_cm", float)
                carton_width_cm = require_positive_number(data, "carton_width_cm", float)
                carton_height_cm = require_positive_number(data, "carton_height_cm", float)
                standard_gross_weight_kg = require_positive_number(data, "standard_gross_weight_kg", float)
                standard_net_weight_kg = require_positive_number(data, "standard_net_weight_kg", float)

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
                                data["sku"],
                                data["category_name"],
                                data["category_hs_code"],
                                data["color"],
                                data["size"],
                                default_packing_qty,
                                carton_length_cm,
                                carton_width_cm,
                                carton_height_cm,
                                standard_gross_weight_kg,
                                standard_net_weight_kg,
                                data["customer_hs_code"],
                                data["customs_cn_name"],
                            ),
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO inventory_balances (sku, on_hand_qty, shipped_qty) VALUES (?, 0, 0)",
                            (data["sku"],),
                        )
                        conn.commit()
                    except sqlite3.IntegrityError as exc:
                        return self._json(400, {"detail": f"商品创建失败: {exc}"})
                return self._json(200, {"message": "商品创建成功", "sku": data["sku"]})

            if path == "/api/inventory/receipt":
                sku = data.get("sku")
                reference_no = data.get("reference_no")
                qty = require_positive_number(data, "qty", int)
                if not sku or not reference_no:
                    return self._json(400, {"detail": "字段缺失: sku/reference_no"})

                with closing(get_conn()) as conn:
                    product = conn.execute("SELECT sku FROM products WHERE sku = ?", (sku,)).fetchone()
                    if not product:
                        return self._json(404, {"detail": "SKU 不存在"})
                    conn.execute(
                        "UPDATE inventory_balances SET on_hand_qty = on_hand_qty + ? WHERE sku = ?",
                        (qty, sku),
                    )
                    conn.execute(
                        "INSERT INTO inventory_ledger (sku, event_type, qty_change, reference_no, created_at) VALUES (?, 'RECEIPT', ?, ?, ?)",
                        (sku, qty, reference_no, now),
                    )
                    conn.commit()
                return self._json(200, {"message": "入库成功", "sku": sku, "qty": qty})

            if path == "/api/orders":
                customer_name = data.get("customer_name")
                customer_po = data.get("customer_po")
                lines = data.get("lines", [])
                if not customer_name or not customer_po:
                    return self._json(400, {"detail": "字段缺失: customer_name/customer_po"})
                if not isinstance(lines, list) or len(lines) == 0:
                    return self._json(400, {"detail": "lines 必须是非空数组"})

                with closing(get_conn()) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO sales_orders (customer_name, customer_po, created_at) VALUES (?, ?, ?)",
                        (customer_name, customer_po, now),
                    )
                    order_id = cur.lastrowid

                    for line in lines:
                        if not isinstance(line, dict):
                            conn.rollback()
                            return self._json(400, {"detail": "line 格式错误"})
                        sku = line.get("sku")
                        if not sku:
                            conn.rollback()
                            return self._json(400, {"detail": "line 缺少 sku"})
                        qty = require_positive_number(line, "qty", int)
                        exists = conn.execute("SELECT sku FROM products WHERE sku = ?", (sku,)).fetchone()
                        if not exists:
                            conn.rollback()
                            return self._json(404, {"detail": f"SKU 不存在: {sku}"})
                        cur.execute(
                            "INSERT INTO sales_order_lines (order_id, sku, ordered_qty, shipped_qty) VALUES (?, ?, ?, 0)",
                            (order_id, sku, qty),
                        )
                    conn.commit()
                return self._json(200, {"message": "订单创建成功", "order_id": order_id})

            if path == "/api/shipments":
                order_id = require_positive_number(data, "order_id", int)
                shipment_no = data.get("shipment_no")
                boxes = data.get("boxes", [])
                if not shipment_no:
                    return self._json(400, {"detail": "字段缺失: shipment_no"})
                if not isinstance(boxes, list) or len(boxes) == 0:
                    return self._json(400, {"detail": "boxes 必须是非空数组"})

                with closing(get_conn()) as conn:
                    order = conn.execute("SELECT id FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
                    if not order:
                        return self._json(404, {"detail": "订单不存在"})
                    order_lines = conn.execute(
                        "SELECT sku, ordered_qty, shipped_qty FROM sales_order_lines WHERE order_id = ?",
                        (order_id,),
                    ).fetchall()
                    line_map = {
                        row["sku"]: {"ordered": row["ordered_qty"], "shipped": row["shipped_qty"]}
                        for row in order_lines
                    }

                    picked: dict[str, int] = {}
                    total_gross_weight = 0.0
                    total_net_weight = 0.0

                    for box in boxes:
                        if not isinstance(box, dict):
                            return self._json(400, {"detail": "box 格式错误"})
                        box_code = box.get("box_code")
                        if not box_code:
                            return self._json(400, {"detail": "box 缺少 box_code"})
                        gross = require_positive_number(box, "gross_weight_kg", float)
                        net = require_positive_number(box, "net_weight_kg", float)
                        volume = require_positive_number(box, "volume_cbm", float)
                        items = box.get("items", [])
                        if not isinstance(items, list) or len(items) == 0:
                            return self._json(400, {"detail": f"box {box_code} items 必须非空"})

                        total_gross_weight += float(gross)
                        total_net_weight += float(net)

                        for item in items:
                            if not isinstance(item, dict):
                                return self._json(400, {"detail": "item 格式错误"})
                            sku = item.get("sku")
                            if not sku:
                                return self._json(400, {"detail": "item 缺少 sku"})
                            qty = require_positive_number(item, "qty", int)
                            picked[sku] = picked.get(sku, 0) + qty

                    for sku, qty in picked.items():
                        if sku not in line_map:
                            return self._json(400, {"detail": f"SKU {sku} 不在订单中"})
                        remaining = line_map[sku]["ordered"] - line_map[sku]["shipped"]
                        if qty > remaining:
                            return self._json(400, {"detail": f"SKU {sku} 发货超订单剩余"})
                        bal = conn.execute("SELECT on_hand_qty FROM inventory_balances WHERE sku = ?", (sku,)).fetchone()
                        if not bal or bal["on_hand_qty"] < qty:
                            return self._json(400, {"detail": f"SKU {sku} 库存不足"})

                    cur = conn.cursor()
                    try:
                        cur.execute(
                            "INSERT INTO shipments (order_id, shipment_no, created_at) VALUES (?, ?, ?)",
                            (order_id, shipment_no, now),
                        )
                        shipment_id = cur.lastrowid

                        for box in boxes:
                            cur.execute(
                                "INSERT INTO shipment_boxes (shipment_id, box_code, gross_weight_kg, net_weight_kg, volume_cbm) VALUES (?, ?, ?, ?, ?)",
                                (
                                    shipment_id,
                                    box["box_code"],
                                    float(box["gross_weight_kg"]),
                                    float(box["net_weight_kg"]),
                                    float(box["volume_cbm"]),
                                ),
                            )
                            box_id = cur.lastrowid
                            for item in box["items"]:
                                cur.execute(
                                    "INSERT INTO shipment_box_items (box_id, sku, qty) VALUES (?, ?, ?)",
                                    (box_id, item["sku"], int(item["qty"])),
                                )

                        for sku, qty in picked.items():
                            cur.execute(
                                "UPDATE inventory_balances SET on_hand_qty = on_hand_qty - ?, shipped_qty = shipped_qty + ? WHERE sku = ?",
                                (qty, qty, sku),
                            )
                            cur.execute(
                                "UPDATE sales_order_lines SET shipped_qty = shipped_qty + ? WHERE order_id = ? AND sku = ?",
                                (qty, order_id, sku),
                            )
                            cur.execute(
                                "INSERT INTO inventory_ledger (sku, event_type, qty_change, reference_no, created_at) VALUES (?, 'SHIPMENT', ?, ?, ?)",
                                (sku, -qty, shipment_no, now),
                            )
                        conn.commit()
                    except sqlite3.IntegrityError as exc:
                        conn.rollback()
                        return self._json(400, {"detail": f"发货失败: {exc}"})

                return self._json(
                    200,
                    {
                        "message": "发货成功",
                        "shipment_no": shipment_no,
                        "total_gross_weight_kg": round(total_gross_weight, 3),
                        "total_net_weight_kg": round(total_net_weight, 3),
                        "sku_shipped": picked,
                    },
                )

            return self._json(404, {"detail": "Not Found"})
        except ValueError as exc:
            return self._json(400, {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"detail": f"服务器错误: {exc}"})


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    init_db()
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    print(f"WM backend running at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
