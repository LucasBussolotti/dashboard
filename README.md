# Dashboard Odoo (Flask + Chart.js)

Dashboard web conectado a Odoo via JSON-RPC para mostrar KPIs comerciales y graficos:

- Ventas totales
- Pedidos
- Ticket promedio
- Clientes nuevos
- Ventas por mes
- Ventas por categoria
- Top productos
- Ventas por region

## 1) Configuracion

1. Crear un archivo `.env` en la raiz (puedes copiar `.env.example`).
2. Cargar tus variables de Odoo.

Variables esperadas:

- `ODOO_URL`
- `ODOO_DB`
- `ODOO_USER`
- `ODOO_PASSWORD` o `ODOO_API_KEY`
- `ODOO_PORT` (opcional para referencia)

## 2) Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3) Ejecutar

```bash
python app.py
```

Abrir en navegador: `http://localhost:5000`

## 4) Notas tecnicas

- Backend: `app.py` (Flask)
- Frontend: `templates/index.html`, `static/styles.css`, `static/app.js`
- API dashboard: `GET /api/dashboard?from=YYYY-MM-DD&to=YYYY-MM-DD`
- Health check: `GET /api/health`

## Seguridad

- No subir `.env` al repositorio.
- Usa `ODOO_API_KEY` en vez de password cuando sea posible.
- Si una credencial ya se compartio en texto plano, rotarla en Odoo.
