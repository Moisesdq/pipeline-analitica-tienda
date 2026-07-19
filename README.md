# Proyecto: Modernización de Datos para Tienda de Barrio (MVP)

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)
![Google Sheets](https://img.shields.io/badge/Google_Sheets-34A853?style=for-the-badge&logo=google-sheets&logoColor=white)
![AppSheet](https://img.shields.io/badge/AppSheet-4285F4?style=for-the-badge&logo=appsheet&logoColor=white)
![Looker Studio](https://img.shields.io/badge/Looker_Studio-4285F4?style=for-the-badge&logo=google&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)

Este proyecto académico implementa un flujo de Ingeniería de Datos de extremo a extremo (End-to-End) para resolver un problema financiero real en un comercio minorista local de abarrotes y variedades.

## 1. El Problema de Negocio
El comercio opera actualmente de manera 100% analógica. El principal riesgo financiero radica en que los gastos fijos (servicios públicos, alquiler) se pagan directamente del efectivo de la caja diaria sin registro previo, distorsionando la utilidad real del negocio.

## 2. Modelo de Datos Ideal (OLTP)
A continuación se presenta el diseño del Modelo Entidad-Relación propuesto para el MVP:

### Tabla: Categorias
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_categoria` | INT | PK, Auto_Increment | Identificador único de la categoría |
| `nombre_categoria`| VARCHAR(50) | Not Null | Ej. 'Limpieza', 'Abarrotes' |

### Tabla: Productos
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_producto` | VARCHAR(50) | PK | Código de barras o ID único |
| `id_categoria` | INT | FK -> Categorias | Categoría a la que pertenece |
| `nombre` | VARCHAR(100)| Not Null | Nombre comercial del producto |
| `precio_compra` | DECIMAL(10,2)| Not Null | Costo de adquisición |
| `precio_venta` | DECIMAL(10,2)| Not Null | Precio al público |
| `stock_inicial` | INT | Default 0 | Inventario base en tienda |

### Tabla: Ventas
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_venta` | INT | PK, Auto_Increment | Número de transacción |
| `fecha_hora` | DATETIME | Default CURRENT_TIMESTAMP | Momento de la compra |
| `metodo_pago` | VARCHAR(20) | Not Null | 'Efectivo', 'Tarjeta', 'QR' |

### Tabla: Detalle_Ventas
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_detalle` | INT | PK, Auto_Increment | Identificador de línea |
| `id_venta` | INT | FK -> Ventas | Venta asociada |
| `id_producto` | VARCHAR(50) | FK -> Productos | Producto vendido |
| `cantidad` | INT | Not Null | Unidades vendidas |
| `subtotal` | DECIMAL(10,2)| Not Null | cantidad * precio_venta_aplicado |
| `precio_compra_aplicado` | DECIMAL(10,2)| Not Null | Congela el costo histórico en el momento de la venta (SCD) |
| `precio_venta_aplicado` | DECIMAL(10,2)| Not Null | Congela el precio al público en el momento de la venta (SCD) |

### Tabla: Gastos
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_gasto` | INT | PK, Auto_Increment | Identificador del egreso |
| `fecha` | DATE | Not Null | Fecha del pago |
| `tipo_gasto` | VARCHAR(20) | Not Null | 'Fijo' o 'Variable' |
| `descripcion` | VARCHAR(150)| Not Null | Detalle (Ej. 'Luz Marzo') |
| `monto` | DECIMAL(10,2)| Not Null | Cantidad de dinero pagada |

## 3. Arquitectura de Datos (Modern Data Stack Ligero)
Para este MVP, se ha diseñado un pipeline de datos tipo ETL (Extract, Transform, Load) optimizado para bajo costo y alta escalabilidad. El flujo se divide en las siguientes capas:

| Capa del Pipeline | Tecnología Utilizada | Función Específica |
| :--- | :--- | :--- |
| **Ingesta (Operacional)** | AppSheet + Google Sheets | App móvil no-code para captura en punto de venta (escáner de barras) con almacenamiento crudo. |
| **Extracción (Extract)** | Python (Google Sheets API) | Script que lee los datos operacionales de forma segura mediante credenciales de servicio (Service Account). |
| **Procesamiento (Transform)** | DuckDB | Motor SQL analítico en memoria (dentro de Python) para cruzar ventas, calcular márgenes y modelar datos. |
| **Carga (Load)** | Google Sheets | Carga del DataFrame procesado a una vista materializada (`BI_Ventas_Modeladas`), evitando Data Warehouses costosos. |
| **Visualización (BI)** | Looker Studio | Dashboard interactivo conectado a la vista limpia, garantizando alto rendimiento con costo cero de cómputo. |
| **Orquestación** | GitHub Actions | Automatización programada (cron job) para ejecutar el pipeline de Python diariamente en la nube. |

### ⏱️ Orquestación y Timezones (Cierre de Caja)
El flujo Batch está orquestado mediante GitHub Actions con una expresión Cron configurada estratégicamente para el cierre de operaciones. Dado que los servidores de GitHub operan en **UTC**, se aplicó un offset de +4 horas para coincidir con el huso horario local (UTC-4, Santa Cruz, Bolivia). El ETL se dispara exactamente a las 10:05 PM (02:05 AM UTC), garantizando que el Dashboard esté actualizado a las 10:15 PM para la auditoría de caja nocturna.

### ⚠️ Consideraciones Técnicas y Trade-offs
* **Ausencia de transacciones ACID nativas:** Al emplear Google Sheets como base de datos operacional (OLTP) acoplada a AppSheet, se asume el riesgo de concurrencia en el cálculo de inventario si se registran transacciones simultáneas *offline*. Dado que el contexto del MVP es para un único punto de venta (un solo usuario concurrente), el riesgo es mínimo. 
* **Mitigación:** Como control de calidad de datos, se establece una auditoría manual de conciliación a fin de mes para cruzar las métricas del inventario físico contra el stock digital.

## Fase 2: Desarrollo del Módulo de Ingesta (AppSheet)

Para garantizar la adopción del sistema por parte del usuario final (quien no posee habilidades técnicas), se descartó el uso de un POS tradicional en PC. En su lugar, se implementó una interfaz móvil No-Code utilizando **AppSheet** conectada al Data Lake crudo en Google Sheets.

### Características Técnicas de la Ingesta:
* **Escaneo Óptico (Barcode Scanner):** Se habilitó la propiedad `Scannable` en los campos `id_producto` (Tablas: Productos y Detalle_Ventas). Esto permite usar la cámara del smartphone para registrar productos y ventas en milisegundos.
* **Catálogo Visual Dinámico (Hardware Integration):** Se configuraron columnas de tipo `Image` con `Labels` duales en AppSheet, permitiendo al usuario utilizar la cámara nativa del smartphone para fotografiar productos físicos en tiempo real. Esto elimina la fricción de buscar imágenes en internet, generando un catálogo visual autogestionable y almacenado automáticamente en Google Drive.
* **Tipado Estricto en Origen:** Para evitar errores de calidad de datos (Data Quality) antes del proceso ETL, se forzaron los siguientes tipos de datos en la app:
  * `Price`: Para montos financieros (precio_compra, precio_venta, subtotal, monto_gasto).
  * `DateTime` / `Date`: Para control temporal exacto de transacciones.
  * `Number`: Para control de inventarios y cantidades.
  * `Enum`: Para estandarizar categorías categóricas (ej. tipo_gasto: Fijo/Variable, metodo_pago: Efectivo/Tarjeta/QR), minimizando el error humano por entrada de texto libre.
  
### Experiencia de Usuario (UX) y Lógica Transaccional
Para asegurar la adopción del sistema por parte del dueño y garantizar la consistencia de los datos, se implementaron las siguientes reglas de negocio en AppSheet:
* **Relaciones Padre-Hijo (Parent-Child):** Se estructuró un vínculo estricto entre `Detalle_Ventas` y `Ventas` mediante referencias (`Ref`) y la propiedad `Is a part of`. Esto genera una experiencia de "Carrito de Compras" sin fricción y asegura la integridad referencial desde el origen (evitando registros huérfanos).
* **Interfaz Minimalista:** Se configuró una barra de navegación inferior exclusiva para la operación diaria (`Ventas`, `Productos`, `Gastos`). Tablas de administración (como `Categorías`) se relegaron a un menú secundario tipo hamburguesa, previniendo alteraciones accidentales durante el flujo de caja.

### Evolución de la Arquitectura: De Transaccional a Analítico (Batch Processing)
Inicialmente, el cálculo de inventario se gestionaba mediante Bots y triggers (Event-Driven) dentro de AppSheet. Sin embargo, para evitar problemas de concurrencia, bloqueos de escritura y lentitud en la aplicación móvil, **se tomó la decisión arquitectónica de eliminar la lógica pesada de la capa transaccional**. 
Actualmente, AppSheet opera puramente como una herramienta de captura (alta velocidad), delegando el cálculo de stocks y finanzas al proceso ETL (procesamiento por lotes o *Batch*) gestionado por Python y DuckDB.

## Fase 3: Pipeline ETL & Modelado Analítico (Python + SQL + DuckDB)

Para desacoplar la base de datos transaccional del entorno analítico, se implementó un pipeline automatizado y blindado:

1. **Extracción y Data Quality:** Python extrae los datos crudos vía API. Se implementaron reglas estrictas de limpieza: forzado de tipos numéricos (evitando errores de campos vacíos) y **normalización y blindaje de fechas** (formato estricto `YYYY-MM-DD` y manejo de nulos) para asegurar la compatibilidad con Looker Studio.
2. **Transformación (DuckDB en memoria):** Se procesaron 3 modelos analíticos independientes utilizando SQL columnar ultra-rápido:
   * **Modelo de Ventas:** Cruce de transacciones aplicando dimensiones lentamente cambiantes (SCD) para congelar precios históricos y calcular Ganancia Bruta por ítem.
   * **Modelo de Inventario (Alertas):** Cálculo del `stock_actual` basado en la resta totalizada. Se aplicó ingeniería de características (*Feature Engineering*) para generar estados categóricos inteligentes (`OK`, `ALERTA: Stock Bajo`, `REVISAR: Stock Negativo`).
   * **Modelo Financiero:** Consolidación de ingresos vs. la tabla de `Gastos` para calcular la **Utilidad Neta Real** del negocio.
3. **Carga Idempotente No Destructiva (Load Seguro):** Para garantizar la estabilidad del dashboard, se diseñó una estrategia de carga mediante "Soft-Reset" (`hoja.clear()`). El script borra únicamente el contenido de los datos viejos y escribe los nuevos, manteniendo intactos los IDs internos de las pestañas de Google Sheets. Esto previene que Looker Studio pierda la conexión por la eliminación física de las hojas.

## Fase 4: Visualización e Inteligencia de Negocios (BI)

Dashboard interactivo en **Looker Studio** diseñado para lectura rápida por parte de usuarios no técnicos (el dueño de la tienda).

* **Métricas de Impacto (KPIs):** Tarjeta de resultados (Scorecard) destacando la **Utilidad Neta Real**, resolviendo directamente el problema de negocio planteado (fuga por gastos fijos).
* **Semáforo de Inventario (Formato Condicional):** Tablas dinámicas conectadas al modelo de DuckDB que interpretan las alertas de stock. Si un producto cae por debajo del umbral, la fila cambia de color automáticamente (Amarillo/Rojo), pasando de un reporte pasivo a un sistema de notificaciones visuales accionables.

## 5. Gobernanza y Calidad de Datos (Reglas de Operación)
Al utilizar una hoja de cálculo como capa de almacenamiento crudo (Data Lake), se detectó que la eliminación parcial de registros (borrar contenido de celdas en lugar de eliminar la fila completa) generaba dimensiones `null` y métricas en `0` durante el procesamiento en DuckDB. 
Para mitigar esto, se estableció una política estricta de Gobernanza de Datos en la interfaz operacional:
* Toda eliminación de registros transaccionales debe realizarse exclusivamente a través de los métodos nativos de AppSheet (CRUD).
* Si se requiere intervención manual en la base de datos cruda, es imperativo aplicar un *Hard Delete* (eliminar la fila completa en Google Sheets) para evitar la ingesta de espacios en blanco durante el escaneo de pandas.