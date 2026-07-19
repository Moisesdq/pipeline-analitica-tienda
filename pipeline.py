import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import duckdb

def run_pipeline():
    print("🚀 INICIANDO PIPELINE ETL (VERSIÓN PRODUCCIÓN)...")

    # ==========================================
    # 1. CONFIGURACIÓN Y CONEXIÓN
    # ==========================================
    print("🔐 Autenticando con Google...")
    CONFIG_SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    credenciales = Credentials.from_service_account_file('credenciales.json', scopes=CONFIG_SCOPES)
    cliente_gmail = gspread.authorize(credenciales)
    sheet_id = cliente_gmail.open('DB_Tienda_Operacional')
    print("✅ Conectado exitosamente a DB_Tienda_Operacional")


    # ==========================================
    # 2. EXTRACCIÓN Y LIMPIEZA (Data Quality)
    # ==========================================
    print("📥 Extrayendo tablas desde Google Sheets...")
    df_ventas = pd.DataFrame(sheet_id.worksheet('Ventas').get_all_records())
    df_detalle = pd.DataFrame(sheet_id.worksheet('Detalle_Ventas').get_all_records())
    df_productos = pd.DataFrame(sheet_id.worksheet('Productos').get_all_records())
    
    # 🌟 NUEVO: Extraer los Gastos
    df_gastos = pd.DataFrame(sheet_id.worksheet('Gastos').get_all_records())

    print("🧹 Curando los datos y normalizando formatos...")
    # Forzar formato numérico
    df_detalle['cantidad'] = pd.to_numeric(df_detalle['cantidad'], errors='coerce').fillna(0)
    df_detalle['precio_compra_aplicado'] = pd.to_numeric(df_detalle['precio_compra_aplicado'], errors='coerce').fillna(0)
    df_detalle['precio_venta_aplicado'] = pd.to_numeric(df_detalle['precio_venta_aplicado'], errors='coerce').fillna(0)
    df_productos['stock_inicial'] = pd.to_numeric(df_productos['stock_inicial'], errors='coerce').fillna(0)
    df_gastos['monto'] = pd.to_numeric(df_gastos['monto'], errors='coerce').fillna(0)

    # 🌟 NUEVO: Blindaje de Fechas (Para que Looker Studio no sufra)
    # Convertimos a formato fecha, rellenamos errores con la fecha actual y lo pasamos a texto estándar (YYYY-MM-DD)
    df_ventas['fecha_hora'] = pd.to_datetime(df_ventas['fecha_hora'], errors='coerce')
    df_ventas['fecha_hora'] = df_ventas['fecha_hora'].fillna(pd.Timestamp.now()).dt.strftime('%Y-%m-%d %H:%M:%S')


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

    # 🌟 NUEVO: B) Modelo de Inventario con Alertas
    query_inventario = """
        SELECT 
            p.id_producto,
            p.nombre,
            p.stock_inicial,
            COALESCE(SUM(d.cantidad), 0) AS total_vendido,
            (p.stock_inicial - COALESCE(SUM(d.cantidad), 0)) AS stock_actual,
            CASE 
                WHEN (p.stock_inicial - COALESCE(SUM(d.cantidad), 0)) < 0 THEN 'REVISAR: Stock Negativo'
                WHEN (p.stock_inicial - COALESCE(SUM(d.cantidad), 0)) <= 3 THEN 'ALERTA: Stock Bajo'
                ELSE 'OK'
            END AS estado_inventario
        FROM df_productos AS p
        LEFT JOIN df_detalle AS d ON p.id_producto = d.id_producto
        GROUP BY p.id_producto, p.nombre, p.stock_inicial
    """
    df_inventario = duckdb.query(query_inventario).to_df().fillna("")

    # 🌟 NUEVO: C) Modelo Financiero (Utilidad Neta Real)
    query_financiero = """
        WITH ingresos AS (
            SELECT 
                SUM(d.cantidad * d.precio_venta_aplicado) AS ingresos_totales,
                SUM((d.precio_venta_aplicado - d.precio_compra_aplicado) * d.cantidad) AS ganancia_bruta
            FROM df_ventas AS v
            JOIN df_detalle AS d ON v.id_venta = d.id_venta
        ),
        egresos AS (
            SELECT SUM(monto) AS gastos_totales FROM df_gastos
        )
        SELECT 
            COALESCE(ingresos.ingresos_totales, 0) AS ingresos_totales,
            COALESCE(ingresos.ganancia_bruta, 0) AS ganancia_bruta,
            COALESCE(egresos.gastos_totales, 0) AS gastos_totales,
            (COALESCE(ingresos.ganancia_bruta, 0) - COALESCE(egresos.gastos_totales, 0)) AS utilidad_neta_real
        FROM ingresos, egresos
    """
    df_financiero = duckdb.query(query_financiero).to_df().fillna("")


    # ==========================================
    # 4. CARGA A GOOGLE SHEETS (LOAD SEGURO E IDEMPOTENTE)
    # ==========================================
    print("📤 Subiendo tablas procesadas a Google Sheets...")

    def reemplazar_hoja(nombre_hoja, dataframe, cols):
        """Función auxiliar para limpiar y actualizar hojas (Mantiene la conexión con Looker)"""
        try:
            hoja = sheet_id.worksheet(nombre_hoja)
            hoja.clear() # Limpiamos el contenido sin borrar la pestaña
            print(f"♻️ Pestaña '{nombre_hoja}' limpiada con éxito.")
        except Exception:
            # Si no existe, la creamos por primera vez
            hoja = sheet_id.add_worksheet(title=nombre_hoja, rows="1000", cols=cols)
            print(f"✨ Pestaña '{nombre_hoja}' creada desde cero.")
            
        datos = [dataframe.columns.values.tolist()] + dataframe.values.tolist()
        hoja.update(range_name='A1', values=datos)
        print(f"✅ Pestaña '{nombre_hoja}' actualizada.")

    # 🌟 NUEVO: Usamos la función para subir las 3 tablas limpiamente
    reemplazar_hoja("BI_Ventas_Modeladas", df_modelo_ventas, "20")
    reemplazar_hoja("BI_Inventario", df_inventario, "10")
    reemplazar_hoja("BI_Finanzas_Resumen", df_financiero, "10")

    print("🎉 ¡ETL FINALIZADO CON ÉXITO! Tu Dashboard está blindado.")

# ESTO VA PEGADO AL MARGEN IZQUIERDO (Fuera de run_pipeline)
if __name__ == "__main__":
    run_pipeline()