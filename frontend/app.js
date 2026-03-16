const API = "http://127.0.0.1:8000";
const out = (data) => {
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
};

async function call(url, options = {}) {
  const res = await fetch(`${API}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  out(data);
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function v(id) { return document.getElementById(id).value.trim(); }
function n(id) { return Number(document.getElementById(id).value); }

function fillProductExample() {
  document.getElementById("p_sku").value = "SKU-RED-M";
  document.getElementById("p_category").value = "T恤";
  document.getElementById("p_cat_hs").value = "610910";
  document.getElementById("p_color").value = "RED";
  document.getElementById("p_size").value = "M";
  document.getElementById("p_pack").value = "50";
  document.getElementById("p_len").value = "60";
  document.getElementById("p_wid").value = "40";
  document.getElementById("p_hei").value = "35";
  document.getElementById("p_gross").value = "12";
  document.getElementById("p_net").value = "10";
  document.getElementById("p_customer_hs").value = "6109100000";
  document.getElementById("p_cn").value = "针织T恤";
}

function fillReceiptExample() {
  document.getElementById("r_sku").value = "SKU-RED-M";
  document.getElementById("r_qty").value = "100";
  document.getElementById("r_ref").value = "GRN-001";
}

function fillOrderExample() {
  document.getElementById("o_customer").value = "ACME LTD";
  document.getElementById("o_po").value = "PO-2026-001";
  document.getElementById("o_lines").value = "SKU-RED-M,100";
}

function fillShipmentExample() {
  document.getElementById("s_order_id").value = "1";
  document.getElementById("s_no").value = "SHIP-001";
  document.getElementById("s_boxes").value = "BOX-001,12,10,0.07,SKU-RED-M,50";
}

function parseOrderLines(text) {
  return text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean)
    .map((line) => {
      const [sku, qty] = line.split(",").map((s) => s.trim());
      return { sku, qty: Number(qty) };
    });
}

function parseBoxes(text) {
  const map = new Map();
  text
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean)
    .forEach((line) => {
      const [box_code, gross, net, volume, sku, qty] = line.split(",").map((s) => s.trim());
      if (!map.has(box_code)) {
        map.set(box_code, {
          box_code,
          gross_weight_kg: Number(gross),
          net_weight_kg: Number(net),
          volume_cbm: Number(volume),
          items: [],
        });
      }
      map.get(box_code).items.push({ sku, qty: Number(qty) });
    });
  return Array.from(map.values());
}

async function createProduct() {
  try {
    await call("/api/products", {
      method: "POST",
      body: JSON.stringify({
        sku: v("p_sku"),
        category_name: v("p_category"),
        category_hs_code: v("p_cat_hs"),
        color: v("p_color"),
        size: v("p_size"),
        default_packing_qty: n("p_pack"),
        carton_length_cm: n("p_len"),
        carton_width_cm: n("p_wid"),
        carton_height_cm: n("p_hei"),
        standard_gross_weight_kg: n("p_gross"),
        standard_net_weight_kg: n("p_net"),
        customer_hs_code: v("p_customer_hs"),
        customs_cn_name: v("p_cn"),
      }),
    });
    await refreshProducts();
  } catch (e) {}
}

async function receiveStock() {
  try {
    await call("/api/inventory/receipt", {
      method: "POST",
      body: JSON.stringify({ sku: v("r_sku"), qty: n("r_qty"), reference_no: v("r_ref") }),
    });
  } catch (e) {}
}

async function createOrder() {
  try {
    await call("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        customer_name: v("o_customer"),
        customer_po: v("o_po"),
        lines: parseOrderLines(v("o_lines")),
      }),
    });
    await refreshOrders();
  } catch (e) {}
}

async function createShipment() {
  try {
    await call("/api/shipments", {
      method: "POST",
      body: JSON.stringify({
        order_id: n("s_order_id"),
        shipment_no: v("s_no"),
        boxes: parseBoxes(v("s_boxes")),
      }),
    });
    await refreshShipments();
  } catch (e) {}
}

async function queryInventory() {
  try { await call(`/api/inventory/summary/${encodeURIComponent(v("q_sku"))}`); } catch (e) {}
}

function renderSimpleTable(elId, cols, rows) {
  const el = document.getElementById(elId);
  if (!rows || rows.length === 0) {
    el.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  const head = cols.map((c) => `<th>${c}</th>`).join("");
  const body = rows
    .map((r) => `<tr>${cols.map((c) => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`)
    .join("");
  el.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function refreshProducts() {
  try {
    const rows = await call("/api/products");
    renderSimpleTable("productsTable", ["sku", "category_name", "color", "size", "default_packing_qty", "customer_hs_code"], rows);
  } catch (e) {}
}

async function refreshOrders() {
  try {
    const rows = await call("/api/orders");
    renderSimpleTable("ordersTable", ["id", "customer_name", "customer_po", "created_at"], rows);
  } catch (e) {}
}

async function refreshShipments() {
  try {
    const rows = await call("/api/shipments");
    renderSimpleTable("shipmentsTable", ["id", "shipment_no", "order_id", "box_count", "total_gross_weight_kg", "total_net_weight_kg"], rows);
  } catch (e) {}
}

window.fillProductExample = fillProductExample;
window.fillReceiptExample = fillReceiptExample;
window.fillOrderExample = fillOrderExample;
window.fillShipmentExample = fillShipmentExample;
window.createProduct = createProduct;
window.receiveStock = receiveStock;
window.createOrder = createOrder;
window.createShipment = createShipment;
window.queryInventory = queryInventory;
window.refreshProducts = refreshProducts;
window.refreshOrders = refreshOrders;
window.refreshShipments = refreshShipments;

fillProductExample();
fillReceiptExample();
fillOrderExample();
fillShipmentExample();
refreshProducts();
refreshOrders();
refreshShipments();
