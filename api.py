from flask import Flask, jsonify, request
import requests # Para hacer llamadas a APIs externas
import sqlite3 # Para la base de datos SQLite
import os # Para construir la ruta a la base de datos

app = Flask(__name__)

# --- Configuración de la Base de Datos ---
DATABASE_FILE = 'inventario.db' # Nombre del archivo de la base de datos

def get_db_connection():
    """Crea y devuelve una conexión a la base de datos."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row # Permite acceder a las columnas por nombre
    return conn

def init_db():
    """Inicializa la base de datos y crea las tablas si no existen."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tabla de Productos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            stock_casa_matriz INTEGER DEFAULT 0
        )
    ''')

    # Tabla de Sucursales Maestras
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sucursales_maestras (
            id_sucursal TEXT PRIMARY KEY,
            nombre_sucursal TEXT NOT NULL UNIQUE
        )
    ''')

    # Tabla de Productos en Sucursales (relación muchos a muchos con atributos)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos_sucursales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_codigo TEXT NOT NULL,
            sucursal_id TEXT NOT NULL,
            cantidad INTEGER DEFAULT 0,
            precio_local REAL DEFAULT 0.0,
            FOREIGN KEY (producto_codigo) REFERENCES productos (codigo) ON DELETE CASCADE,
            FOREIGN KEY (sucursal_id) REFERENCES sucursales_maestras (id_sucursal) ON DELETE CASCADE,
            UNIQUE (producto_codigo, sucursal_id) -- Un producto solo puede estar una vez por sucursal
        )
    ''')
    conn.commit()

    # Poblar sucursales maestras si la tabla está vacía (solo la primera vez)
    cursor.execute("SELECT COUNT(*) FROM sucursales_maestras")
    if cursor.fetchone()[0] == 0:
        sucursales_iniciales = [
            ("S01", "Sucursal Capital"),
            ("S02", "Sucursal Valparaíso"),
            ("S03", "Sucursal Concepción"),
            ("S04", "Sucursal Antofagasta")
        ]
        cursor.executemany("INSERT INTO sucursales_maestras (id_sucursal, nombre_sucursal) VALUES (?, ?)", sucursales_iniciales)
        conn.commit()
        app.logger.info("Tabla 'sucursales_maestras' poblada con datos iniciales.")

    conn.close()


DEFAULT_TASA_CAMBIO_USD_CLP = 980.0 # Valor de respaldo
EXCHANGE_RATE_API_KEY = "b13c1920a6582926f6d00078" 

def obtener_tasa_cambio_actual_usd_clp():
    moneda_local_iso = "CLP"
    
    if EXCHANGE_RATE_API_KEY == "TU_API_KEY_AQUI" or not EXCHANGE_RATE_API_KEY:
        app.logger.error("API Key para ExchangeRate-API no configurada correctamente. Usando valor por defecto para tasa de cambio.")
        return DEFAULT_TASA_CAMBIO_USD_CLP

    api_url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
    
    
    app.logger.info(f"Intentando obtener tasa de cambio desde ExchangeRate-API: https://v6.exchangerate-api.com/v6/***API_KEY_HIDDEN***/latest/USD")
    
    try:
        response = requests.get(api_url, timeout=10) 
        app.logger.debug(f"Respuesta de ExchangeRate-API - Status: {response.status_code}")
        response.raise_for_status() 
        
        data = response.json()
        app.logger.debug(f"Respuesta JSON completa de ExchangeRate-API: {data}") 
        
        if data.get("result") == "success":
            tasa = data.get("conversion_rates", {}).get(moneda_local_iso)
            if tasa:
                app.logger.info(f"Tasa de cambio USD a {moneda_local_iso} obtenida de ExchangeRate-API: {tasa}")
                return float(tasa)
            else:
                app.logger.warning(f"No se encontró la tasa para {moneda_local_iso} en la respuesta de ExchangeRate-API. Usando valor por defecto. Respuesta: {data}")
                return DEFAULT_TASA_CAMBIO_USD_CLP
        else:
            # Loguear el tipo de error específico que devuelve la API
            error_type = data.get('error-type', 'Error desconocido de API')
            app.logger.error(f"ExchangeRate-API devolvió un error: {error_type}. Usando valor por defecto.")
            return DEFAULT_TASA_CAMBIO_USD_CLP
            
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout al contactar ExchangeRate-API. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except requests.exceptions.HTTPError as e:
        app.logger.error(f"Error HTTP al contactar ExchangeRate-API: {e}. Status: {e.response.status_code}. Respuesta: {e.response.text}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except requests.exceptions.RequestException as e: 
        app.logger.error(f"Error de red al contactar ExchangeRate-API: {e}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except ValueError as e: # Si response.json() falla
        app.logger.error(f"Error al decodificar JSON de ExchangeRate-API: {e}. Respuesta: {response.text if 'response' in locals() else 'N/A'}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP
    except Exception as e: 
        app.logger.error(f"Error inesperado en obtener_tasa_cambio_actual_usd_clp: {type(e).__name__} - {e}. Usando valor por defecto.")
        return DEFAULT_TASA_CAMBIO_USD_CLP

# --- Endpoints de la API

@app.route('/api/producto/<string:codigo_producto>', methods=['GET'])
def obtener_info_producto(codigo_producto):
    producto_codigo_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM productos WHERE codigo = ?", (producto_codigo_upper,))
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
        return jsonify({"error": "Solicitud debe ser JSON"}), 400

    codigo_producto = request.json.get('codigo_producto', '').strip().upper()
    nombre_producto = request.json.get('nombre_producto', '').strip()
    try:
        stock_casa_matriz = int(request.json.get('stock_casa_matriz', 0))
        if stock_casa_matriz < 0:
             return jsonify({"error": "stock_casa_matriz no puede ser negativo"}), 400
    except ValueError:
        return jsonify({"error": "stock_casa_matriz debe ser un número entero"}), 400

    if not codigo_producto or not nombre_producto:
        return jsonify({"error": "codigo_producto y nombre_producto son requeridos"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO productos (codigo, nombre, stock_casa_matriz) VALUES (?, ?, ?)",
            (codigo_producto, nombre_producto, stock_casa_matriz)
        )
        conn.commit()
        producto_creado = {
            "codigo": codigo_producto,
            "nombre": nombre_producto,
            "stock_casa_matriz": stock_casa_matriz,
            "sucursales": []
        }
        return jsonify(producto_creado), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Producto con código '{codigo_producto}' ya existe"}), 409
    finally:
        conn.close()


@app.route('/api/producto/<string:codigo_producto>/sucursal', methods=['POST'])
def agregar_o_actualizar_producto_en_sucursal(codigo_producto):
    codigo_producto_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo FROM productos WHERE codigo = ?", (codigo_producto_upper,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": "Producto no encontrado"}), 404

    if not request.json:
        conn.close()
        return jsonify({"error": "Solicitud debe ser JSON"}), 400

    id_sucursal = request.json.get('id_sucursal', '').strip().upper()
    try:
        cantidad = int(request.json.get('cantidad'))
        precio_local = float(request.json.get('precio_local'))
        if cantidad < 0 or precio_local < 0:
            conn.close()
            return jsonify({"error": "Cantidad y precio no pueden ser negativos"}), 400
    except (ValueError, TypeError):
        conn.close()
        return jsonify({"error": "cantidad debe ser un número entero y precio_local un número válido"}), 400

    if not id_sucursal:
        conn.close()
        return jsonify({"error": "id_sucursal es requerido"}), 400
    
    cursor.execute("SELECT id_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"error": f"ID de sucursal '{id_sucursal}' no es válido."}), 400
    
    try:
        cursor.execute('''
            INSERT INTO productos_sucursales (producto_codigo, sucursal_id, cantidad, precio_local)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(producto_codigo, sucursal_id) DO UPDATE SET
                cantidad = excluded.cantidad,
                precio_local = excluded.precio_local
        ''', (codigo_producto_upper, id_sucursal, cantidad, precio_local))
        conn.commit()
        mensaje = f"Producto '{codigo_producto_upper}' asignado/actualizado en sucursal '{id_sucursal}'."
        
        cursor.execute("SELECT * FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db = cursor.fetchone()
        cursor.execute('''
            SELECT ps.sucursal_id, sm.nombre_sucursal, ps.cantidad, ps.precio_local
            FROM productos_sucursales ps
            JOIN sucursales_maestras sm ON ps.sucursal_id = sm.id_sucursal
            WHERE ps.producto_codigo = ?
        ''', (codigo_producto_upper,))
        sucursales_info = [dict(row) for row in cursor.fetchall()]
        
        producto_actualizado = dict(producto_db)
        producto_actualizado["sucursales"] = sucursales_info

        return jsonify({"mensaje": mensaje, "producto": producto_actualizado}), 200
    
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de base de datos al asignar producto a sucursal: {e}")
        return jsonify({"error": "Error interno de base de datos"}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.DEBUG) 
    
    init_db()
    app.logger.info(f"Base de datos '{DATABASE_FILE}' inicializada y lista.")
    
    app.run(host='0.0.0.0', port=5001, debug=True)
