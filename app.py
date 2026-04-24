from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request


load_dotenv()


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class OdooClient:
    def __init__(self) -> None:
        self.url = env("ODOO_URL").rstrip("/")
        self.db = env("ODOO_DB")
        self.user = env("ODOO_USER")
        self.password = os.getenv("ODOO_API_KEY") or env("ODOO_PASSWORD")
        self.timeout = 30
        self.uid: int | None = None

    def _jsonrpc(self, service: str, method: str, *args: Any) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": service,
                "method": method,
                "args": list(args),
            },
            "id": int(dt.datetime.now().timestamp() * 1000),
        }

        response = requests.post(
            f"{self.url}/jsonrpc",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            error = data["error"]
            message = error.get("data", {}).get("message") or error.get("message")
            raise RuntimeError(f"Odoo JSON-RPC error: {message}")
        return data.get("result")

    def login(self) -> int:
        if self.uid is not None:
            return self.uid

        uid = self._jsonrpc("common", "login", self.db, self.user, self.password)
        if not uid:
            raise RuntimeError("Odoo login failed. Verify ODOO_DB/ODOO_USER/ODOO_PASSWORD or API key.")
        self.uid = int(uid)
        return self.uid

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = self.login()
        return self._jsonrpc(
            "object",
            "execute_kw",
            self.db,
            uid,
            self.password,
            model,
            method,
            args or [],
            kwargs or {},
        )


def parse_date(value: str | None, default: dt.date) -> dt.date:
    if not value:
        return default
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def month_label(value: str | None) -> str:
    if not value:
        return "N/A"
    try:
        parsed = dt.datetime.fromisoformat(value)
        return parsed.strftime("%b %Y")
    except ValueError:
        return value


def clean_product_name(name: str) -> str:
    """Remove SKU code prefix and packaging suffix, keep core product name."""
    cleaned = re.sub(r"^\[.*?\]\s*", "", str(name)).strip()
    # Strip packaging info: everything from " CAJA", " FRASCO", " BOLSA", etc.
    for stop in (" CAJA", " FRASCO", " BOLSA", " DISPLAY", " PACK"):
        idx = cleaned.upper().find(stop)
        if idx > 4:
            cleaned = cleaned[:idx].strip()
            break
    # Final hard cap at word boundary
    if len(cleaned) > 38:
        truncated = cleaned[:38]
        last_space = truncated.rfind(" ")
        cleaned = truncated[:last_space] if last_space > 10 else truncated
    return cleaned


def get_dashboard_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    from_dt = f"{date_from.isoformat()} 00:00:00"
    to_dt = f"{date_to.isoformat()} 23:59:59"

    sale_domain = [
        ["state", "in", ["sale", "done"]],
        ["date_order", ">=", from_dt],
        ["date_order", "<=", to_dt],
    ]

    summary = client.execute_kw(
        "sale.order",
        "read_group",
        args=[sale_domain, ["amount_total:sum"], []],
        kwargs={"lazy": False},
    )
    bucket = summary[0] if summary else {}
    total_sales = float(bucket.get("amount_total", 0.0) or 0.0)
    order_count = int(bucket.get("__count", 0) or 0)
    avg_ticket = total_sales / order_count if order_count else 0.0

    new_customers = client.execute_kw(
        "res.partner",
        "search_count",
        args=[
            [
                ["customer_rank", ">", 0],
                ["create_date", ">=", from_dt],
                ["create_date", "<=", to_dt],
            ]
        ],
    )

    monthly_sales_raw = client.execute_kw(
        "sale.order",
        "read_group",
        args=[sale_domain, ["amount_total:sum"], ["date_order:month"]],
        kwargs={"orderby": "date_order asc", "lazy": False},
    )
    monthly_sales = [
        {
            "label": month_label(
                item.get("date_order:month") or item.get("date_order")
            ),
            "value": float(item.get("amount_total", 0.0) or 0.0),
        }
        for item in monthly_sales_raw
    ]

    line_domain = [
        ["order_id.state", "in", ["sale", "done"]],
        ["order_id.date_order", ">=", from_dt],
        ["order_id.date_order", "<=", to_dt],
    ]
    product_sales_raw = client.execute_kw(
        "sale.order.line",
        "read_group",
        args=[line_domain, ["price_total:sum", "product_id"], ["product_id"]],
        kwargs={"orderby": "price_total desc", "lazy": False},
    )

    product_sales = []
    for item in product_sales_raw:
        product = item.get("product_id")
        if not product:
            continue
        product_sales.append(
            {
                "product_id": int(product[0]),
                "name": product[1],
                "value": float(item.get("price_total", 0.0) or 0.0),
            }
        )

    top_products = sorted(product_sales, key=lambda x: x["value"], reverse=True)[:5]

    category_sales: dict[str, float] = {}
    if product_sales:
        product_ids = [item["product_id"] for item in product_sales]
        products = client.execute_kw(
            "product.product",
            "read",
            args=[product_ids],
            kwargs={"fields": ["id", "categ_id"]},
        )

        category_map: dict[int, str] = {}
        category_ids = sorted(
            {
                int(prod["categ_id"][0])
                for prod in products
                if prod.get("categ_id") and isinstance(prod.get("categ_id"), list)
            }
        )

        if category_ids:
            categories = client.execute_kw(
                "product.category",
                "read",
                args=[category_ids],
                kwargs={"fields": ["id", "name"]},
            )
            category_map = {int(cat["id"]): str(cat["name"]) for cat in categories}

        product_to_category: dict[int, str] = {}
        for prod in products:
            product_id = int(prod["id"])
            categ = prod.get("categ_id")
            if categ and isinstance(categ, list):
                category_name = category_map.get(int(categ[0]), "Sin categoria")
            else:
                category_name = "Sin categoria"
            product_to_category[product_id] = category_name

        for item in product_sales:
            category_name = product_to_category.get(item["product_id"], "Sin categoria")
            category_sales[category_name] = category_sales.get(category_name, 0.0) + item["value"]

    category_sales_rows = [
        {"label": label, "value": value}
        for label, value in sorted(category_sales.items(), key=lambda x: x[1], reverse=True)[:6]
    ]

    partner_sales_raw = client.execute_kw(
        "sale.order",
        "read_group",
        args=[sale_domain, ["amount_total:sum", "partner_id"], ["partner_id"]],
        kwargs={"lazy": False},
    )

    region_sales: dict[str, float] = {}
    partner_ids = []
    for item in partner_sales_raw:
        partner = item.get("partner_id")
        if partner:
            partner_ids.append(int(partner[0]))

    partner_location: dict[int, str] = {}
    if partner_ids:
        partners = client.execute_kw(
            "res.partner",
            "read",
            args=[partner_ids],
            kwargs={"fields": ["id", "state_id", "country_id"]},
        )

        state_ids = sorted(
            {
                int(p["state_id"][0])
                for p in partners
                if p.get("state_id") and isinstance(p.get("state_id"), list)
            }
        )
        state_name: dict[int, str] = {}
        if state_ids:
            states = client.execute_kw(
                "res.country.state",
                "read",
                args=[state_ids],
                kwargs={"fields": ["id", "name"]},
            )
            state_name = {int(s["id"]): str(s["name"]) for s in states}

        for p in partners:
            partner_id = int(p["id"])
            if p.get("state_id") and isinstance(p["state_id"], list):
                partner_location[partner_id] = state_name.get(int(p["state_id"][0]), "Sin region")
            elif p.get("country_id") and isinstance(p["country_id"], list):
                partner_location[partner_id] = str(p["country_id"][1])
            else:
                partner_location[partner_id] = "Sin region"

    for item in partner_sales_raw:
        partner = item.get("partner_id")
        if not partner:
            continue
        partner_id = int(partner[0])
        region = partner_location.get(partner_id, "Sin region")
        region_sales[region] = region_sales.get(region, 0.0) + float(item.get("amount_total", 0.0) or 0.0)

    region_sales_rows = [
        {"label": label, "value": value}
        for label, value in sorted(region_sales.items(), key=lambda x: x[1], reverse=True)[:6]
    ]

    return {
        "kpis": {
            "totalSales": total_sales,
            "orderCount": order_count,
            "avgTicket": avg_ticket,
            "newCustomers": int(new_customers or 0),
        },
        "charts": {
            "monthlySales": monthly_sales,
            "categorySales": category_sales_rows,
            "topProducts": [{"label": clean_product_name(p["name"]), "value": p["value"]} for p in top_products],
            "regionSales": region_sales_rows,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


def get_clientes_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    from_dt = f"{date_from.isoformat()} 00:00:00"
    to_dt = f"{date_to.isoformat()} 23:59:59"

    total_customers = client.execute_kw(
        "res.partner",
        "search_count",
        args=[[["customer_rank", ">", 0]]],
    )

    new_customers = client.execute_kw(
        "res.partner",
        "search_count",
        args=[[["customer_rank", ">", 0], ["create_date", ">=", from_dt], ["create_date", "<=", to_dt]]],
    )

    sale_domain = [
        ["state", "in", ["sale", "done"]],
        ["date_order", ">=", from_dt],
        ["date_order", "<=", to_dt],
    ]

    orders_by_customer = client.execute_kw(
        "sale.order",
        "read_group",
        args=[sale_domain, ["amount_total:sum"], ["partner_id"]],
        kwargs={"lazy": False},
    )

    customers_with_orders = len(orders_by_customer)
    total_orders = sum(int(item.get("__count", 0) or 0) for item in orders_by_customer)
    total_sales_clientes = sum(float(item.get("amount_total", 0) or 0) for item in orders_by_customer)
    avg_ticket_per_customer = total_sales_clientes / customers_with_orders if customers_with_orders else 0.0

    top_customers_raw = sorted(
        orders_by_customer,
        key=lambda x: float(x.get("amount_total", 0) or 0),
        reverse=True,
    )[:10]
    top_customers = [
        {
            "label": item["partner_id"][1] if item.get("partner_id") else "Sin nombre",
            "value": float(item.get("amount_total", 0) or 0),
        }
        for item in top_customers_raw
    ]

    new_customers_monthly_raw = client.execute_kw(
        "res.partner",
        "read_group",
        args=[
            [["customer_rank", ">", 0], ["create_date", ">=", from_dt], ["create_date", "<=", to_dt]],
            [],
            ["create_date:month"],
        ],
        kwargs={"orderby": "create_date asc", "lazy": False},
    )
    new_customers_by_month = [
        {
            "label": month_label(item.get("create_date:month") or item.get("create_date")),
            "value": int(item.get("__count", 0) or 0),
        }
        for item in new_customers_monthly_raw
    ]

    partner_ids = [int(item["partner_id"][0]) for item in orders_by_customer if item.get("partner_id")]
    partner_amounts = {
        int(item["partner_id"][0]): float(item.get("amount_total", 0) or 0)
        for item in orders_by_customer
        if item.get("partner_id")
    }

    province_sales: dict[str, float] = {}
    if partner_ids:
        partners = client.execute_kw(
            "res.partner",
            "read",
            args=[partner_ids],
            kwargs={"fields": ["id", "state_id", "country_id"]},
        )
        state_ids = sorted(
            {int(p["state_id"][0]) for p in partners if p.get("state_id") and isinstance(p["state_id"], list)}
        )
        state_name: dict[int, str] = {}
        if state_ids:
            states = client.execute_kw(
                "res.country.state",
                "read",
                args=[state_ids],
                kwargs={"fields": ["id", "name"]},
            )
            state_name = {int(s["id"]): str(s["name"]) for s in states}

        for p in partners:
            pid = int(p["id"])
            amount = partner_amounts.get(pid, 0.0)
            if p.get("state_id") and isinstance(p["state_id"], list):
                province = state_name.get(int(p["state_id"][0]), "Sin provincia")
            elif p.get("country_id") and isinstance(p["country_id"], list):
                province = str(p["country_id"][1])
            else:
                province = "Sin provincia"
            province_sales[province] = province_sales.get(province, 0.0) + amount

    province_rows = [
        {"label": label, "value": value}
        for label, value in sorted(province_sales.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    return {
        "kpis": {
            "totalCustomers": int(total_customers or 0),
            "newCustomers": int(new_customers or 0),
            "customersWithOrders": customers_with_orders,
            "avgTicketPerCustomer": avg_ticket_per_customer,
        },
        "charts": {
            "newCustomersByMonth": new_customers_by_month,
            "topCustomers": top_customers,
            "byProvince": province_rows,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


def get_productos_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    from_dt = f"{date_from.isoformat()} 00:00:00"
    to_dt = f"{date_to.isoformat()} 23:59:59"

    line_domain = [
        ["order_id.state", "in", ["sale", "done"]],
        ["order_id.date_order", ">=", from_dt],
        ["order_id.date_order", "<=", to_dt],
    ]

    products_raw = client.execute_kw(
        "sale.order.line",
        "read_group",
        args=[line_domain, ["price_total:sum", "product_uom_qty:sum"], ["product_id"]],
        kwargs={"lazy": False},
    )

    unique_products = len(products_raw)
    total_units = sum(float(item.get("product_uom_qty", 0) or 0) for item in products_raw)

    top_by_amount = [
        {
            "label": clean_product_name(item["product_id"][1]) if item.get("product_id") else "Sin nombre",
            "value": float(item.get("price_total", 0) or 0),
        }
        for item in sorted(products_raw, key=lambda x: float(x.get("price_total", 0) or 0), reverse=True)[:10]
    ]

    top_by_qty = [
        {
            "label": clean_product_name(item["product_id"][1]) if item.get("product_id") else "Sin nombre",
            "value": float(item.get("product_uom_qty", 0) or 0),
        }
        for item in sorted(products_raw, key=lambda x: float(x.get("product_uom_qty", 0) or 0), reverse=True)[:10]
    ]

    category_sales: dict[str, float] = {}
    if products_raw:
        product_ids = [int(item["product_id"][0]) for item in products_raw if item.get("product_id")]
        price_map = {
            int(item["product_id"][0]): float(item.get("price_total", 0) or 0)
            for item in products_raw
            if item.get("product_id")
        }

        products = client.execute_kw(
            "product.product",
            "read",
            args=[product_ids],
            kwargs={"fields": ["id", "categ_id"]},
        )
        category_ids = sorted(
            {int(p["categ_id"][0]) for p in products if p.get("categ_id") and isinstance(p["categ_id"], list)}
        )
        category_map: dict[int, str] = {}
        if category_ids:
            categories = client.execute_kw(
                "product.category",
                "read",
                args=[category_ids],
                kwargs={"fields": ["id", "name"]},
            )
            category_map = {int(c["id"]): str(c["name"]) for c in categories}

        for p in products:
            pid = int(p["id"])
            amount = price_map.get(pid, 0.0)
            categ = p.get("categ_id")
            cat_name = (
                category_map.get(int(categ[0]), "Sin categoría")
                if categ and isinstance(categ, list)
                else "Sin categoría"
            )
            category_sales[cat_name] = category_sales.get(cat_name, 0.0) + amount

    active_categories = len(category_sales)
    category_rows = [
        {"label": label, "value": value}
        for label, value in sorted(category_sales.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    return {
        "kpis": {
            "uniqueProducts": unique_products,
            "totalUnits": int(total_units),
            "activeCategories": active_categories,
        },
        "charts": {
            "topByAmount": top_by_amount,
            "topByQty": top_by_qty,
            "byCategory": category_rows,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


def get_contabilidad_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    from_dt = f"{date_from.isoformat()} 00:00:00"
    to_dt = f"{date_to.isoformat()} 23:59:59"
    today = dt.date.today().isoformat()

    # ── Facturas de clientes (out_invoice) ──────────────────────────────────
    inv_domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["invoice_date", ">=", date_from.isoformat()],
        ["invoice_date", "<=", date_to.isoformat()],
    ]

    inv_summary = client.execute_kw(
        "account.move",
        "read_group",
        args=[inv_domain, ["amount_total:sum", "amount_residual:sum"], []],
        kwargs={"lazy": False},
    )
    inv_bucket = inv_summary[0] if inv_summary else {}
    total_invoiced = float(inv_bucket.get("amount_total", 0.0) or 0.0)
    total_pending = float(inv_bucket.get("amount_residual", 0.0) or 0.0)
    total_collected = total_invoiced - total_pending

    # ── Facturas vencidas ────────────────────────────────────────────────────
    overdue_domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["not_paid", "partial"]],
        ["invoice_date_due", "<", today],
    ]
    overdue_summary = client.execute_kw(
        "account.move",
        "read_group",
        args=[overdue_domain, ["amount_residual:sum"], []],
        kwargs={"lazy": False},
    )
    overdue_bucket = overdue_summary[0] if overdue_summary else {}
    total_overdue = float(overdue_bucket.get("amount_residual", 0.0) or 0.0)

    # ── Cuentas a pagar (in_invoice) ─────────────────────────────────────────
    bills_domain = [
        ["move_type", "=", "in_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["not_paid", "partial"]],
    ]
    bills_summary = client.execute_kw(
        "account.move",
        "read_group",
        args=[bills_domain, ["amount_residual:sum"], []],
        kwargs={"lazy": False},
    )
    bills_bucket = bills_summary[0] if bills_summary else {}
    total_payable = float(bills_bucket.get("amount_residual", 0.0) or 0.0)

    # ── Facturación vs cobros por mes ────────────────────────────────────────
    inv_monthly = client.execute_kw(
        "account.move",
        "read_group",
        args=[inv_domain, ["amount_total:sum"], ["invoice_date:month"]],
        kwargs={"orderby": "invoice_date asc", "lazy": False},
    )

    collected_domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["paid", "in_payment"]],
        ["invoice_date", ">=", date_from.isoformat()],
        ["invoice_date", "<=", date_to.isoformat()],
    ]
    collected_monthly = client.execute_kw(
        "account.move",
        "read_group",
        args=[collected_domain, ["amount_total:sum"], ["invoice_date:month"]],
        kwargs={"orderby": "invoice_date asc", "lazy": False},
    )

    def _month_key(item: dict[str, Any]) -> str:
        return str(item.get("invoice_date:month") or item.get("invoice_date") or "")

    invoiced_map = {_month_key(i): float(i.get("amount_total", 0) or 0) for i in inv_monthly}
    collected_map = {_month_key(i): float(i.get("amount_total", 0) or 0) for i in collected_monthly}
    all_months = sorted(set(invoiced_map) | set(collected_map))
    monthly_comparison = [
        {
            "label": month_label(m),
            "invoiced": invoiced_map.get(m, 0.0),
            "collected": collected_map.get(m, 0.0),
        }
        for m in all_months
    ]

    # ── Estado de facturas (donut) ────────────────────────────────────────────
    all_inv_domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["invoice_date", ">=", date_from.isoformat()],
        ["invoice_date", "<=", date_to.isoformat()],
    ]
    status_summary = client.execute_kw(
        "account.move",
        "read_group",
        args=[all_inv_domain, ["amount_total:sum"], ["payment_state"]],
        kwargs={"lazy": False},
    )
    status_labels = {
        "paid": "Pagado",
        "not_paid": "Pendiente",
        "in_payment": "En proceso",
        "partial": "Parcial",
        "reversed": "Revertido",
    }
    invoice_status = [
        {
            "label": status_labels.get(str(item.get("payment_state") or ""), str(item.get("payment_state") or "Otro")),
            "value": float(item.get("amount_total", 0) or 0),
        }
        for item in status_summary
    ]

    # ── Top deudores ──────────────────────────────────────────────────────────
    debtors_domain = [
        ["move_type", "=", "out_invoice"],
        ["state", "=", "posted"],
        ["payment_state", "in", ["not_paid", "partial"]],
    ]
    debtors_raw = client.execute_kw(
        "account.move",
        "read_group",
        args=[debtors_domain, ["amount_residual:sum"], ["partner_id"]],
        kwargs={"lazy": False},
    )
    top_debtors = [
        {
            "label": item["partner_id"][1] if item.get("partner_id") else "Sin nombre",
            "value": float(item.get("amount_residual", 0) or 0),
        }
        for item in sorted(debtors_raw, key=lambda x: float(x.get("amount_residual", 0) or 0), reverse=True)[:10]
    ]

    # ── Gastos por mes (in_invoice) ───────────────────────────────────────────
    bills_monthly_domain = [
        ["move_type", "=", "in_invoice"],
        ["state", "=", "posted"],
        ["invoice_date", ">=", date_from.isoformat()],
        ["invoice_date", "<=", date_to.isoformat()],
    ]
    expenses_monthly_raw = client.execute_kw(
        "account.move",
        "read_group",
        args=[bills_monthly_domain, ["amount_total:sum"], ["invoice_date:month"]],
        kwargs={"orderby": "invoice_date asc", "lazy": False},
    )
    expenses_monthly = [
        {
            "label": month_label(item.get("invoice_date:month") or item.get("invoice_date")),
            "value": float(item.get("amount_total", 0) or 0),
        }
        for item in expenses_monthly_raw
    ]

    return {
        "kpis": {
            "totalInvoiced": total_invoiced,
            "totalCollected": total_collected,
            "totalPending": total_pending,
            "totalOverdue": total_overdue,
            "totalPayable": total_payable,
        },
        "charts": {
            "monthlyComparison": monthly_comparison,
            "invoiceStatus": invoice_status,
            "topDebtors": top_debtors,
            "expensesMonthly": expenses_monthly,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


def get_compras_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    from_dt = f"{date_from.isoformat()} 00:00:00"
    to_dt = f"{date_to.isoformat()} 23:59:59"

    po_domain = [
        ["state", "in", ["purchase", "done"]],
        ["date_order", ">=", from_dt],
        ["date_order", "<=", to_dt],
    ]

    # ── KPIs generales ───────────────────────────────────────────────────────────
    po_summary = client.execute_kw(
        "purchase.order",
        "read_group",
        args=[po_domain, ["amount_total:sum"], []],
        kwargs={"lazy": False},
    )
    bucket = po_summary[0] if po_summary else {}
    total_purchase = float(bucket.get("amount_total", 0.0) or 0.0)
    order_count = int(bucket.get("__count", 0) or 0)
    avg_order = total_purchase / order_count if order_count else 0.0

    # ── Compras por mes ──────────────────────────────────────────────────────────
    monthly_po_raw = client.execute_kw(
        "purchase.order",
        "read_group",
        args=[po_domain, ["amount_total:sum"], ["date_order:month"]],
        kwargs={"orderby": "date_order asc", "lazy": False},
    )
    monthly_purchase = [
        {
            "label": month_label(item.get("date_order:month") or item.get("date_order")),
            "value": float(item.get("amount_total", 0.0) or 0.0),
        }
        for item in monthly_po_raw
    ]

    # ── Compras por proveedor (top 10) ───────────────────────────────────────────
    supplier_raw = client.execute_kw(
        "purchase.order",
        "read_group",
        args=[po_domain, ["amount_total:sum"], ["partner_id"]],
        kwargs={"lazy": False},
    )
    top_suppliers = sorted(
        supplier_raw, key=lambda x: float(x.get("amount_total", 0) or 0), reverse=True
    )[:10]
    suppliers = [
        {
            "label": item["partner_id"][1] if item.get("partner_id") else "Sin nombre",
            "value": float(item.get("amount_total", 0.0) or 0.0),
        }
        for item in top_suppliers
    ]

    # ── Compras por categoría de producto ─────────────────────────────────────────
    line_domain = [
        ["order_id.state", "in", ["purchase", "done"]],
        ["order_id.date_order", ">=", from_dt],
        ["order_id.date_order", "<=", to_dt],
    ]
    product_po_raw = client.execute_kw(
        "purchase.order.line",
        "read_group",
        args=[line_domain, ["price_subtotal:sum", "product_id"], ["product_id"]],
        kwargs={"lazy": False},
    )

    category_purchase: dict[str, float] = {}
    if product_po_raw:
        product_ids = [int(item["product_id"][0]) for item in product_po_raw if item.get("product_id")]
        price_map = {
            int(item["product_id"][0]): float(item.get("price_subtotal", 0) or 0)
            for item in product_po_raw
            if item.get("product_id")
        }

        products = client.execute_kw(
            "product.product",
            "read",
            args=[product_ids],
            kwargs={"fields": ["id", "categ_id"]},
        )
        category_ids = sorted(
            {int(p["categ_id"][0]) for p in products if p.get("categ_id") and isinstance(p["categ_id"], list)}
        )
        category_map: dict[int, str] = {}
        if category_ids:
            categories = client.execute_kw(
                "product.category",
                "read",
                args=[category_ids],
                kwargs={"fields": ["id", "name"]},
            )
            category_map = {int(c["id"]): str(c["name"]) for c in categories}

        for p in products:
            pid = int(p["id"])
            amount = price_map.get(pid, 0.0)
            categ = p.get("categ_id")
            cat_name = (
                category_map.get(int(categ[0]), "Sin categoría")
                if categ and isinstance(categ, list)
                else "Sin categoría"
            )
            category_purchase[cat_name] = category_purchase.get(cat_name, 0.0) + amount

    category_rows = [
        {"label": label, "value": value}
        for label, value in sorted(category_purchase.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    # ── Estado de pedidos ────────────────────────────────────────────────────────
    status_summary = client.execute_kw(
        "purchase.order",
        "read_group",
        args=[po_domain, ["amount_total:sum"], ["state"]],
        kwargs={"lazy": False},
    )
    status_labels = {
        "draft": "Borrador",
        "sent": "Enviado",
        "to approve": "Por aprobar",
        "purchase": "Confirmado",
        "done": "Recibido",
        "cancel": "Cancelado",
    }
    order_status = [
        {
            "label": status_labels.get(str(item.get("state") or ""), str(item.get("state") or "Otro")),
            "value": float(item.get("amount_total", 0) or 0),
        }
        for item in status_summary
    ]

    return {
        "kpis": {
            "orderCount": order_count,
            "totalPurchase": total_purchase,
            "avgOrder": avg_order,
        },
        "charts": {
            "monthlyPurchase": monthly_purchase,
            "topSuppliers": suppliers,
            "byCategory": category_rows,
            "orderStatus": order_status,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


def get_crm_data(client: OdooClient, date_from: dt.date, date_to: dt.date) -> dict[str, Any]:
    # ── Pipeline snapshot (sin filtro de fecha, refleja estado actual) ──────────
    opp_domain = [["type", "=", "opportunity"], ["active", "=", True]]

    opp_summary = client.execute_kw(
        "crm.lead",
        "read_group",
        args=[opp_domain, ["expected_revenue:sum"], []],
        kwargs={"lazy": False},
    )
    bucket = opp_summary[0] if opp_summary else {}
    total_active = int(bucket.get("__count", 0))
    total_revenue = float(bucket.get("expected_revenue", 0.0) or 0.0)

    won_count = client.execute_kw(
        "crm.lead",
        "search_count",
        args=[[["type", "=", "opportunity"], ["active", "=", True], ["probability", "=", 100]]],
    )
    won_count = int(won_count or 0)

    # ── Por etapa ────────────────────────────────────────────────────────────────
    by_stage_raw = client.execute_kw(
        "crm.lead",
        "read_group",
        args=[opp_domain, ["expected_revenue:sum"], ["stage_id"]],
        kwargs={"lazy": False},
    )
    by_stage = [
        {
            "label": item["stage_id"][1] if item.get("stage_id") else "Sin etapa",
            "count": int(item.get("__count", 0)),
            "revenue": float(item.get("expected_revenue", 0.0) or 0.0),
        }
        for item in sorted(by_stage_raw, key=lambda x: float(x.get("expected_revenue", 0) or 0), reverse=True)
    ]

    # ── Por vendedor ─────────────────────────────────────────────────────────────
    by_user_raw = client.execute_kw(
        "crm.lead",
        "read_group",
        args=[opp_domain, ["expected_revenue:sum"], ["user_id"]],
        kwargs={"lazy": False},
    )
    by_user = [
        {
            "label": item["user_id"][1] if item.get("user_id") else "Sin asignar",
            "count": int(item.get("__count", 0)),
            "revenue": float(item.get("expected_revenue", 0.0) or 0.0),
        }
        for item in sorted(by_user_raw, key=lambda x: float(x.get("expected_revenue", 0) or 0), reverse=True)[:10]
    ]

    # ── Nuevas oportunidades por mes (filtro de fecha en create_date) ────────────
    new_domain = [
        ["type", "=", "opportunity"],
        ["create_date", ">=", f"{date_from.isoformat()} 00:00:00"],
        ["create_date", "<=", f"{date_to.isoformat()} 23:59:59"],
    ]
    new_monthly_raw = client.execute_kw(
        "crm.lead",
        "read_group",
        args=[new_domain, ["expected_revenue:sum"], ["create_date:month"]],
        kwargs={"orderby": "create_date asc", "lazy": False},
    )

    def _crm_month_key(item: dict[str, Any]) -> str:
        return str(item.get("create_date:month") or item.get("create_date") or "")

    new_monthly = [
        {
            "label": month_label(_crm_month_key(item)),
            "count": int(item.get("__count", 0)),
            "revenue": float(item.get("expected_revenue", 0.0) or 0.0),
        }
        for item in new_monthly_raw
    ]

    # ── Distribución por probabilidad (donut) ────────────────────────────────────
    prob_buckets = {"0-25%": 0, "26-50%": 0, "51-75%": 0, "76-99%": 0, "Ganadas (100%)": 0}
    all_opps = client.execute_kw(
        "crm.lead",
        "search_read",
        args=[opp_domain],
        kwargs={"fields": ["probability"], "limit": 500},
    )
    for opp in all_opps:
        p = float(opp.get("probability") or 0)
        if p == 100:
            prob_buckets["Ganadas (100%)"] += 1
        elif p >= 76:
            prob_buckets["76-99%"] += 1
        elif p >= 51:
            prob_buckets["51-75%"] += 1
        elif p >= 26:
            prob_buckets["26-50%"] += 1
        else:
            prob_buckets["0-25%"] += 1
    prob_distribution = [{"label": k, "value": v} for k, v in prob_buckets.items() if v > 0]

    return {
        "kpis": {
            "totalActive": total_active,
            "totalRevenue": total_revenue,
            "wonCount": won_count,
        },
        "charts": {
            "byStage": by_stage,
            "byUser": by_user,
            "newMonthly": new_monthly,
            "probDistribution": prob_distribution,
        },
        "meta": {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        },
    }


app = Flask(__name__)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/health")
def health() -> Any:
    return jsonify({"ok": True})


@app.get("/api/dashboard")
def dashboard_data() -> Any:
    now = dt.date.today()
    start_default = dt.date(now.year, 1, 1)

    try:
        date_from = parse_date(request.args.get("from"), start_default)
        date_to = parse_date(request.args.get("to"), now)
        if date_from > date_to:
            return jsonify({"error": "Invalid date range"}), 400

        client = OdooClient()
        payload = get_dashboard_data(client, date_from, date_to)
        return jsonify(payload)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


def _date_range_from_request() -> tuple[dt.date, dt.date]:
    now = dt.date.today()
    date_from = parse_date(request.args.get("from"), dt.date(now.year, 1, 1))
    date_to = parse_date(request.args.get("to"), now)
    if date_from > date_to:
        raise ValueError("Invalid date range: 'from' must be before 'to'")
    return date_from, date_to


@app.get("/api/ventas")
def ventas_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_dashboard_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/clientes")
def clientes_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_clientes_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/productos")
def productos_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_productos_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/contabilidad")
def contabilidad_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_contabilidad_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/compras")
def compras_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_compras_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


@app.get("/api/crm")
def crm_data() -> Any:
    try:
        date_from, date_to = _date_range_from_request()
        client = OdooClient()
        return jsonify(get_crm_data(client, date_from, date_to))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
