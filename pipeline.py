import os
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import duckdb

print("Iniciando pipeline ETL...")

# 1. AUTENTICACIÓN FLEXIBLE (Local vs. Nube)
if "GOOGLE_CREDENTIALS" in os.environ:
    print("GitHub Actions detectado. Cargando credenciales desde Secrets...")
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(
        creds_dict, 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
else:
    print("Computadora local detectada. Cargando credenciales locales...")
    creds = Credentials.from_service_account_file(
        "credenciales.json", 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )

# Conectar con la hoja de cálculo
client = gspread.authorize(creds)
SPREADSHEET_NAME = "DB_Tienda_Operacional"
sheet_id = client.open(SPREADSHEET_NAME)

# 2. EXTRACCIÓN (Extract)
print("📥 Extrayendo tablas desde Google Sheets...")
df_ventas = pd.DataFrame(sheet_id.worksheet("Ventas").get_all_records())
df_detalle = pd.DataFrame(sheet_id.worksheet("Detalle_Ventas").get_all_records())
df_productos = pd.DataFrame(sheet_id.worksheet("Productos").get_all_records())

# 3. TRANSFORMACIÓN (Transform) con DuckDB
print("Ejecutando transformaciones SQL en memoria con DuckDB...")
query = """
SELECT 
    v.id_venta,
    v.fecha_hora,
    v.metodo_pago,
    dv.id_producto,
    p.nombre,
    dv.cantidad,
    dv.precio_compra_aplicado AS precio_compra,
    dv.precio_venta_aplicado AS precio_venta,
    (dv.cantidad * dv.precio_venta_aplicado) as subtotal,
    ((dv.precio_venta_aplicado - dv.precio_compra_aplicado) * dv.cantidad) as ganancia_bruta
FROM df_detalle dv
JOIN df_ventas v ON dv.id_venta = v.id_venta
JOIN df_productos p ON dv.id_producto = p.id_producto
"""
df_modelo_ventas = duckdb.query(query).to_df()

# Limpieza rápida para evitar errores de carga en celdas vacías
df_modelo_ventas = df_modelo_ventas.fillna("")

# 4. CARGA (Load)
print("📤 Cargando datos procesados a la capa analítica...")
try:
    hoja_destino = sheet_id.add_worksheet(title="BI_Ventas_Modeladas", rows="1000", cols="20")
    print("Pestaña 'BI_Ventas_Modeladas' creada exitosamente.")
except Exception:
    hoja_destino = sheet_id.worksheet("BI_Ventas_Modeladas")
    hoja_destino.clear()
    print("Pestaña existente limpiada con éxito.")

# Convertir el DataFrame a formato compatible con Google Sheets
columnas = df_modelo_ventas.columns.values.tolist()
filas = df_modelo_ventas.values.tolist()
datos_a_subir = [columnas] + filas

# Enviar los datos
hoja_destino.update(range_name='A1', values=datos_a_subir)
print("PIPELINE FINALIZADO CON ÉXITO! Looker Studio actualizado.")