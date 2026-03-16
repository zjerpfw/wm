const API = "http://127.0.0.1:8000";
const out = (data) => {
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
};

async function call(url, options = {}) {
  try {
    const res = await fetch(`${API}${url}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json();
    out(data);
  } catch (err) {
    out({ error: String(err) });
  }
}

async function createProduct() {
  const payload = {
    sku: document.getElementById("p_sku").value,
    category_name: document.getElementById("p_category").value,
    category_hs_code: document.getElementById("p_cat_hs").value,
    color: document.getElementById("p_color").value,
    size: document.getElementById("p_size").value,
    default_packing_qty: 50,
    carton_length_cm: 60,
    carton_width_cm: 40,
    carton_height_cm: 35,
    standard_gross_weight_kg: 12,
    standard_net_weight_kg: 10,
    customer_hs_code: "6109100000",
    customs_cn_name: document.getElementById("p_category").value || "未命名类别",
  };
  await call("/api/products", { method: "POST", body: JSON.stringify(payload) });
}

async function receiveStock() {
  await call("/api/inventory/receipt", {
    method: "POST",
    body: JSON.stringify({
      sku: document.getElementById("r_sku").value,
      qty: Number(document.getElementById("r_qty").value),
      reference_no: document.getElementById("r_ref").value,
    }),
  });
}

async function createOrder() {
  await call("/api/orders", {
    method: "POST",
    body: JSON.stringify({
      customer_name: document.getElementById("o_customer").value,
      customer_po: document.getElementById("o_po").value,
      lines: JSON.parse(document.getElementById("o_lines").value || "[]"),
    }),
  });
}

async function createShipment() {
  await call("/api/shipments", {
    method: "POST",
    body: JSON.stringify({
      order_id: Number(document.getElementById("s_order_id").value),
      shipment_no: document.getElementById("s_no").value,
      boxes: JSON.parse(document.getElementById("s_boxes").value || "[]"),
    }),
  });
}

async function queryInventory() {
  const sku = document.getElementById("q_sku").value;
  await call(`/api/inventory/summary/${encodeURIComponent(sku)}`);
}

window.createProduct = createProduct;
window.receiveStock = receiveStock;
window.createOrder = createOrder;
window.createShipment = createShipment;
window.queryInventory = queryInventory;
