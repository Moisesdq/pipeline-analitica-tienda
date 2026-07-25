import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import duckdb

def run_pipeline():
    print("🚀 INICIANDO PIPELINE ETL (VERSIÓN PRODUCCIÓN CON BLINDAJE)...")

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
    # 2. EXTRACCIÓN Y LIMPIEZA DE DATOS (Data Quality)
    # ==========================================
    print("📥 Extrayendo tablas desde Google Sheets...")
    df_ventas = pd.DataFrame(sheet_id.worksheet('Ventas').get_all_records())
    df_detalle = pd.DataFrame(sheet_id.worksheet('Detalle_Ventas').get_all_records())
    df_productos = pd.DataFrame(sheet_id.worksheet('Productos').get_all_records())
    df_gastos = pd.DataFrame(sheet_id.worksheet('Gastos').get_all_records())

    print("🧹 Curando los datos y normalizando formatos...")
    # Normalización de tipos numéricos (Filtro anti-comas riguroso)
    df_detalle['cantidad'] = pd.to_numeric(df_detalle['cantidad'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_detalle['precio_compra_aplicado'] = pd.to_numeric(df_detalle['precio_compra_aplicado'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_detalle['precio_venta_aplicado'] = pd.to_numeric(df_detalle['precio_venta_aplicado'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    
    df_productos['stock_inicial'] = pd.to_numeric(df_productos['stock_inicial'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_productos['stock_minimo'] = pd.to_numeric(df_productos['stock_minimo'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_gastos['monto'] = pd.to_numeric(df_gastos['monto'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

    # Limpieza de textos e IDs
    for df in [df_ventas, df_detalle, df_productos, df_gastos]:
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()
            
    # Rellenar métodos de pago vacíos
    df_ventas['metodo_pago'] = df_ventas['metodo_pago'].replace('', 'No Definido')

    # Normalización de Fechas para Looker Studio
    df_ventas['fecha_hora'] = pd.to_datetime(df_ventas['fecha_hora'], errors='coerce')
    df_ventas['fecha_hora'] = df_ventas['fecha_hora'].fillna(pd.Timestamp.now()).dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Estandarizar fecha de gastos
    df_gastos['fecha'] = pd.to_datetime(df_gastos['fecha'], format='%d/%m/%Y', errors='coerce').dt.strftime('%Y-%m-%d')

    # ==========================================
    # 3. TRANSFORMACIÓN CON DUCKDB (SQL BLINDADO)
    # ==========================================
    print("⚡ Transformando datos con motor SQL en memoria (DuckDB)...")

    # A) Modelo de Ventas (Agregamos la columna 'mes' para compatibilidad con filtros)
    query_ventas_completas = """
        SELECT 
            SUBSTRING(v.fecha_hora, 1, 7) AS mes,
            v.fecha_hora,
            v.metodo_pago,
            d.id_producto,
            p.nombre,
            d.cantidad,
            ROUND(CAST(d.precio_compra_aplicado AS DOUBLE), 2) AS precio_compra,
            ROUND(CAST(d.precio_venta_aplicado AS DOUBLE), 2) AS precio_venta,
            ROUND(CAST(d.cantidad * d.precio_venta_aplicado AS DOUBLE), 2) AS subtotal,
            ROUND(CAST((d.precio_venta_aplicado - d.precio_compra_aplicado) * d.cantidad AS DOUBLE), 2) AS ganancia_bruta
        FROM df_ventas AS v
        LEFT JOIN df_detalle AS d 
            ON v.id_venta = d.id_venta
        LEFT JOIN df_productos AS p 
            ON d.id_producto = p.id_producto
        WHERE v.id_venta IS NOT NULL AND TRIM(CAST(v.id_venta AS VARCHAR)) != ''
    """
    df_modelo_ventas = duckdb.query(query_ventas_completas).to_df().fillna("")

    # B) Modelo de Inventario con Alertas
    query_inventario = """
        WITH ventas_resumen AS (
            SELECT 
                d.id_producto,
                SUM(d.cantidad) AS total_vendido
            FROM df_detalle AS d
            WHERE d.id_producto IS NOT NULL AND TRIM(CAST(d.id_producto AS VARCHAR)) != ''
            GROUP BY d.id_producto
        )
        SELECT 
            p.id_producto,
            p.nombre,
            p.stock_inicial,
            p.stock_minimo,
            COALESCE(vr.total_vendido, 0) AS total_vendido,
            (p.stock_inicial - COALESCE(vr.total_vendido, 0)) AS stock_actual,
            CASE 
                WHEN (p.stock_inicial - COALESCE(vr.total_vendido, 0)) < 0 THEN 'REVISAR: Stock Negativo'
                WHEN (p.stock_inicial - COALESCE(vr.total_vendido, 0)) <= p.stock_minimo THEN 'ALERTA: Stock Bajo'
                ELSE 'OK'
            END AS estado_inventario
        FROM df_productos AS p
        LEFT JOIN ventas_resumen AS vr 
            ON p.id_producto = vr.id_producto
        WHERE p.id_producto IS NOT NULL 
          AND TRIM(CAST(p.id_producto AS VARCHAR)) != ''
          AND LOWER(TRIM(CAST(p.nombre AS VARCHAR))) != 'null'
    """
    df_inventario = duckdb.query(query_inventario).to_df().fillna("")

    # C) Modelo Financiero (Valores Numéricos Forzados)
    query_financiero = """
        WITH ingresos AS (
            SELECT 
                SUBSTRING(v.fecha_hora, 1, 7) AS mes_anio,
                SUM(d.cantidad * d.precio_venta_aplicado) AS ingresos_totales,
                SUM((d.precio_venta_aplicado - d.precio_compra_aplicado) * d.cantidad) AS ganancia_bruta
            FROM df_ventas AS v
            LEFT JOIN df_detalle AS d 
                ON v.id_venta = d.id_venta
            WHERE v.id_venta IS NOT NULL AND TRIM(CAST(v.id_venta AS VARCHAR)) != ''
            GROUP BY SUBSTRING(v.fecha_hora, 1, 7)
        ),
        egresos AS (
            SELECT 
                SUBSTRING(fecha, 1, 7) AS mes_anio,
                SUM(monto) AS gastos_totales 
            FROM df_gastos
            WHERE monto IS NOT NULL
            GROUP BY SUBSTRING(fecha, 1, 7)
        )
        SELECT 
            COALESCE(i.mes_anio, e.mes_anio) AS mes,
            ROUND(CAST(COALESCE(i.ingresos_totales, 0) AS DOUBLE), 2) AS ingresos_totales,
            ROUND(CAST(COALESCE(i.ganancia_bruta, 0) AS DOUBLE), 2) AS ganancia_bruta,
            ROUND(CAST(COALESCE(e.gastos_totales, 0) AS DOUBLE), 2) AS gastos_totales,
            ROUND(CAST(COALESCE(i.ganancia_bruta, 0) - COALESCE(e.gastos_totales, 0) AS DOUBLE), 2) AS utilidad_neta_real,
            CASE 
                WHEN COALESCE(i.ingresos_totales, 0) > 0 
                THEN ROUND(CAST((COALESCE(i.ganancia_bruta, 0) / i.ingresos_totales) AS DOUBLE), 4)
                ELSE 0.0 
            END AS margen_porcentaje
        FROM ingresos i
        FULL OUTER JOIN egresos e 
            ON i.mes_anio = e.mes_anio
        ORDER BY mes DESC
    """
    df_financiero = duckdb.query(query_financiero).to_df().fillna("")


    # ==========================================
    # 4. CARGA A GOOGLE SHEETS (LOAD IDEMPOTENTE)
    # ==========================================
    print("📤 Subiendo tablas procesadas a Google Sheets...")

    def reemplazar_hoja(nombre_hoja, dataframe, cols):
        try:
            hoja = sheet_id.worksheet(nombre_hoja)
            hoja.clear()
            print(f"♻️ Pestaña '{nombre_hoja}' limpiada con éxito.")
        except Exception:
            hoja = sheet_id.add_worksheet(title=nombre_hoja, rows="1000", cols=cols)
            print(f"✨ Pestaña '{nombre_hoja}' creada desde cero.")
            
        datos = [dataframe.columns.values.tolist()] + dataframe.values.tolist()
        hoja.update(range_name='A1', values=datos)
        print(f"✅ Pestaña '{nombre_hoja}' actualizada.")

    reemplazar_hoja("BI_Ventas_Modeladas", df_modelo_ventas, "20")
    reemplazar_hoja("BI_Inventario", df_inventario, "10")
    reemplazar_hoja("BI_Finanzas_Resumen", df_financiero, "10")

    print("🎉 ¡ETL FINALIZADO CON ÉXITO! Tu Dashboard está blindado.")

if __name__ == "__main__":
    run_pipeline()