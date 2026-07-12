import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import duckdb

def run_pipeline():
    print("🚀 INICIANDO PIPELINE ETL...")

    # ==========================================
    # 1. CONFIGURACIÓN Y CONEXIÓN
    # ==========================================
    print("🔐 Autenticando con Google...")
    CONFIG_SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    # Cargar credenciales locales (GitHub Actions usará este mismo archivo)
    credenciales = Credentials.from_service_account_file('credenciales.json', scopes=CONFIG_SCOPES)
    cliente_gmail = gspread.authorize(credenciales)

    # Conectar al archivo exacto
    sheet_id = cliente_gmail.open('DB_Tienda_Operacional')
    print("✅ Conectado exitosamente a DB_Tienda_Operacional")


    # ==========================================
    # 2. EXTRACCIÓN Y LIMPIEZA
    # ==========================================
    print("📥 Extrayendo tablas desde Google Sheets...")
    df_ventas = pd.DataFrame(sheet_id.worksheet('Ventas').get_all_records())
    df_detalle = pd.DataFrame(sheet_id.worksheet('Detalle_Ventas').get_all_records())
    df_productos = pd.DataFrame(sheet_id.worksheet('Productos').get_all_records())

    print("🧹 Curando los datos (forzando formato numérico)...")
    # Esto evita que los textos vacíos rompan las matemáticas en SQL
    df_detalle['cantidad'] = pd.to_numeric(df_detalle['cantidad'], errors='coerce').fillna(0)
    df_detalle['precio_compra_aplicado'] = pd.to_numeric(df_detalle['precio_compra_aplicado'], errors='coerce').fillna(0)
    df_detalle['precio_venta_aplicado'] = pd.to_numeric(df_detalle['precio_venta_aplicado'], errors='coerce').fillna(0)
    
    # Asegurarnos de que el stock inicial también sea numérico por si acaso
    df_productos['stock_inicial'] = pd.to_numeric(df_productos['stock_inicial'], errors='coerce').fillna(0)


    # ==========================================
    # 3. TRANSFORMACIÓN (DUCKDB)
    # ==========================================
    print("⚡ Transformando datos con motor SQL en memoria (DuckDB)...")

    # A) Modelo de Ventas
    query_ventas_completas = """
        SELECT 
            v.fecha_hora,
            v.metodo_pago,
            d.id_producto,
            p.nombre,
            d.cantidad,
            d.precio_compra_aplicado AS precio_compra,
            d.precio_venta_aplicado AS precio_venta,
            (d.cantidad * d.precio_venta_aplicado) AS subtotal,
            (d.precio_venta_aplicado - d.precio_compra_aplicado) * d.cantidad AS ganancia_bruta
        FROM df_ventas AS v
        JOIN df_detalle AS d ON v.id_venta = d.id_venta
        JOIN df_productos AS p ON d.id_producto = p.id_producto
    """
    df_modelo_ventas = duckdb.query(query_ventas_completas).to_df().fillna("")

    # B) Modelo de Inventario
    query_inventario = """
        SELECT 
            p.id_producto,
            p.nombre,
            p.stock_inicial,
            COALESCE(SUM(d.cantidad), 0) AS total_vendido,
            (p.stock_inicial - COALESCE(SUM(d.cantidad), 0)) AS stock_actual
        FROM df_productos AS p
        LEFT JOIN df_detalle AS d ON p.id_producto = d.id_producto
        GROUP BY p.id_producto, p.nombre, p.stock_inicial
    """
    df_inventario = duckdb.query(query_inventario).to_df().fillna("")


    # ==========================================
    # 4. CARGA A GOOGLE SHEETS (LOAD)
    # ==========================================
    print("📤 Subiendo tablas procesadas a Google Sheets...")

    # --- Subir Ventas Modeladas ---
    try:
        hoja_ventas_bi = sheet_id.add_worksheet(title="BI_Ventas_Modeladas", rows="1000", cols="20")
    except Exception:
        hoja_ventas_bi = sheet_id.worksheet("BI_Ventas_Modeladas")
        hoja_ventas_bi.clear()
    
    datos_ventas = [df_modelo_ventas.columns.values.tolist()] + df_modelo_ventas.values.tolist()
    hoja_ventas_bi.update(range_name='A1', values=datos_ventas)
    print("✅ Pestaña 'BI_Ventas_Modeladas' actualizada.")

    # --- Subir Inventario ---
    try:
        hoja_inv_bi = sheet_id.add_worksheet(title="BI_Inventario", rows="1000", cols="10")
    except Exception:
        hoja_inv_bi = sheet_id.worksheet("BI_Inventario")
        hoja_inv_bi.clear()
        
    datos_inv = [df_inventario.columns.values.tolist()] + df_inventario.values.tolist()
    hoja_inv_bi.update(range_name='A1', values=datos_inv)
    print("✅ Pestaña 'BI_Inventario' actualizada.")

    print("🎉 ¡ETL FINALIZADO CON ÉXITO! Tu Dashboard está listo para brillar.")

# Punto de entrada del script
if __name__ == "__main__":
    run_pipeline()