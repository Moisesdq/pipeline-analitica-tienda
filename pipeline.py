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
    
    # Función para evitar que Pandas colapse si la tabla está vacía (Día 1 del mes)
    def extraer_seguro(nombre_hoja):
        hoja = sheet_id.worksheet(nombre_hoja)
        registros = hoja.get_all_records()
        if not registros: # Si no hay datos, forzamos a que lea la fila 1 como columnas
            encabezados = hoja.row_values(1)
            return pd.DataFrame(columns=encabezados)
        return pd.DataFrame(registros)

    # Datos Calientes con extracción segura
    df_ventas_caliente = extraer_seguro('Ventas')
    df_detalle_caliente = extraer_seguro('Detalle_Ventas')
    
    # Tablas maestras (Estas siempre tienen datos)
    df_productos = pd.DataFrame(sheet_id.worksheet('Productos').get_all_records())
    df_gastos = pd.DataFrame(sheet_id.worksheet('Gastos').get_all_records())
    df_snapshots = pd.DataFrame(sheet_id.worksheet('Snapshots_Inventario').get_all_records())

    print("🧊 Extrayendo bóvedas de datos históricos...")
    try:
        df_ventas_fria = pd.DataFrame(sheet_id.worksheet('Ventas_Historicas').get_all_records())
        df_detalle_fria = pd.DataFrame(sheet_id.worksheet('Detalle_Ventas_Historicas').get_all_records())
    except Exception:
        # Si no existen, usamos las columnas de las tablas calientes
        df_ventas_fria = pd.DataFrame(columns=df_ventas_caliente.columns)
        df_detalle_fria = pd.DataFrame(columns=df_detalle_caliente.columns)

    print("🧹 Curando los datos y normalizando formatos...")
    # Unificamos Hot y Cold SOLO para finanzas
    df_ventas_total = pd.concat([df_ventas_caliente, df_ventas_fria], ignore_index=True)
    df_detalle_total = pd.concat([df_detalle_caliente, df_detalle_fria], ignore_index=True)

    # Normalización de tipos numéricos
    df_detalle_caliente['cantidad'] = pd.to_numeric(df_detalle_caliente['cantidad'], errors='coerce').fillna(0)
    df_detalle_total['cantidad'] = pd.to_numeric(df_detalle_total['cantidad'], errors='coerce').fillna(0)
    df_detalle_total['precio_compra_aplicado'] = pd.to_numeric(df_detalle_total['precio_compra_aplicado'], errors='coerce').fillna(0)
    df_detalle_total['precio_venta_aplicado'] = pd.to_numeric(df_detalle_total['precio_venta_aplicado'], errors='coerce').fillna(0)
    
    df_productos['stock_inicial'] = pd.to_numeric(df_productos['stock_inicial'], errors='coerce').fillna(0)
    df_productos['stock_minimo'] = pd.to_numeric(df_productos['stock_minimo'], errors='coerce').fillna(0)
    df_gastos['monto'] = pd.to_numeric(df_gastos['monto'], errors='coerce').fillna(0)

    # Limpieza de textos e IDs
    for df in [df_ventas_total, df_detalle_total, df_detalle_caliente, df_productos, df_gastos]:
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()
            
    # Rellenar métodos de pago vacíos
    df_ventas_total['metodo_pago'] = df_ventas_total['metodo_pago'].replace('', 'No Definido')
    if 'cliente_nota' not in df_ventas_total.columns:
        df_ventas_total['cliente_nota'] = 'Sin Nombre'
    else:
        df_ventas_total['cliente_nota'] = df_ventas_total['cliente_nota'].replace('', 'Sin Nombre')
    
    # Normalización de Fechas para Looker Studio
    df_ventas_total['fecha_hora'] = pd.to_datetime(df_ventas_total['fecha_hora'], dayfirst=True, errors='coerce')
    df_ventas_total['fecha_hora'] = df_ventas_total['fecha_hora'].fillna(pd.Timestamp.now()).dt.strftime('%Y-%m-%d %H:%M:%S')
    
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
        FROM df_ventas_total AS v
        LEFT JOIN df_detalle_total AS d 
            ON v.id_venta = d.id_venta
        LEFT JOIN df_productos AS p 
            ON d.id_producto = p.id_producto
        WHERE v.id_venta IS NOT NULL AND TRIM(CAST(v.id_venta AS VARCHAR)) != ''
    """
    df_modelo_ventas = duckdb.query(query_ventas_completas).to_df().fillna("")

  # B) Modelo de Inventario con Alertas (SOLO USA DATOS CALIENTES)
    query_inventario = """
        WITH ventas_mes_actual AS (
            SELECT 
                d.id_producto,
                SUM(d.cantidad) AS total_vendido
            FROM df_detalle_caliente AS d
            WHERE d.id_producto IS NOT NULL AND TRIM(CAST(d.id_producto AS VARCHAR)) != ''
            GROUP BY d.id_producto
        ),
        ultimo_snapshot AS (
            SELECT 
                id_producto, 
                CAST(stock_cierre AS DOUBLE) AS stock_base
            FROM df_snapshots
        )
        SELECT 
            p.id_producto,
            p.nombre,
            COALESCE(s.stock_base, p.stock_inicial) AS stock_inicial,
            p.stock_minimo,
            COALESCE(v.total_vendido, 0) AS total_vendido,
            (COALESCE(s.stock_base, p.stock_inicial) - COALESCE(v.total_vendido, 0)) AS stock_actual,
            CASE 
                WHEN (COALESCE(s.stock_base, p.stock_inicial) - COALESCE(v.total_vendido, 0)) < 0 THEN 'REVISAR: Stock Negativo'
                WHEN (COALESCE(s.stock_base, p.stock_inicial) - COALESCE(v.total_vendido, 0)) <= p.stock_minimo THEN 'ALERTA: Stock Bajo'
                ELSE 'OK'
            END AS estado_inventario
        FROM df_productos AS p
        LEFT JOIN ultimo_snapshot AS s
            ON p.id_producto = s.id_producto
        LEFT JOIN ventas_mes_actual AS v 
            ON p.id_producto = v.id_producto
        WHERE p.id_producto IS NOT NULL 
          AND TRIM(CAST(p.id_producto AS VARCHAR)) != ''
    """
    df_inventario = duckdb.query(query_inventario).to_df().fillna("")
    # C) Modelo Financiero (Valores Numéricos Forzados)
    query_financiero = """
        WITH ingresos AS (
            SELECT 
                SUBSTRING(v.fecha_hora, 1, 7) AS mes_anio,
                SUM(d.cantidad * d.precio_venta_aplicado) AS ingresos_totales,
                SUM((d.precio_venta_aplicado - d.precio_compra_aplicado) * d.cantidad) AS ganancia_bruta
            FROM df_ventas_total AS v
            LEFT JOIN df_detalle_total AS d 
                ON v.id_venta = d.id_venta
            WHERE v.id_venta IS NOT NULL 
              AND TRIM(CAST(v.id_venta AS VARCHAR)) != ''
              AND LOWER(TRIM(CAST(v.metodo_pago AS VARCHAR))) != 'fiado'
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

    # D) Modelo de Deudores para el Dashboard (Solo lectura analítica)
    query_deudores = """
        SELECT 
            v.cliente_nota AS cliente,
            SUM(d.cantidad * d.precio_venta_aplicado) AS total_fiado_historico,
            COUNT(DISTINCT v.id_venta) AS cantidad_compras_fiadas
        FROM df_ventas_total AS v
        LEFT JOIN df_detalle_total AS d 
            ON v.id_venta = d.id_venta
        WHERE v.id_venta IS NOT NULL 
          AND TRIM(CAST(v.id_venta AS VARCHAR)) != ''
          AND LOWER(TRIM(CAST(v.metodo_pago AS VARCHAR))) = 'fiado'
        GROUP BY v.cliente_nota
    """
    df_deudores_analytics = duckdb.query(query_deudores).to_df().fillna("")

    # ==========================================
    # 4. CARGA A GOOGLE SHEETS (LOAD IDEMPOTENTE)
    # ==========================================
    print("📤 Subiendo tablas procesadas a Google Sheets...")

    def reemplazar_hoja_segura(nombre_hoja, dataframe, cols):
        nombre_temp = f"{nombre_hoja}_TEMP"
        
        # 1. Crear la hoja temporal e inyectar los datos
        try:
            hoja_temp = sheet_id.add_worksheet(title=nombre_temp, rows="1000", cols=cols)
            datos = [dataframe.columns.values.tolist()] + dataframe.values.tolist()
            hoja_temp.update(range_name='A1', values=datos)
            print(f"✅ Datos cargados con éxito en staging: '{nombre_temp}'")
        except Exception as e:
            print(f"❌ Error crítico al escribir en staging para {nombre_hoja}. Abortando para proteger producción. Error: {e}")
            return # Salimos para no romper nada
            
        # 2. Si llegamos aquí, los datos están seguros. Ahora hacemos el SWAP.
        try:
            hoja_vieja = sheet_id.worksheet(nombre_hoja)
            sheet_id.del_worksheet(hoja_vieja)
            print(f"🗑️ Hoja antigua '{nombre_hoja}' eliminada.")
        except Exception:
            print(f"⚠️ La hoja '{nombre_hoja}' no existía, se creará una nueva.")

        # 3. Renombrar la hoja temporal a producción
        hoja_temp.update_title(nombre_hoja)
        print(f"🚀 SWAP EXITOSO: '{nombre_temp}' ahora es la tabla oficial '{nombre_hoja}'.")

    # Ejecutamos las cargas con la nueva función segura
    reemplazar_hoja_segura("BI_Ventas_Modeladas", df_modelo_ventas, "20")
    reemplazar_hoja_segura("BI_Inventario", df_inventario, "10")
    reemplazar_hoja_segura("BI_Finanzas_Resumen", df_financiero, "10")
    reemplazar_hoja_segura("BI_Deudores_Analytics", df_deudores_analytics, "5")

    print("🎉 ¡ETL FINALIZADO CON ÉXITO! Tu Dashboard está blindado.")

if __name__ == "__main__":
    run_pipeline()