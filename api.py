from flask import Flask, jsonify, request
import requests 
import sqlite3 
import os
import logging

app = Flask(__name__)

if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

DATABASE_FILE = 'inventario.db'
EXCHANGE_RATE_API_KEY = "b13c1920a6582926f6d00078" 
DEFAULT_TASA_CAMBIO_USD_CLP = 980.0 

def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False) 
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            stock_casa_matriz INTEGER DEFAULT 0 CHECK(stock_casa_matriz >= 0)
        )
    ''')
    app.logger.info("Tabla 'productos' verificada/creada.")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sucursales_maestras (
            id_sucursal TEXT PRIMARY KEY,
            nombre_sucursal TEXT NOT NULL UNIQUE
        )
    ''')
    app.logger.info("Tabla 'sucursales_maestras' verificada/creada.")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos_sucursales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_codigo TEXT NOT NULL,
            sucursal_id TEXT NOT NULL,
            cantidad INTEGER DEFAULT 0 CHECK(cantidad >= 0),
            precio_local REAL DEFAULT 0.0,
            FOREIGN KEY (producto_codigo) REFERENCES productos (codigo) ON DELETE CASCADE,
            FOREIGN KEY (sucursal_id) REFERENCES sucursales_maestras (id_sucursal) ON DELETE CASCADE,
            UNIQUE (producto_codigo, sucursal_id)
        )
    ''')
    app.logger.info("Tabla 'productos_sucursales' verificada/creada.")
    conn.commit() 
    cursor.execute("SELECT COUNT(*) FROM sucursales_maestras")
    if cursor.fetchone()[0] == 0:
        sucursales_iniciales = [
            ("S01", "Sucursal Capital"), ("S02", "Sucursal Valparaíso"),
            ("S03", "Sucursal Concepción"), ("S04", "Sucursal Antofagasta")
        ]
        cursor.executemany("INSERT INTO sucursales_maestras (id_sucursal, nombre_sucursal) VALUES (?, ?)", sucursales_iniciales)
        conn.commit()
        app.logger.info("Tabla 'sucursales_maestras' poblada con datos iniciales.")
    conn.close()

def obtener_tasa_cambio_actual_usd_clp():
    moneda_local_iso = "CLP"
    if not EXCHANGE_RATE_API_KEY or EXCHANGE_RATE_API_KEY == "TU_API_KEY_AQUI":
        app.logger.error("API Key para ExchangeRate-API no configurada. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    api_url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
    app.logger.info(f"Intentando obtener tasa de cambio desde ExchangeRate-API para USD a {moneda_local_iso}...")
    try:
        response = requests.get(api_url, timeout=10) 
        response.raise_for_status()
        data = response.json()
        if data.get("result") == "success":
            tasa = data.get("conversion_rates", {}).get(moneda_local_iso)
            if tasa:
                app.logger.info(f"Tasa USD a {moneda_local_iso} obtenida: {tasa}")
                return float(tasa)
        app.logger.warning(f"No se encontró tasa para {moneda_local_iso} o API devolvió error. Usando valor por defecto. Respuesta: {data if 'data' in locals() else 'No data object'}")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except requests.exceptions.RequestException as e: 
        app.logger.error(f"Error de red/HTTP al contactar ExchangeRate-API: {e}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except ValueError as e: 
        app.logger.error(f"Error al decodificar JSON de ExchangeRate-API: {e}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except Exception as e: 
        app.logger.error(f"Error inesperado en obtener_tasa_cambio_actual_usd_clp: {type(e).__name__} - {e}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP

@app.route('/api/producto/<string:codigo_producto>', methods=['GET'])
def obtener_info_producto(codigo_producto):
    producto_codigo_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (producto_codigo_upper,))
    producto_db = cursor.fetchone()
    if not producto_db:
        conn.close()
        return jsonify({"error": "Producto no encontrado", "codigo": producto_codigo_upper}), 404
    cursor.execute('''
        SELECT ps.sucursal_id, sm.nombre_sucursal, ps.cantidad, ps.precio_local
        FROM productos_sucursales ps
        JOIN sucursales_maestras sm ON ps.sucursal_id = sm.id_sucursal
        WHERE ps.producto_codigo = ?
    ''', (producto_codigo_upper,))
    sucursales_info = [dict(row) for row in cursor.fetchall()]
    conn.close()
    tasa_actual_usd_clp = obtener_tasa_cambio_actual_usd_clp()
    respuesta = {
        "codigo_producto": producto_db["codigo"], 
        "nombre_producto": producto_db["nombre"],
        "stock_casa_matriz": producto_db["stock_casa_matriz"],
        "sucursales": sucursales_info, 
        "tasa_cambio_a_usd": tasa_actual_usd_clp
    }
    return jsonify(respuesta)

@app.route('/api/productos', methods=['GET'])
def obtener_todos_los_productos():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo, nombre FROM productos ORDER BY nombre")
    productos_db = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(productos_db)

@app.route('/api/sucursales_maestras', methods=['GET'])
def obtener_sucursales_maestras():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id_sucursal, nombre_sucursal FROM sucursales_maestras ORDER BY nombre_sucursal")
    sucursales_db = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(sucursales_db)

@app.route('/api/producto', methods=['POST'])
def crear_producto():
    if not request.json:
        return jsonify({"error": "La solicitud debe ser JSON"}), 400
    codigo_producto = request.json.get('codigo_producto', '').strip().upper()
    nombre_producto = request.json.get('nombre_producto', '').strip()
    try:
        stock_casa_matriz = int(request.json.get('stock_casa_matriz', 0))
        if stock_casa_matriz < 0:
             return jsonify({"error": "El stock en casa matriz no puede ser negativo"}), 400
    except ValueError:
        return jsonify({"error": "El stock en casa matriz debe ser un número entero"}), 400
    if not codigo_producto or not nombre_producto:
        return jsonify({"error": "El código y el nombre del producto son requeridos"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO productos (codigo, nombre, stock_casa_matriz) VALUES (?, ?, ?)",
            (codigo_producto, nombre_producto, stock_casa_matriz)
        )
        conn.commit()
        producto_creado = {
            "codigo_producto": codigo_producto, 
            "nombre_producto": nombre_producto,
            "stock_casa_matriz": stock_casa_matriz, 
            "sucursales": [] 
        }
        return jsonify(producto_creado), 201 
    except sqlite3.IntegrityError: 
        return jsonify({"error": f"Un producto con el código '{codigo_producto}' ya existe"}), 409
    finally:
        conn.close()

@app.route('/api/sucursal', methods=['POST'])
def crear_sucursal_maestra():
    """Crea una nueva sucursal maestra."""
    if not request.json:
        return jsonify({"error": "La solicitud debe ser JSON"}), 400
    
    id_sucursal = request.json.get('id_sucursal', '').strip().upper()
    nombre_sucursal = request.json.get('nombre_sucursal', '').strip()

    if not id_sucursal or not nombre_sucursal:
        return jsonify({"error": "El ID y el nombre de la sucursal son requeridos"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO sucursales_maestras (id_sucursal, nombre_sucursal) VALUES (?, ?)",
            (id_sucursal, nombre_sucursal)
        )
        conn.commit()
        sucursal_creada = {
            "id_sucursal": id_sucursal,
            "nombre_sucursal": nombre_sucursal
        }
        app.logger.info(f"Sucursal '{nombre_sucursal}' ({id_sucursal}) creada exitosamente.")
        return jsonify(sucursal_creada), 201 # 201 Created
    except sqlite3.IntegrityError: 
        # Puede ser por ID duplicado (PRIMARY KEY) o nombre duplicado (UNIQUE)
        app.logger.warning(f"Intento de crear sucursal con ID '{id_sucursal}' o nombre '{nombre_sucursal}' duplicado.")
        return jsonify({"error": f"Ya existe una sucursal con el ID '{id_sucursal}' o el nombre '{nombre_sucursal}'"}), 409 # 409 Conflict
    except Exception as e:
        app.logger.error(f"Error inesperado al crear sucursal: {e}")
        return jsonify({"error": "Error interno del servidor al crear la sucursal"}), 500
    finally:
        conn.close()


@app.route('/api/producto/<string:codigo_producto>/restock_matriz', methods=['POST'])
def restock_casa_matriz(codigo_producto):
    codigo_producto_upper = codigo_producto.upper()
    if not request.json:
        return jsonify({"error": "La solicitud debe ser JSON"}), 400
    try:
        cantidad_a_agregar = int(request.json.get('cantidad_a_agregar'))
        if cantidad_a_agregar <= 0:
            return jsonify({"error": "La cantidad a agregar debe ser un número positivo."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "La cantidad a agregar debe ser un número entero."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db = cursor.fetchone()
        if not producto_db:
            return jsonify({"error": "Producto no encontrado"}), 404
        
        stock_actual = producto_db["stock_casa_matriz"]
        nuevo_stock = stock_actual + cantidad_a_agregar
        
        cursor.execute(
            "UPDATE productos SET stock_casa_matriz = ? WHERE codigo = ?",
            (nuevo_stock, codigo_producto_upper)
        )
        conn.commit()
        
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_actualizado_db = cursor.fetchone()

        return jsonify({
            "mensaje": f"Stock de '{codigo_producto_upper}' en casa matriz actualizado a {nuevo_stock}.",
            "producto": dict(producto_actualizado_db)
        }), 200
        
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de base de datos al hacer restock en casa matriz: {e}")
        return jsonify({"error": "Error interno de la base de datos"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/producto/<string:codigo_producto>/sucursal', methods=['POST'])
def agregar_o_actualizar_producto_en_sucursal(codigo_producto):
    codigo_producto_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db = cursor.fetchone()
        if not producto_db:
            return jsonify({"error": "Producto no encontrado"}), 404
        
        stock_anterior_casa_matriz = producto_db["stock_casa_matriz"]
        
        if not request.json: return jsonify({"error": "La solicitud debe ser JSON"}), 400
        id_sucursal = request.json.get('id_sucursal', '').strip().upper()
        try:
            nueva_cantidad_sucursal = int(request.json.get('cantidad'))
            precio_local = float(request.json.get('precio_local'))
            if nueva_cantidad_sucursal < 0 or precio_local < 0:
                return jsonify({"error": "La cantidad y el precio no pueden ser negativos"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "La cantidad debe ser un entero y el precio local un número válido"}), 400
        if not id_sucursal: return jsonify({"error": "El ID de sucursal es requerido"}), 400
        cursor.execute("SELECT id_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal,))
        if not cursor.fetchone(): return jsonify({"error": f"El ID de sucursal '{id_sucursal}' no es válido."}), 400

        cantidad_anterior_sucursal = 0
        cursor.execute("SELECT cantidad FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?", (codigo_producto_upper, id_sucursal))
        producto_en_sucursal_db = cursor.fetchone()
        if producto_en_sucursal_db: cantidad_anterior_sucursal = producto_en_sucursal_db["cantidad"]
        
        diferencia_stock_movido = nueva_cantidad_sucursal - cantidad_anterior_sucursal
        nuevo_stock_casa_matriz = stock_anterior_casa_matriz - diferencia_stock_movido

        if nuevo_stock_casa_matriz < 0:
            return jsonify({
                "error": "Stock insuficiente en casa matriz.",
                "stock_disponible_casa_matriz": stock_anterior_casa_matriz,
                "requerido_para_mover_a_sucursal": diferencia_stock_movido 
            }), 400 

        cursor.execute("UPDATE productos SET stock_casa_matriz = ? WHERE codigo = ?", (nuevo_stock_casa_matriz, codigo_producto_upper))
        
        cursor.execute('''
            INSERT INTO productos_sucursales (producto_codigo, sucursal_id, cantidad, precio_local)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(producto_codigo, sucursal_id) DO UPDATE SET
                cantidad = excluded.cantidad,
                precio_local = excluded.precio_local
        ''', (codigo_producto_upper, id_sucursal, nueva_cantidad_sucursal, precio_local))
        
        conn.commit()
        mensaje = f"Producto '{codigo_producto_upper}' asignado/actualizado en sucursal '{id_sucursal}'. Stock de casa matriz ajustado."
        
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db_actualizado = cursor.fetchone()
        cursor.execute('''
            SELECT ps.sucursal_id, sm.nombre_sucursal, ps.cantidad, ps.precio_local
            FROM productos_sucursales ps JOIN sucursales_maestras sm ON ps.sucursal_id = sm.id_sucursal
            WHERE ps.producto_codigo = ?
        ''', (codigo_producto_upper,))
        sucursales_info_actualizadas = [dict(row) for row in cursor.fetchall()]
        
        producto_respuesta = {
            "codigo_producto": producto_db_actualizado["codigo"], 
            "nombre_producto": producto_db_actualizado["nombre"],
            "stock_casa_matriz": producto_db_actualizado["stock_casa_matriz"],
            "sucursales": sucursales_info_actualizadas
        }
        return jsonify({"mensaje": mensaje, "producto": producto_respuesta}), 200
    
    except sqlite3.Error as e:
        conn.rollback() 
        app.logger.error(f"Error de base de datos al asignar producto a sucursal: {e}")
        return jsonify({"error": "Error interno de la base de datos"}), 500
    finally:
        if conn: conn.close()

if __name__ == '__main__':
    import logging 
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
        app.logger.setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.DEBUG)
        app.logger.setLevel(logging.DEBUG)
    
    if os.path.exists(DATABASE_FILE):
        app.logger.info(f"Usando archivo de base de datos existente: '{DATABASE_FILE}'.")
    
    init_db() 
    app.logger.info(f"Base de datos '{DATABASE_FILE}' inicializada y lista para usarse.")
    
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
