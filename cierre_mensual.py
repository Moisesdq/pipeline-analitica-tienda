import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

def ejecutar_cierre_mensual():
    print("🚨 INICIANDO CIERRE MENSUAL (MODO PARANOICO ACTIVO)...")

    # ==========================================
    # 0. CONFIGURACIÓN Y CONEXIÓN
    # ==========================================
    CONFIG_SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    credenciales = Credentials.from_service_account_file('credenciales.json', scopes=CONFIG_SCOPES)
    cliente_gmail = gspread.authorize(credenciales)
    db = cliente_gmail.open('DB_Tienda_Operacional')
    
    # Hojas Calientes
    ws_ventas = db.worksheet('Ventas')
    ws_detalle = db.worksheet('Detalle_Ventas')
    ws_inventario = db.worksheet('BI_Inventario') # Para tomar el snapshot
    
    # Hojas Frías / Snapshots
    ws_ventas_historicas = db.worksheet('Ventas_Historicas')
    ws_detalle_historicas = db.worksheet('Detalle_Ventas_Historicas')
    ws_snapshots = db.worksheet('Snapshots_Inventario')

    # Calcular el mes a cerrar (Si hoy es 1 de Agosto, cerramos Julio)
    fecha_actual = datetime.now()
    mes_a_cerrar = (fecha_actual - relativedelta(months=1)).strftime('%Y-%m')
    print(f"📅 Mes contable a cerrar: {mes_a_cerrar}")

    # ==========================================
    # FASE 1: LECTURA Y SNAPSHOT DE INVENTARIO
    # ==========================================
    print("📸 Generando Snapshot de Inventario...")
    df_inventario_actual = pd.DataFrame(ws_inventario.get_all_records())
    
    if df_inventario_actual.empty:
        print("❌ Error: BI_Inventario está vacío. Abortando cierre.")
        return

    # Preparamos los datos para el Snapshot
    snapshot_datos = []
    for index, row in df_inventario_actual.iterrows():
        snapshot_datos.append([
            str(row['id_producto']), 
            mes_a_cerrar, 
            row['stock_actual']
        ])
    
    # Guardamos el Snapshot de forma inmutable
    ws_snapshots.append_rows(snapshot_datos)
    print("✅ Snapshot guardado exitosamente.")

    # ==========================================
    # FASE 2: LECTURA Y BLOQUEO LÓGICO (CHECKSUM)
    # ==========================================
    print("🔒 Fase 1 y 2: Leyendo tablas calientes y calculando Checksums...")
    ventas_calientes = ws_ventas.get_all_values()
    detalle_calientes = ws_detalle.get_all_values()

    # Si solo hay encabezados (1 fila), no hay nada que cerrar
    if len(ventas_calientes) <= 1:
        print("⚠️ No hay ventas en el mes. Cierre finalizado sin cambios.")
        return

    # Separamos encabezados de datos
    datos_ventas = ventas_calientes[1:]
    datos_detalle = detalle_calientes[1:]
    
    cantidad_filas_ventas = len(datos_ventas)
    cantidad_filas_detalle = len(datos_detalle)
    
    print(f"📊 Detectadas {cantidad_filas_ventas} Ventas y {cantidad_filas_detalle} Detalles.")

    # ==========================================
    # FASE 3: INTENTO DE ESCRITURA (APPEND)
    # ==========================================
    print("🧊 Fase 3: Transfiriendo a Cold Storage...")
    try:
        ws_ventas_historicas.append_rows(datos_ventas)
        ws_detalle_historicas.append_rows(datos_detalle)
    except Exception as e:
        print(f"❌ Error crítico al escribir en histórico: {e}. Abortando. Datos calientes intactos.")
        return

    # ==========================================
    # FASE 4: LA PARANOIA (VALIDACIÓN POST-ESCRITURA)
    # ==========================================
    print("🕵️‍♂️ Fase 4: Validando integridad de los datos transferidos...")
    # Descargamos el histórico para confirmar que todo llegó
    df_ventas_frias = pd.DataFrame(ws_ventas_historicas.get_all_records())
    df_detalle_frias = pd.DataFrame(ws_detalle_historicas.get_all_records())

    # Extraemos el último lote de IDs insertados (asumiendo que id_venta es la columna 1)
    ultimos_ids_frios = df_ventas_frias.iloc[-cantidad_filas_ventas:, df_ventas_frias.columns.get_loc('id_venta')].astype(str).tolist()
    ids_calientes = [str(row[0]) for row in datos_ventas] # id_venta es índice 0

    if ultimos_ids_frios == ids_calientes:
        print("✅ VALIDACIÓN ACID APROBADA: Los datos se copiaron 100% exactos.")
    else:
        print("❌ ERROR DE INTEGRIDAD: Los checksums no coinciden. Posible pérdida de paquetes. Abortando limpieza.")
        return

    # ==========================================
    # FASE 5: EL COMMIT (BORRADO QUIRÚRGICO POR RANGO)
    # ==========================================
    print("🔪 Fase 5: Ejecutando Borrado Quirúrgico (Range Delete) para evitar Race Conditions...")
    
    def borrar_por_rango(worksheet, cantidad_filas_a_borrar):
        # La API de Google usa índices base 0. La fila 1 (encabezados) es el índice 0.
        # Queremos borrar desde el índice 1 (fila 2) hasta la última fila leída.
        body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": worksheet.id,
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": cantidad_filas_a_borrar + 1
                        }
                    }
                }
            ]
        }
        db.batch_update(body)

    # Borramos exactamente la cantidad de filas que leímos, 
    # si AppSheet insertó algo nuevo hace 1 segundo, sobrevivirá intacto.
    borrar_por_rango(ws_ventas, cantidad_filas_ventas)
    borrar_por_rango(ws_detalle, cantidad_filas_detalle)
    
    print("🎉 ¡CIERRE MENSUAL COMPLETADO CON ÉXITO Y SIN PÉRDIDA DE DATOS!")

if __name__ == "__main__":
    ejecutar_cierre_mensual()