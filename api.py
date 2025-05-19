from flask import Flask, jsonify, request, Response
import requests 
import sqlite3 
import os
import time 
import queue 
import json 
import threading 
# from werkzeug.serving import حوالي # Esta línea no es necesaria y 'حوالي' no está definido

app = Flask(__name__)

DATABASE_FILE = 'inventario.db'
EXCHANGE_RATE_API_KEY = "b13c1920a6582926f6d00078" 
DEFAULT_TASA_CAMBIO_USD_CLP = 980.0 

sse_listeners = []
sse_listeners_lock = threading.Lock() 

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
    if not EXCHANGE_RATE_API_KEY or EXCHANGE_RATE_API_KEY == "TU_API_KEY_AQUI": # Placeholder check
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

def broadcast_stock_alert(evento_json_str):
    with sse_listeners_lock:
        app.logger.debug(f"API_SSE_BROADCAST: Transmitiendo a {len(sse_listeners)} listeners. Evento: {evento_json_str}")
        for listener_queue in list(sse_listeners): 
            try:
                listener_queue.put_nowait(evento_json_str)
            except queue.Full:
                app.logger.warning(f"API_SSE_BROADCAST: Cola de un listener llena. Evento no enviado a ese listener.")
            except Exception as e: 
                app.logger.error(f"API_SSE_BROADCAST: Error al poner en cola de listener: {e}")


@app.route('/api/producto/<string:codigo_producto>', methods=['GET'])
def obtener_info_producto(codigo_producto):
    # ... (sin cambios) ...
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
        "codigo_producto": producto_db["codigo"], "nombre_producto": producto_db["nombre"],
        "stock_casa_matriz": producto_db["stock_casa_matriz"],
        "sucursales": sucursales_info, "tasa_cambio_a_usd": tasa_actual_usd_clp
    }
    return jsonify(respuesta)

@app.route('/api/productos', methods=['GET'])
def obtener_todos_los_productos():
    # ... (sin cambios) ...
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codigo, nombre FROM productos ORDER BY nombre")
    productos_db = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(productos_db)

@app.route('/api/sucursales_maestras', methods=['GET'])
def obtener_sucursales_maestras():
    # ... (sin cambios) ...
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id_sucursal, nombre_sucursal FROM sucursales_maestras ORDER BY nombre_sucursal")
    sucursales_db = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(sucursales_db)

@app.route('/api/sucursal/<string:id_sucursal>/productos', methods=['GET'])
def obtener_productos_por_sucursal(id_sucursal):
    # ... (sin cambios) ...
    id_sucursal_upper = id_sucursal.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal_upper,))
    sucursal_db = cursor.fetchone()
    if not sucursal_db:
        conn.close()
        return jsonify({"error": "Sucursal no encontrada", "id_sucursal": id_sucursal_upper}), 404
    cursor.execute('''
        SELECT p.codigo AS codigo_producto, p.nombre AS nombre_producto, 
               ps.cantidad, ps.precio_local
        FROM productos p
        JOIN productos_sucursales ps ON p.codigo = ps.producto_codigo
        WHERE ps.sucursal_id = ? AND ps.cantidad > 0 
        ORDER BY p.nombre
    ''', (id_sucursal_upper,))
    productos_en_sucursal = [dict(row) for row in cursor.fetchall()]
    conn.close()
    tasa_actual_usd_clp = obtener_tasa_cambio_actual_usd_clp()
    return jsonify({
        "id_sucursal": id_sucursal_upper,
        "nombre_sucursal": sucursal_db["nombre_sucursal"],
        "productos": productos_en_sucursal,
        "tasa_cambio_a_usd": tasa_actual_usd_clp
    })

@app.route('/api/producto', methods=['POST'])
def crear_producto():
    # ... (modificado para usar broadcast_stock_alert si el stock es 0) ...
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
        if stock_casa_matriz == 0: # Si se crea con stock 0, también es una alerta
            evento_alerta = {
                "type": "stock_cero_matriz", # Tipo de evento específico para casa matriz
                "codigo_producto": codigo_producto,
                "nombre_producto": nombre_producto,
                "mensaje": f"¡ALERTA! Producto '{nombre_producto}' ({codigo_producto}) necesita restock en casa matriz (creado con stock 0)."
            }
            broadcast_stock_alert(json.dumps(evento_alerta))
            app.logger.info(f"Evento de stock cero en MATRIZ BROADCAST para {codigo_producto}")

        producto_creado = {
            "codigo_producto": codigo_producto, "nombre_producto": nombre_producto,
            "stock_casa_matriz": stock_casa_matriz, "sucursales": [] 
        }
        return jsonify(producto_creado), 201 
    except sqlite3.IntegrityError: 
        return jsonify({"error": f"Un producto con el código '{codigo_producto}' ya existe"}), 409
    finally:
        conn.close()

@app.route('/api/producto/<string:codigo_producto>', methods=['PUT'])
def actualizar_producto(codigo_producto):
    # ... (sin cambios) ...
    codigo_producto_upper = codigo_producto.upper()
    if not request.json:
        return jsonify({"error": "La solicitud debe ser JSON"}), 400
    nuevo_nombre = request.json.get('nombre_producto', '').strip()
    stock_casa_matriz_str = request.json.get('stock_casa_matriz') 
    if not nuevo_nombre and stock_casa_matriz_str is None:
        return jsonify({"error": "Se requiere al menos un campo para actualizar (nombre_producto o stock_casa_matriz)"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_actual = cursor.fetchone()
        if not producto_actual:
            conn.close()
            return jsonify({"error": "Producto no encontrado para actualizar"}), 404
        
        stock_anterior_casa_matriz = producto_actual["stock_casa_matriz"]
        nombre_producto_actual = producto_actual["nombre"]

        campos_a_actualizar = []
        valores_a_actualizar = []
        if nuevo_nombre:
            campos_a_actualizar.append("nombre = ?")
            valores_a_actualizar.append(nuevo_nombre)
        
        nuevo_stock_casa_matriz_val = None # Para la alerta SSE
        if stock_casa_matriz_str is not None:
            try:
                nuevo_stock_casa_matriz_val = int(stock_casa_matriz_str)
                if nuevo_stock_casa_matriz_val < 0:
                    conn.close()
                    return jsonify({"error": "El stock en casa matriz no puede ser negativo"}), 400
                campos_a_actualizar.append("stock_casa_matriz = ?")
                valores_a_actualizar.append(nuevo_stock_casa_matriz_val)
            except ValueError:
                conn.close()
                return jsonify({"error": "El stock en casa matriz debe ser un número entero"}), 400
        
        if not campos_a_actualizar: 
            conn.close()
            return jsonify({"error": "No se proporcionaron campos para actualizar"}), 400
        valores_a_actualizar.append(codigo_producto_upper) 
        query_actualizacion = f"UPDATE productos SET {', '.join(campos_a_actualizar)} WHERE codigo = ?"
        app.logger.debug(f"Query de actualización de producto: {query_actualizacion} con valores {valores_a_actualizar}")
        cursor.execute(query_actualizacion, tuple(valores_a_actualizar))
        conn.commit()

        # Generar alerta si el stock de casa matriz llega a 0
        if nuevo_stock_casa_matriz_val == 0 and stock_anterior_casa_matriz > 0:
            evento_alerta = {
                "type": "stock_cero_matriz",
                "codigo_producto": codigo_producto_upper,
                "nombre_producto": nuevo_nombre if nuevo_nombre else nombre_producto_actual,
                "mensaje": f"¡ALERTA! Producto '{nuevo_nombre if nuevo_nombre else nombre_producto_actual}' ({codigo_producto_upper}) ha alcanzado 0 stock en casa matriz (editado)."
            }
            broadcast_stock_alert(json.dumps(evento_alerta))
            app.logger.info(f"Evento de stock cero en MATRIZ BROADCAST para {codigo_producto_upper} (editado).")

        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Producto no encontrado durante la actualización (no se afectaron filas)"}), 404
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_actualizado_db = cursor.fetchone()
        conn.close()
        app.logger.info(f"Producto '{codigo_producto_upper}' actualizado exitosamente.")
        return jsonify(dict(producto_actualizado_db)), 200
    except sqlite3.Error as e: 
        conn.rollback()
        app.logger.error(f"Error de base de datos al actualizar producto: {e}")
        if conn: conn.close()
        return jsonify({"error": "Error interno de la base de datos al actualizar el producto"}), 500

@app.route('/api/sucursal', methods=['POST'])
def crear_sucursal_maestra():
    # ... (sin cambios) ...
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
        sucursal_creada = { "id_sucursal": id_sucursal, "nombre_sucursal": nombre_sucursal }
        app.logger.info(f"Sucursal '{nombre_sucursal}' ({id_sucursal}) creada exitosamente.")
        return jsonify(sucursal_creada), 201
    except sqlite3.IntegrityError: 
        app.logger.warning(f"Intento de crear sucursal con ID '{id_sucursal}' o nombre '{nombre_sucursal}' duplicado.")
        return jsonify({"error": f"Ya existe una sucursal con el ID '{id_sucursal}' o el nombre '{nombre_sucursal}'"}), 409
    except Exception as e:
        app.logger.error(f"Error inesperado al crear sucursal: {e}")
        return jsonify({"error": "Error interno del servidor al crear la sucursal"}), 500
    finally:
        conn.close()

@app.route('/api/sucursal/<string:id_sucursal>', methods=['GET'])
def obtener_info_sucursal(id_sucursal):
    # ... (sin cambios) ...
    id_sucursal_upper = id_sucursal.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id_sucursal, nombre_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal_upper,))
    sucursal_db = cursor.fetchone()
    conn.close() 
    if not sucursal_db:
        return jsonify({"error": "Sucursal no encontrada", "id_sucursal": id_sucursal_upper}), 404
    return jsonify(dict(sucursal_db))

@app.route('/api/sucursal/<string:id_sucursal>', methods=['PUT'])
def actualizar_sucursal_maestra(id_sucursal):
    # ... (sin cambios) ...
    id_sucursal_upper = id_sucursal.upper()
    if not request.json:
        return jsonify({"error": "La solicitud debe ser JSON"}), 400
    
    nuevo_nombre_sucursal = request.json.get('nombre_sucursal', '').strip()
    if not nuevo_nombre_sucursal:
        return jsonify({"error": "El nuevo nombre de la sucursal es requerido"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal_upper,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Sucursal no encontrada para actualizar"}), 404

        cursor.execute(
            "UPDATE sucursales_maestras SET nombre_sucursal = ? WHERE id_sucursal = ?",
            (nuevo_nombre_sucursal, id_sucursal_upper)
        )
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Sucursal no encontrada durante la actualización (no se afectaron filas)"}), 404

        sucursal_actualizada = {"id_sucursal": id_sucursal_upper, "nombre_sucursal": nuevo_nombre_sucursal}
        app.logger.info(f"Sucursal '{id_sucursal_upper}' actualizada a nombre '{nuevo_nombre_sucursal}'.")
        conn.close()
        return jsonify(sucursal_actualizada), 200
    except sqlite3.IntegrityError: 
        app.logger.warning(f"Intento de actualizar sucursal '{id_sucursal_upper}' a un nombre duplicado '{nuevo_nombre_sucursal}'.")
        if conn: conn.close()
        return jsonify({"error": f"Ya existe otra sucursal con el nombre '{nuevo_nombre_sucursal}'"}), 409
    except Exception as e:
        app.logger.error(f"Error inesperado al actualizar sucursal: {e}")
        if conn: conn.close()
        return jsonify({"error": "Error interno del servidor al actualizar la sucursal"}), 500

@app.route('/api/producto/<string:codigo_producto>/restock_matriz', methods=['POST'])
def restock_casa_matriz(codigo_producto):
    # ... (modificado para usar broadcast_stock_alert si el stock era 0 y ahora es > 0) ...
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
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db = cursor.fetchone()
        if not producto_db:
            conn.close() 
            return jsonify({"error": "Producto no encontrado"}), 404
        
        stock_actual = producto_db["stock_casa_matriz"]
        nombre_producto = producto_db["nombre"]
        nuevo_stock = stock_actual + cantidad_a_agregar
        
        cursor.execute(
            "UPDATE productos SET stock_casa_matriz = ? WHERE codigo = ?",
            (nuevo_stock, codigo_producto_upper)
        )
        conn.commit()

        # Si el stock era 0 y ahora es > 0, podríamos enviar un evento de "restock_exitoso"
        # Por ahora, nos enfocamos en la alerta de stock cero.
        # Si el stock llega a cero por otra vía y luego se hace restock, la alerta de stock cero ya se habría enviado.

        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_actualizado_db = cursor.fetchone()
        conn.close() 

        return jsonify({
            "mensaje": f"Stock de '{codigo_producto_upper}' ({nombre_producto}) en casa matriz actualizado a {nuevo_stock}.",
            "producto": dict(producto_actualizado_db)
        }), 200
        
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de base de datos al hacer restock en casa matriz: {e}")
        if conn: conn.close() 
        return jsonify({"error": "Error interno de la base de datos"}), 500

@app.route('/api/producto/<string:codigo_producto>/sucursal', methods=['POST'])
def agregar_o_actualizar_producto_en_sucursal(codigo_producto):
    # ... (modificado para usar broadcast_stock_alert para stock CERO en casa matriz) ...
    codigo_producto_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT codigo, nombre, stock_casa_matriz FROM productos WHERE codigo = ?", (codigo_producto_upper,))
        producto_db = cursor.fetchone()
        if not producto_db:
            conn.close()
            return jsonify({"error": "Producto no encontrado"}), 404
        
        stock_anterior_casa_matriz = producto_db["stock_casa_matriz"]
        nombre_producto = producto_db["nombre"]
        
        if not request.json: 
            conn.close()
            return jsonify({"error": "La solicitud debe ser JSON"}), 400
        id_sucursal = request.json.get('id_sucursal', '').strip().upper()
        try:
            nueva_cantidad_sucursal = int(request.json.get('cantidad'))
            precio_local = float(request.json.get('precio_local'))
            if nueva_cantidad_sucursal < 0 or precio_local < 0:
                conn.close()
                return jsonify({"error": "La cantidad y el precio no pueden ser negativos"}), 400
        except (ValueError, TypeError):
            conn.close()
            return jsonify({"error": "La cantidad debe ser un entero y el precio local un número válido"}), 400
        if not id_sucursal: 
            conn.close()
            return jsonify({"error": "El ID de sucursal es requerido"}), 400
        cursor.execute("SELECT id_sucursal FROM sucursales_maestras WHERE id_sucursal = ?", (id_sucursal,))
        if not cursor.fetchone(): 
            conn.close()
            return jsonify({"error": f"El ID de sucursal '{id_sucursal}' no es válido."}), 400

        cantidad_anterior_sucursal = 0
        cursor.execute("SELECT cantidad FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?", (codigo_producto_upper, id_sucursal))
        producto_en_sucursal_db = cursor.fetchone()
        if producto_en_sucursal_db: cantidad_anterior_sucursal = producto_en_sucursal_db["cantidad"]
        
        diferencia_stock_movido = nueva_cantidad_sucursal - cantidad_anterior_sucursal
        nuevo_stock_casa_matriz = stock_anterior_casa_matriz - diferencia_stock_movido

        if nuevo_stock_casa_matriz < 0:
            conn.close()
            return jsonify({
                "error": "Stock insuficiente en casa matriz.",
                "stock_disponible_casa_matriz": stock_anterior_casa_matriz,
                "requerido_para_mover_a_sucursal": diferencia_stock_movido 
            }), 400 

        cursor.execute("UPDATE productos SET stock_casa_matriz = ? WHERE codigo = ?", (nuevo_stock_casa_matriz, codigo_producto_upper))
        
        if nuevo_stock_casa_matriz == 0 and stock_anterior_casa_matriz > 0:
            evento_alerta = {
                "type": "stock_cero_matriz",
                "codigo_producto": codigo_producto_upper,
                "nombre_producto": nombre_producto,
                "mensaje": f"¡ALERTA! Producto '{nombre_producto}' ({codigo_producto_upper}) ha alcanzado 0 stock en casa matriz. ¡Necesita restock!"
            }
            broadcast_stock_alert(json.dumps(evento_alerta))
            app.logger.info(f"Evento de stock cero en MATRIZ BROADCAST para {codigo_producto_upper}")
        
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
        conn.close()
        
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
        if conn: conn.close()
        return jsonify({"error": "Error interno de la base de datos"}), 500

@app.route('/api/sucursal/<string:id_sucursal>/producto/<string:codigo_producto>/quitar', methods=['POST'])
def quitar_producto_de_sucursal(id_sucursal, codigo_producto):
    # ... (sin cambios) ...
    id_sucursal_upper = id_sucursal.upper()
    codigo_producto_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Producto no encontrado en esta sucursal"}), 404

        cursor.execute(
            "DELETE FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        conn.commit()
        
        if cursor.rowcount > 0:
            app.logger.info(f"Producto '{codigo_producto_upper}' quitado de sucursal '{id_sucursal_upper}'.")
            conn.close()
            return jsonify({"mensaje": f"Producto '{codigo_producto_upper}' quitado de la sucursal '{id_sucursal_upper}'."}), 200
        else:
            conn.close()
            return jsonify({"error": "Producto no se pudo quitar de la sucursal (no se afectaron filas)"}), 400 
            
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de BD al quitar producto de sucursal: {e}")
        if conn: conn.close()
        return jsonify({"error": "Error interno de base de datos"}), 500

@app.route('/api/sucursal/<string:id_sucursal>/producto/<string:codigo_producto>/retornar_stock', methods=['POST'])
def retornar_stock_a_matriz(id_sucursal, codigo_producto):
    # ... (sin cambios) ...
    id_sucursal_upper = id_sucursal.upper()
    codigo_producto_upper = codigo_producto.upper()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT cantidad FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        producto_en_sucursal = cursor.fetchone()
        if not producto_en_sucursal:
            conn.close()
            return jsonify({"error": "Producto no encontrado en esta sucursal para retornar stock"}), 404
        
        cantidad_en_sucursal = producto_en_sucursal["cantidad"]

        cursor.execute(
            "SELECT stock_casa_matriz FROM productos WHERE codigo = ?",
            (codigo_producto_upper,)
        )
        producto_matriz = cursor.fetchone()
        if not producto_matriz: 
            conn.close()
            return jsonify({"error": "Producto no encontrado en casa matriz (inconsistencia de datos)"}), 500
        
        stock_actual_casa_matriz = producto_matriz["stock_casa_matriz"]
        nuevo_stock_casa_matriz = stock_actual_casa_matriz + cantidad_en_sucursal

        cursor.execute(
            "UPDATE productos SET stock_casa_matriz = ? WHERE codigo = ?",
            (nuevo_stock_casa_matriz, codigo_producto_upper)
        )
        cursor.execute(
            "DELETE FROM productos_sucursales WHERE producto_codigo = ? AND sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        conn.commit()
        
        app.logger.info(f"Stock de producto '{codigo_producto_upper}' ({cantidad_en_sucursal} unidades) retornado de sucursal '{id_sucursal_upper}' a casa matriz.")
        conn.close()
        return jsonify({
            "mensaje": f"{cantidad_en_sucursal} unidades de '{codigo_producto_upper}' retornadas a casa matriz desde sucursal '{id_sucursal_upper}'. Nuevo stock matriz: {nuevo_stock_casa_matriz}."
        }), 200
            
    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de BD al retornar stock a matriz: {e}")
        if conn: conn.close()
        return jsonify({"error": "Error interno de base de datos"}), 500

@app.route('/api/sucursal/<string:id_sucursal>/producto/<string:codigo_producto>/comprar', methods=['POST'])
def comprar_producto_de_sucursal(id_sucursal, codigo_producto):
    id_sucursal_upper = id_sucursal.upper()
    codigo_producto_upper = codigo_producto.upper()
    cantidad_comprada = 1 

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT ps.cantidad, p.nombre as nombre_producto, sm.nombre_sucursal FROM productos_sucursales ps JOIN productos p ON ps.producto_codigo = p.codigo JOIN sucursales_maestras sm ON ps.sucursal_id = sm.id_sucursal WHERE ps.producto_codigo = ? AND ps.sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        producto_en_sucursal = cursor.fetchone()

        if not producto_en_sucursal:
            conn.close()
            return jsonify({"error": "Producto no disponible en esta sucursal."}), 404

        stock_actual_sucursal = producto_en_sucursal["cantidad"]
        nombre_producto = producto_en_sucursal["nombre_producto"] # Para el evento
        nombre_sucursal = producto_en_sucursal["nombre_sucursal"] # Para el evento

        if stock_actual_sucursal < cantidad_comprada:
            conn.close()
            return jsonify({
                "error": "Stock insuficiente en la sucursal para esta compra.",
                "stock_disponible_sucursal": stock_actual_sucursal,
                "cantidad_solicitada": cantidad_comprada
            }), 400

        nuevo_stock_sucursal = stock_actual_sucursal - cantidad_comprada
        cursor.execute(
            "UPDATE productos_sucursales SET cantidad = ? WHERE producto_codigo = ? AND sucursal_id = ?",
            (nuevo_stock_sucursal, codigo_producto_upper, id_sucursal_upper)
        )
        conn.commit()
        
        app.logger.info(f"Compra simulada: {cantidad_comprada} unidad(es) de '{codigo_producto_upper}' en sucursal '{id_sucursal_upper}'. Nuevo stock sucursal: {nuevo_stock_sucursal}.")
        
        # Generar evento de compra exitosa
        evento_compra = {
            "type": "compra_exitosa",
            "id_sucursal": id_sucursal_upper,
            "nombre_sucursal": nombre_sucursal, # Añadido para el mensaje
            "codigo_producto": codigo_producto_upper,
            "nombre_producto": nombre_producto,
            "stock_restante_sucursal": nuevo_stock_sucursal,
            # Mensajes pre-formateados para el pop-up
            "mensaje_compra": f"Alguien en {nombre_sucursal} compró {nombre_producto} ({codigo_producto_upper}) ¡ahora!",
            "mensaje_stock": f"Solo quedan {nuevo_stock_sucursal} unidades en la sucursal."
        }
        broadcast_stock_alert(json.dumps(evento_compra))
        app.logger.info(f"Evento de COMPRA EXITOSA BROADCAST para {codigo_producto_upper} en sucursal {id_sucursal_upper}")

        cursor.execute(
            "SELECT p.nombre, ps.cantidad, ps.precio_local FROM productos p JOIN productos_sucursales ps ON p.codigo = ps.producto_codigo WHERE ps.producto_codigo = ? AND ps.sucursal_id = ?",
            (codigo_producto_upper, id_sucursal_upper)
        )
        producto_actualizado_sucursal = cursor.fetchone()
        conn.close()

        return jsonify({
            "mensaje": f"¡Compra exitosa! {cantidad_comprada} unidad(es) de '{nombre_producto}' comprada(s) de la sucursal '{id_sucursal_upper}'.",
            "producto_actualizado_sucursal": dict(producto_actualizado_sucursal) if producto_actualizado_sucursal else None
        }), 200

    except sqlite3.Error as e:
        conn.rollback()
        app.logger.error(f"Error de BD al simular compra en sucursal: {e}")
        if conn: conn.close()
        return jsonify({"error": "Error interno de la base de datos durante la compra."}), 500


@app.route('/api/stream_stock_alerts')
def stream_stock_alerts():
    client_event_queue = queue.Queue(maxsize=20) 
    with sse_listeners_lock:
        sse_listeners.append(client_event_queue)
    app.logger.info(f"API_SSE_STREAM: Nuevo cliente conectado. Total listeners: {len(sse_listeners)}")

    def event_stream():
        last_keep_alive_sent = time.time()
        keep_alive_interval = 15
        try:
            while True:
                try:
                    evento_json_str = client_event_queue.get(timeout=0.5) 
                    yield f"data: {evento_json_str}\n\n"
                    app.logger.info(f"API_SSE_STREAM: Evento enviado a un cliente: {evento_json_str}")
                    client_event_queue.task_done()
                    last_keep_alive_sent = time.time()
                except queue.Empty:
                    current_time = time.time()
                    if current_time - last_keep_alive_sent > keep_alive_interval:
                        yield ": keep-alive\n\n"
                        app.logger.debug("API_SSE_STREAM: Keep-alive enviado a un cliente.")
                        last_keep_alive_sent = current_time
                except Exception as e_loop: 
                    app.logger.error(f"API_SSE_STREAM: Error dentro del bucle de eventos para un cliente: {e_loop}")
                    break 
                time.sleep(0.05) 
        except GeneratorExit:
            app.logger.info("API_SSE_STREAM: Cliente desconectado (GeneratorExit).")
        except Exception as e_stream:
            app.logger.error(f"API_SSE_STREAM: Error crítico en el generador del stream para un cliente: {e_stream}")
        finally:
            with sse_listeners_lock:
                try:
                    sse_listeners.remove(client_event_queue)
                    app.logger.info(f"API_SSE_STREAM: Cliente desconectado, cola eliminada. Listeners restantes: {len(sse_listeners)}")
                except ValueError:
                    app.logger.warning("API_SSE_STREAM: Intento de eliminar una cola de listener que ya no estaba en la lista.")
            app.logger.info("API_SSE_STREAM: Stream cerrado para un cliente.")
    return Response(event_stream(), mimetype="text/event-stream")

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
    
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True, use_reloader=False)
