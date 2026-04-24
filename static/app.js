// â”€â”€â”€ Formatters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const numFmt = new Intl.NumberFormat("es-AR");

/** Formato corto en millones: $ 1.306 M  |  $ 854 M  |  $ 120 K */
function formatARS(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    const m = value / 1_000_000;
    return "$ " + numFmt.format(Math.round(m)) + " M";
  }
  if (abs >= 1_000) {
    return "$ " + numFmt.format(Math.round(value / 1_000)) + " K";
  }
  return "$ " + numFmt.format(Math.round(value));
}

/** Tick muy corto para ejes: $1.3B / $950M / $120K */
function tickARS(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return "$ " + (value / 1_000_000_000).toFixed(1) + " B";
  if (abs >= 1_000_000) return "$ " + (value / 1_000_000).toFixed(0) + " M";
  if (abs >= 1_000) return "$ " + (value / 1_000).toFixed(0) + " K";
  return "$ " + value.toFixed(0);
}

const yMoneyAxis = { ticks: { callback: tickARS } };
const xMoneyAxis = { beginAtZero: true, ticks: { callback: tickARS } };

/** Y axis for horizontal bars — reserves fixed width so labels don't get cut */
function yLabelAxis(widthPx = 230) {
  return {
    ticks: { font: { size: 11 }, autoSkip: false },
    afterFit(scale) { scale.width = widthPx; },
  };
}

const moneyTooltip = (isHorizontal = false) => ({
  callbacks: {
    label: (ctx) => " " + formatARS(isHorizontal ? ctx.parsed.x : ctx.parsed.y),
  },
});

// â”€â”€â”€ Chart registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const charts = {};

function upsert(key, canvasId, config) {
  if (charts[key]) charts[key].destroy();
  charts[key] = new Chart(document.getElementById(canvasId), config);
}

/* Loading state helpers */
function setLoadingState(isLoading = true) {
  const activeTab = document.querySelector('.tab-pane.active');
  if (!activeTab) return;

  const kpiCards = activeTab.querySelectorAll('.kpi-card');
  const panels = activeTab.querySelectorAll('.panel');
  const canvases = activeTab.querySelectorAll('canvas');

  if (isLoading) {
    kpiCards.forEach(card => {
      card.classList.add('loading');
      const p = card.querySelector('p');
      if (p) p.textContent = '⋯';
    });
    
    panels.forEach(panel => {
      panel.classList.add('loading');
      const canvas = panel.querySelector('canvas');
      if (canvas) {
        canvas.style.opacity = '0.2';
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        panel.appendChild(spinner);
      }
    });
  } else {
    kpiCards.forEach(card => card.classList.remove('loading'));
    panels.forEach(panel => {
      panel.classList.remove('loading');
      const spinner = panel.querySelector('.spinner');
      if (spinner) spinner.remove();
      const canvas = panel.querySelector('canvas');
      if (canvas) canvas.style.opacity = '1';
    });
  }
}

const palette = ["#0077b6", "#00b4d8", "#48cae4", "#90e0ef", "#4f46e5", "#0ea5e9", "#06b6d4", "#3b82f6"];

// â”€â”€â”€ Status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function setStatus(msg, isError = false) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.style.color = isError ? "#dc2626" : "#667085";
}

// â”€â”€â”€ Tab state & cache â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const cache = {};
let activeTab = "ventas";

const PAGE_TITLES = {
  ventas: "Ventas",
  clientes: "Clientes",
  productos: "Productos",
  contabilidad: "Contabilidad",
  crm: "CRM",
};

// â”€â”€â”€ Render functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function renderVentas(data) {
  const { kpis, charts: c } = data;
  document.getElementById("v-kpi-sales").textContent = formatARS(kpis.totalSales || 0);
  document.getElementById("v-kpi-orders").textContent = numFmt.format(kpis.orderCount || 0);
  document.getElementById("v-kpi-ticket").textContent = formatARS(kpis.avgTicket || 0);
  document.getElementById("v-kpi-customers").textContent = numFmt.format(kpis.newCustomers || 0);

  upsert("v-monthly", "v-monthly-chart", {
    type: "line",
    data: {
      labels: c.monthlySales.map((d) => d.label),
      datasets: [{
        label: "Ventas",
        data: c.monthlySales.map((d) => d.value),
        borderColor: "#0077b6",
        backgroundColor: "rgba(0,119,182,0.15)",
        fill: true,
        tension: 0.35,
        pointRadius: 5,
        pointHoverRadius: 7,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: yMoneyAxis },
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("v-category", "v-category-chart", {
    type: "doughnut",
    data: {
      labels: c.categorySales.map((d) => d.label),
      datasets: [{ data: c.categorySales.map((d) => d.value), backgroundColor: palette }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("v-products", "v-products-chart", {
    type: "bar",
    data: {
      labels: c.topProducts.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.topProducts.map((d) => d.value), backgroundColor: "#48cae4", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis() },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });

  upsert("v-region", "v-region-chart", {
    type: "bar",
    data: {
      labels: c.regionSales.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.regionSales.map((d) => d.value), backgroundColor: "#0077b6", borderRadius: 8 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });
}

function renderClientes(data) {
  const { kpis, charts: c } = data;
  document.getElementById("c-kpi-total").textContent = numFmt.format(kpis.totalCustomers || 0);
  document.getElementById("c-kpi-new").textContent = numFmt.format(kpis.newCustomers || 0);
  document.getElementById("c-kpi-active").textContent = numFmt.format(kpis.customersWithOrders || 0);
  document.getElementById("c-kpi-ticket").textContent = formatARS(kpis.avgTicketPerCustomer || 0);

  upsert("c-monthly", "c-monthly-chart", {
    type: "bar",
    data: {
      labels: c.newCustomersByMonth.map((d) => d.label),
      datasets: [{
        label: "Clientes nuevos",
        data: c.newCustomersByMonth.map((d) => d.value),
        backgroundColor: "#0077b6",
        borderRadius: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } },
    },
  });

  upsert("c-top", "c-top-chart", {
    type: "bar",
    data: {
      labels: c.topCustomers.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.topCustomers.map((d) => d.value), backgroundColor: "#48cae4", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis(200) },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });

  upsert("c-province", "c-province-chart", {
    type: "bar",
    data: {
      labels: c.byProvince.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.byProvince.map((d) => d.value), backgroundColor: "#4f46e5", borderRadius: 8 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });
}

function renderProductos(data) {
  const { kpis, charts: c } = data;
  document.getElementById("p-kpi-unique").textContent = numFmt.format(kpis.uniqueProducts || 0);
  document.getElementById("p-kpi-units").textContent = numFmt.format(kpis.totalUnits || 0);
  document.getElementById("p-kpi-categories").textContent = numFmt.format(kpis.activeCategories || 0);

  upsert("p-amount", "p-amount-chart", {
    type: "bar",
    data: {
      labels: c.topByAmount.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.topByAmount.map((d) => d.value), backgroundColor: "#0077b6", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis() },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });

  upsert("p-qty", "p-qty-chart", {
    type: "bar",
    data: {
      labels: c.topByQty.map((d) => d.label),
      datasets: [{ label: "Unidades", data: c.topByQty.map((d) => d.value), backgroundColor: "#48cae4", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { beginAtZero: true }, y: yLabelAxis() },
    },
  });

  upsert("p-category", "p-category-chart", {
    type: "bar",
    data: {
      labels: c.byCategory.map((d) => d.label),
      datasets: [{ label: "Ventas", data: c.byCategory.map((d) => d.value), backgroundColor: palette, borderRadius: 8 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });
}

function renderContabilidad(data) {
  const { kpis, charts: c } = data;
  document.getElementById("acc-kpi-invoiced").textContent = formatARS(kpis.totalInvoiced || 0);
  document.getElementById("acc-kpi-collected").textContent = formatARS(kpis.totalCollected || 0);
  document.getElementById("acc-kpi-pending").textContent = formatARS(kpis.totalPending || 0);
  document.getElementById("acc-kpi-overdue").textContent = formatARS(kpis.totalOverdue || 0);
  document.getElementById("acc-kpi-payable").textContent = formatARS(kpis.totalPayable || 0);

  upsert("acc-monthly", "acc-monthly-chart", {
    type: "bar",
    data: {
      labels: c.monthlyComparison.map((d) => d.label),
      datasets: [
        {
          label: "Facturado",
          data: c.monthlyComparison.map((d) => d.invoiced),
          backgroundColor: "#0077b6",
          borderRadius: 6,
          order: 2,
        },
        {
          label: "Cobrado",
          data: c.monthlyComparison.map((d) => d.collected),
          backgroundColor: "#22c55e",
          borderRadius: 6,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("acc-status", "acc-status-chart", {
    type: "doughnut",
    data: {
      labels: c.invoiceStatus.map((d) => d.label),
      datasets: [{ data: c.invoiceStatus.map((d) => d.value), backgroundColor: ["#22c55e", "#f59e0b", "#0077b6", "#a855f7", "#94a3b8"] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("acc-debtors", "acc-debtors-chart", {
    type: "bar",
    data: {
      labels: c.topDebtors.map((d) => d.label),
      datasets: [{ label: "Deuda", data: c.topDebtors.map((d) => d.value), backgroundColor: "#f59e0b", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis(200) },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });

  upsert("acc-expenses", "acc-expenses-chart", {
    type: "bar",
    data: {
      labels: c.expensesMonthly.map((d) => d.label),
      datasets: [{ label: "Gastos", data: c.expensesMonthly.map((d) => d.value), backgroundColor: "#ef4444", borderRadius: 6 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });
}

function renderCRM(data) {
  const { kpis, charts: c } = data;
  document.getElementById("crm-kpi-active").textContent = numFmt.format(kpis.totalActive || 0);
  document.getElementById("crm-kpi-revenue").textContent = formatARS(kpis.totalRevenue || 0);
  document.getElementById("crm-kpi-won").textContent = numFmt.format(kpis.wonCount || 0);

  const palette = ["#0077b6","#00b4d8","#48cae4","#90e0ef","#ade8f4","#caf0f8","#023e8a","#0096c7","#0077b6","#48cae4"];

  upsert("crm-monthly", "crm-monthly-chart", {
    type: "bar",
    data: {
      labels: c.newMonthly.map((d) => d.label),
      datasets: [
        {
          label: "Cantidad",
          data: c.newMonthly.map((d) => d.count),
          backgroundColor: "#0077b6",
          borderRadius: 6,
          yAxisID: "yCount",
        },
        {
          label: "Ingreso Esperado",
          data: c.newMonthly.map((d) => d.revenue),
          type: "line",
          borderColor: "#f59e0b",
          backgroundColor: "rgba(245,158,11,0.15)",
          tension: 0.35,
          fill: true,
          yAxisID: "yRevenue",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        yCount: { type: "linear", position: "left", beginAtZero: true, ticks: { stepSize: 1 } },
        yRevenue: { type: "linear", position: "right", beginAtZero: true, ticks: { callback: tickARS }, grid: { drawOnChartArea: false } },
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => ctx.dataset.label === "Ingreso Esperado" ? " " + formatARS(ctx.parsed.y) : ` ${ctx.parsed.y} oportunidades`,
          },
        },
      },
    },
  });

  upsert("crm-stage", "crm-stage-chart", {
    type: "bar",
    data: {
      labels: c.byStage.map((d) => d.label),
      datasets: [
        { label: "Cantidad", data: c.byStage.map((d) => d.count), backgroundColor: palette, borderRadius: 8 },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } }, y: yLabelAxis(180) },
      plugins: {
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const s = c.byStage[ctx.dataIndex];
              return ` ${s.count} opp — ${formatARS(s.revenue)}`;
            },
          },
        },
      },
    },
  });

  upsert("crm-prob", "crm-prob-chart", {
    type: "doughnut",
    data: {
      labels: c.probDistribution.map((d) => d.label),
      datasets: [{ data: c.probDistribution.map((d) => d.value), backgroundColor: ["#94a3b8","#60a5fa","#f59e0b","#0077b6","#22c55e"] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: { callbacks: { label: (ctx) => ` ${ctx.parsed} oportunidades` } } },
    },
  });

  upsert("crm-user", "crm-user-chart", {
    type: "bar",
    data: {
      labels: c.byUser.map((d) => d.label),
      datasets: [{ label: "Ingreso Esperado", data: c.byUser.map((d) => d.revenue), backgroundColor: "#0077b6", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis(180) },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });
}

function renderCompras(data) {
  const { kpis, charts: c } = data;
  document.getElementById("comp-kpi-orders").textContent = numFmt.format(kpis.orderCount || 0);
  document.getElementById("comp-kpi-total").textContent = formatARS(kpis.totalPurchase || 0);
  document.getElementById("comp-kpi-avg").textContent = formatARS(kpis.avgOrder || 0);

  upsert("comp-monthly", "comp-monthly-chart", {
    type: "bar",
    data: {
      labels: c.monthlyPurchase.map((d) => d.label),
      datasets: [{
        label: "Compras",
        data: c.monthlyPurchase.map((d) => d.value),
        backgroundColor: "#f59e0b",
        borderRadius: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("comp-suppliers", "comp-suppliers-chart", {
    type: "bar",
    data: {
      labels: c.topSuppliers.map((d) => d.label),
      datasets: [{ label: "Compras", data: c.topSuppliers.map((d) => d.value), backgroundColor: "#8b5cf6", borderRadius: 8 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: { x: xMoneyAxis, y: yLabelAxis(200) },
      plugins: { tooltip: moneyTooltip(true) },
    },
  });

  upsert("comp-category", "comp-category-chart", {
    type: "bar",
    data: {
      labels: c.byCategory.map((d) => d.label),
      datasets: [{ label: "Compras", data: c.byCategory.map((d) => d.value), backgroundColor: "#06b6d4", borderRadius: 8 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, ...yMoneyAxis } },
      plugins: { tooltip: moneyTooltip() },
    },
  });

  upsert("comp-status", "comp-status-chart", {
    type: "doughnut",
    data: {
      labels: c.orderStatus.map((d) => d.label),
      datasets: [{ data: c.orderStatus.map((d) => d.value), backgroundColor: ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#94a3b8"] }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { tooltip: moneyTooltip() },
    },
  });
}

const RENDERERS = {
  ventas: renderVentas,
  clientes: renderClientes,
  productos: renderProductos,
  compras: renderCompras,
  contabilidad: renderContabilidad,
  crm: renderCRM,
};

// â”€â”€â”€ Data loading â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function loadTab(tab, dateFrom, dateTo, forceReload = false) {
  const cacheKey = `${tab}__${dateFrom}__${dateTo}`;
  if (!forceReload && cache[cacheKey]) {
    setLoadingState(false);
    RENDERERS[tab](cache[cacheKey]);
    setStatus(`Rango: ${dateFrom} a ${dateTo}`);
    return;
  }

  setStatus("Cargando datos...");
  setLoadingState(true);
  try {
    const res = await fetch(`/api/${tab}?from=${dateFrom}&to=${dateTo}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al cargar datos");
    cache[cacheKey] = data;
    setLoadingState(false);
    RENDERERS[tab](data);
    setStatus(`✓ Rango: ${data.meta.dateFrom} a ${data.meta.dateTo}`);
  } catch (err) {
    setLoadingState(false);
    setStatus(err.message, true);
  }
}

// â”€â”€â”€ Init â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

(function init() {
  const now = new Date();
  const fromInput = document.getElementById("from");
  const toInput = document.getElementById("to");
  const filters = document.getElementById("filters");
  const pageTitle = document.getElementById("page-title");

  fromInput.value = new Date(now.getFullYear(), 0, 1).toISOString().slice(0, 10);
  toInput.value = now.toISOString().slice(0, 10);

  // Tab switching
  document.querySelectorAll(".side-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      if (tab === activeTab) return;

      document.querySelectorAll(".side-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      document.getElementById(`tab-${tab}`).classList.add("active");

      pageTitle.textContent = PAGE_TITLES[tab];
      activeTab = tab;
      loadTab(tab, fromInput.value, toInput.value);
    });
  });

  // Filter submit
  filters.addEventListener("submit", (e) => {
    e.preventDefault();
    // Clear cache for current tab so it reloads
    Object.keys(cache).forEach((k) => {
      if (k.startsWith(activeTab + "__")) delete cache[k];
    });
    loadTab(activeTab, fromInput.value, toInput.value, true);
  });

  // Initial load
  loadTab("ventas", fromInput.value, toInput.value);
})();
