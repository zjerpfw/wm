const API = "http://127.0.0.1:8000";

function setResult(data) {
  const el = document.getElementById("result");
  if (el) el.textContent = JSON.stringify(data, null, 2);
}

async function api(url, options = {}) {
  const res = await fetch(`${API}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  setResult(data);
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function renderTable(elId, columns, rows) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!rows || rows.length === 0) {
    el.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  const h = columns.map((c) => `<th>${c}</th>`).join("");
  const b = rows
    .map((r) => `<tr>${columns.map((c) => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`)
    .join("");
  el.innerHTML = `<table><thead><tr>${h}</tr></thead><tbody>${b}</tbody></table>`;
}

async function fetchCustomers() { return api('/api/customers'); }
async function fetchProducts() { return api('/api/products'); }
async function fetchOrders() { return api('/api/orders'); }
async function fetchShipments() { return api('/api/shipments'); }

function fillSelect(selectId, rows, valueKey, labelKey) {
  const el = document.getElementById(selectId);
  if (!el) return;
  const previous = el.value;
  el.innerHTML = '<option value="">-- 请选择 --</option>';
  rows.forEach((r) => {
    const op = document.createElement('option');
    op.value = r[valueKey];
    op.textContent = r[labelKey];
    el.appendChild(op);
  });
  if ([...el.options].some((o) => o.value === previous)) el.value = previous;
}

window.WM = {
  api,
  renderTable,
  fetchCustomers,
  fetchProducts,
  fetchOrders,
  fetchShipments,
  fillSelect,
};
