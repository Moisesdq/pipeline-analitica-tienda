# Proyecto: Modernización de Datos para Tienda de Barrio (MVP)

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
| `stock_actual` | INT | Default 0 | Inventario disponible en tienda |

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
| `subtotal` | DECIMAL(10,2)| Not Null | cantidad * precio_venta |

### Tabla: Gastos
| Campo | Tipo de Datos | Atributos | Descripción |
| :--- | :--- | :--- | :--- |
| `id_gasto` | INT | PK, Auto_Increment | Identificador del egreso |
| `fecha` | DATE | Not Null | Fecha del pago |
| `tipo_gasto` | VARCHAR(20) | Not Null | 'Fijo' o 'Variable' |
| `descripcion` | VARCHAR(150)| Not Null | Detalle (Ej. 'Luz Marzo') |
| `monto` | DECIMAL(10,2)| Not Null | Cantidad de dinero pagada |

## 3. Arquitectura de Datos (Modern Data Stack Ligero)

Para este MVP, se ha diseñado un pipeline de datos tipo ELT (Extract, Load, Transform) optimizado para bajo costo y alta escalabilidad. El flujo se divide en las siguientes capas:

| Capa del Pipeline | Tecnología Utilizada | Función Específica |
| :--- | :--- | :--- |
| **Ingesta (Operacional)** | AppSheet + Google Sheets | Aplicación móvil no-code para captura de datos en el punto de venta (escaneo de códigos de barras) con almacenamiento crudo en hojas de cálculo. |
| **Extracción (Extract)** | Python (Google Sheets API) | Script que lee los datos operacionales de forma segura mediante credenciales de servicio. |
| **Procesamiento (Transform)** | DuckDB | Motor SQL analítico en memoria utilizado dentro de Python para cruzar ventas, calcular márgenes y estructurar el modelo analítico. |
|3. **Carga y Almacenamiento (Load):** Para mantener una infraestructura simplificada y de costo cero (aprovechando el Free Tier), no se utiliza un Data Warehouse externo. En su lugar, el DataFrame resultante procesado por DuckDB se carga directamente como una vista materializada en una nueva pestaña (`BI_Ventas_Modeladas`) dentro del mismo Google Sheets. Looker Studio se conecta exclusivamente a esta capa limpia, garantizando un rendimiento óptimo en la visualización sin incurrir en costos de licenciamiento o cómputo en la nube. |
| **Visualización (BI)** | Looker Studio | Dashboard interactivo optimizado para dispositivos móviles con los KPIs críticos del negocio. |
| **Orquestación** | GitHub Actions | Automatización del pipeline (cron job) para ejecutar la ingesta y transformación de forma programada diariamente. |

## ⚠️ Consideraciones Técnicas y Trade-offs
* **Ausencia de transacciones ACID nativas:** Al emplear Google Sheets como base de datos operacional (OLTP) acoplada a AppSheet, se asume el riesgo de concurrencia en el cálculo de inventario si se registran transacciones simultáneas *offline*. Dado que el contexto del MVP es para un único punto de venta (un solo usuario concurrente), el riesgo es mínimo. 
* **Mitigación:** Como control de calidad de datos, se establece una auditoría manual de conciliación a fin de mes para cruzar las métricas del inventario físico contra el stock digital.

## Fase 2: Desarrollo del Módulo de Ingesta (AppSheet)

Para garantizar la adopción del sistema por parte del usuario final (quien no posee habilidades técnicas), se descartó el uso de un POS tradicional en PC. En su lugar, se implementó una interfaz móvil No-Code utilizando **AppSheet** conectada al Data Lake crudo en Google Sheets.

### Características Técnicas de la Ingesta:
* **Escaneo Óptico (Barcode Scanner):** Se habilitó la propiedad `Scannable` en los campos `id_producto` (Tablas: Productos y Detalle_Ventas). Esto permite usar la cámara del smartphone para registrar productos y ventas en milisegundos.
* **Tipado Estricto en Origen:** Para evitar errores de calidad de datos (Data Quality) antes del proceso ETL, se forzaron los siguientes tipos de datos en la app:
  * `Price`: Para montos financieros (precio_compra, precio_venta, subtotal, monto_gasto).
  * `DateTime` / `Date`: Para control temporal exacto de transacciones.
  * `Number`: Para control de inventarios y cantidades.
  * `Enum`: Para estandarizar categorías categóricas (ej. tipo_gasto: Fijo/Variable, metodo_pago: Efectivo/Tarjeta/QR), minimizando el error humano por entrada de texto libre.
 
### Experiencia de Usuario (UX) y Lógica Transaccional
Para asegurar la adopción del sistema por parte del dueño y garantizar la consistencia de los datos, se implementaron las siguientes reglas de negocio en AppSheet:
* **Relaciones Padre-Hijo (Parent-Child):** Se estructuró un vínculo estricto entre `Detalle_Ventas` y `Ventas` mediante referencias (`Ref`) y la propiedad `Is a part of`. Esto genera una experiencia de "Carrito de Compras" sin fricción y asegura la integridad referencial desde el origen (evitando registros huérfanos).
* **Interfaz Minimalista:** Se configuró una barra de navegación inferior exclusiva para la operación diaria (`Ventas`, `Productos`, `Gastos`). Tablas de administración (como `Categorías`) se relegaron a un menú secundario tipo hamburguesa, previniendo alteraciones accidentales durante el flujo de caja.

### Automatización de Inventario en Tiempo Real (Event-Driven)
Para resolver la necesidad operacional de mantener el inventario sincronizado al instante en el punto de venta, se implementó un trigger lógico híbrido dentro de la capa de ingesta:
1. **Acción de Decremento (`Productos`):** Se programó una expresión analítica utilizando `MAXROW` y `SELECT` para identificar dinámicamente la última transacción del producto escaneado y restar la cantidad del stock físico.
2. **Puente de Referencia (`Detalle_Ventas`):** Se creó una acción puente encargada de resolver la relación de entidades y apuntar al registro indexado.
3. **Orquestación mediante Bots (AppSheet Automation):** Se desplegó un Bot reactivo que escucha exclusivamente el evento `Adds only` en el carrito de compras. Al confirmarse la línea de venta, el bot dispara el flujo de actualización en milisegundos, garantizando consistencia operacional en el dispositivo móvil y en el almacenamiento crudo (Google Sheets).

## Fase 3: Pipeline ETL & Modelado Analítico (Python + SQL + DuckDB)
Con los datos operacionales capturados de forma segura, se diseñó e implementó un pipeline de extracción, transformación y carga (ETL) programático para desacoplar la base de datos transaccional del entorno analítico:

1. **Extracción (Extract):** Utilizando Python junto con las librerías `gspread` y `google-auth`, el script se autentica de forma segura mediante una Cuenta de Servicio (Service Account) en Google Cloud Platform (GCP) para extraer las tablas crudas (`Ventas`, `Detalle_Ventas`, `Productos` y `Gastos`) hacia DataFrames de `Pandas` en memoria RAM.
2. **Transformación (Transform):** Se integró **DuckDB** como motor de base de datos analítico columnar en-memoria. Mediante consultas SQL avanzadas (`JOINs`), se cruzaron las relaciones de las tablas y se realizó ingeniería de características (*Feature Engineering*) para calcular métricas financieras críticas en tiempo real (ej. `Ganancia Bruta = (Precio Venta - Precio Compra) * Cantidad`).
3. **Carga (Load):** Los datos completamente modelados y limpios se consolidan en una capa lista para el consumo de Inteligencia de Negocios (BI), optimizando el rendimiento de las consultas y evitando el procesamiento costoso en la herramienta de visualización.

## Fase 4: Visualización e Inteligencia de Negocios (BI)
Para la capa de presentación y consumo final de los datos, se desarrolló un dashboard interactivo en **Looker Studio** conectado directamente a la vista analítica materializada.

* **Integración Optimizada:** Conexión nativa con la tabla modelada (`BI_Ventas_Modeladas`), garantizando que la herramienta de BI actúe puramente como capa de visualización, delegando el cómputo pesado al motor de base de datos en Python.
* **Métricas Clave (KPIs):** Desarrollo de tarjetas de resultados dinámicas para monitorear la salud financiera del negocio: Ingresos Totales, Ganancia Real y Margen de Rentabilidad.
* **Análisis Visual:** Implementación de gráficos de distribución (análisis de métodos de pago) y ranking de desempeño (Top productos por volumen de ventas) para facilitar la toma de decisiones estratégicas de los *stakeholders*.
