from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import datetime
import logging

app = Flask(__name__)
app.secret_key = 'tu_super_secreto_aqui_cambialo_por_algo_seguro'

if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)
else:
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

API_BASE_URL = "http://127.0.0.1:5001/api"
DEFAULT_TASA_CAMBIO_USD_CLP = 980.0 

def get_current_year():
    return datetime.datetime.now().year

@app.route('/')
def pagina_inicio():
    sucursales_maestras = []
    productos_de_sucursal_seleccionada = []
    sucursal_seleccionada_info = None
    tasa_cambio = DEFAULT_TASA_CAMBIO_USD_CLP 
    
    try:
        response_sucursales = requests.get(f"{API_BASE_URL}/sucursales_maestras", timeout=5)
        if response_sucursales.status_code == 200:
            sucursales_maestras = response_sucursales.json()
        else:
            app.logger.warning(f"No se pudieron cargar las sucursales maestras. API devolvió: {response_sucursales.status_code}")
            flash("Error al cargar la lista de sucursales.", "danger")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al obtener sucursales maestras: {e}")
        flash("Error de conexión al cargar sucursales.", "danger")

    id_sucursal_seleccionada = request.args.get('sucursal_id')
    if id_sucursal_seleccionada:
        try:
            api_url = f"{API_BASE_URL}/sucursal/{id_sucursal_seleccionada}/productos"
            app.logger.debug(f"Obteniendo productos para sucursal: {api_url}")
            response_productos_suc = requests.get(api_url, timeout=5)
            
            if response_productos_suc.status_code == 200:
                data_sucursal = response_productos_suc.json()
                productos_de_sucursal_seleccionada = data_sucursal.get("productos", [])
                tasa_cambio = data_sucursal.get("tasa_cambio_a_usd", DEFAULT_TASA_CAMBIO_USD_CLP)
                sucursal_seleccionada_info = {
                    "id_sucursal": data_sucursal.get("id_sucursal"),
                    "nombre_sucursal": data_sucursal.get("nombre_sucursal")
                }
                app.logger.debug(f"Productos obtenidos para sucursal {id_sucursal_seleccionada}: {len(productos_de_sucursal_seleccionada)} productos. Tasa: {tasa_cambio}")
            elif response_productos_suc.status_code == 404:
                flash(f"Sucursal con ID '{id_sucursal_seleccionada}' no encontrada o sin productos.", "warning")
            else:
                flash(f"Error al cargar productos de la sucursal (API: {response_productos_suc.status_code}).", "error")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Error de conexión/API al obtener productos de sucursal {id_sucursal_seleccionada}: {e}")
            flash("Error de conexión al cargar productos de la sucursal.", "danger")
    
    productos_existentes_para_lista_general = []
    try:
        response_prods_general = requests.get(f"{API_BASE_URL}/productos", timeout=5)
        if response_prods_general.status_code == 200:
            productos_existentes_para_lista_general = response_prods_general.json()
    except requests.exceptions.RequestException:
        app.logger.warning("No se pudo cargar la lista general de productos para el buscador.")

    return render_template('index.html', 
                           current_year=get_current_year(),
                           sucursales_maestras=sucursales_maestras,
                           productos_de_sucursal=productos_de_sucursal_seleccionada,
                           sucursal_seleccionada=sucursal_seleccionada_info,
                           tasa_cambio_a_usd=tasa_cambio,
                           productos_existentes=productos_existentes_para_lista_general
                           )

@app.route('/buscar', methods=['POST'])
def buscar_producto():
    codigo_producto_buscado = request.form.get('codigo_producto', '').strip().upper()
    if not codigo_producto_buscado:
        flash("Por favor, ingrese un código de producto.", "warning")
        return redirect(url_for('pagina_inicio'))
    try:
        response = requests.get(f"{API_BASE_URL}/producto/{codigo_producto_buscado}")
        if response.status_code == 200:
            datos_producto = response.json()
            if not datos_producto.get('codigo_producto'):
                app.logger.error(f"API devolvió producto sin codigo_producto o vacío para búsqueda: {codigo_producto_buscado}. Respuesta API: {datos_producto}")
                flash(f"Error: La API devolvió datos incompletos para el producto '{codigo_producto_buscado}'.", "error")
                return redirect(url_for('pagina_inicio'))

            mensajes_stock_bajo = [
                f"¡Alerta! Stock es 0 en {s.get('nombre_sucursal', 'N/A')}."
                for s in datos_producto.get("sucursales", []) if s.get("cantidad", 0) == 0
            ]
            return render_template('resultados.html',
                                   producto=datos_producto,
                                   mensajes_stock_bajo=mensajes_stock_bajo,
                                   current_year=get_current_year())
        elif response.status_code == 404:
            flash(f"Producto con código '{codigo_producto_buscado}' no encontrado.", "error")
        else:
            flash(f"Error de la API (código {response.status_code}): {response.text}", "error")
    except requests.exceptions.RequestException as e:
        flash(f"Error de conexión con la API en {API_BASE_URL}: {e}", "danger")
    return redirect(url_for('pagina_inicio'))

@app.route('/producto/nuevo', methods=['GET', 'POST'])
def gestionar_nuevo_producto():
    # ... (sin cambios) ...
    form_data = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        codigo_producto = request.form.get('codigo_producto', '').strip().upper()
        nombre_producto = request.form.get('nombre_producto', '').strip()
        stock_casa_matriz_str = request.form.get('stock_casa_matriz', '0')
        if not codigo_producto or not nombre_producto:
            flash("El código y el nombre del producto son obligatorios.", "warning")
            return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=form_data)
        try:
            stock_casa_matriz = int(stock_casa_matriz_str)
            if stock_casa_matriz < 0:
                flash("El stock en casa matriz no puede ser negativo.", "warning")
                return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=form_data)
        except ValueError:
            flash("El stock en casa matriz debe ser un número entero.", "warning")
            return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=form_data)
        payload = {
            "codigo_producto": codigo_producto, "nombre_producto": nombre_producto,
            "stock_casa_matriz": stock_casa_matriz
        }
        try:
            response = requests.post(f"{API_BASE_URL}/producto", json=payload)
            if response.status_code == 201:
                flash(f"Producto '{nombre_producto}' ({codigo_producto}) creado exitosamente.", "success")
                return redirect(url_for('pagina_inicio')) 
            elif response.status_code == 409:
                 flash(f"Error: Ya existe un producto con el código '{codigo_producto}'.", "error")
            else:
                error_msg = response.json().get("error", "Error desconocido.")
                flash(f"Error al crear producto (API {response.status_code}): {error_msg}", "error")
        except requests.exceptions.RequestException as e:
            flash(f"Error de conexión con la API al crear producto: {e}", "danger")
        return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=form_data)
    return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=form_data)

@app.route('/sucursal/nueva', methods=['GET', 'POST'])
def gestionar_nueva_sucursal():
    # ... (sin cambios) ...
    form_data = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        id_sucursal = request.form.get('id_sucursal', '').strip().upper()
        nombre_sucursal = request.form.get('nombre_sucursal', '').strip()

        if not id_sucursal or not nombre_sucursal:
            flash("El ID y el nombre de la sucursal son obligatorios.", "warning")
            return render_template('nueva_sucursal.html', current_year=get_current_year(), form_data=form_data)

        payload = {
            "id_sucursal": id_sucursal,
            "nombre_sucursal": nombre_sucursal
        }
        try:
            response = requests.post(f"{API_BASE_URL}/sucursal", json=payload)
            if response.status_code == 201:
                flash(f"Sucursal '{nombre_sucursal}' ({id_sucursal}) creada exitosamente.", "success")
                return redirect(url_for('gestionar_sucursales_maestras')) 
            elif response.status_code == 409: 
                 flash(response.json().get("error", f"Error: Ya existe una sucursal con ese ID o nombre."), "error")
            else:
                error_msg = response.json().get("error", "Error desconocido de la API.")
                flash(f"Error al crear sucursal (API {response.status_code}): {error_msg}", "error")
        except requests.exceptions.RequestException as e:
            flash(f"Error de conexión con la API al crear sucursal: {e}", "danger")
        return render_template('nueva_sucursal.html', current_year=get_current_year(), form_data=form_data)
    return render_template('nueva_sucursal.html', current_year=get_current_year(), form_data=form_data)

@app.route('/sucursales', methods=['GET'])
def gestionar_sucursales_maestras():
    """Muestra la lista de todas las sucursales maestras con opción de editar."""
    sucursales = []
    try:
        response = requests.get(f"{API_BASE_URL}/sucursales_maestras", timeout=5)
        if response.status_code == 200:
            sucursales = response.json()
        else:
            flash(f"Error al cargar sucursales (API: {response.status_code}).", "danger")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al obtener sucursales para gestión: {e}")
        flash("Error de conexión al cargar sucursales.", "danger")
    
    return render_template('lista_sucursales.html', 
                           sucursales=sucursales, 
                           current_year=get_current_year())

@app.route('/sucursal/<string:id_sucursal>/editar', methods=['GET', 'POST'])
def editar_sucursal_maestra(id_sucursal):
    """Muestra el formulario para editar una sucursal y procesa la actualización."""
    id_sucursal_upper = id_sucursal.upper()
    sucursal_actual = None

    # Para GET, obtener datos de la sucursal para poblar el formulario
    if request.method == 'GET':
        try:
            response = requests.get(f"{API_BASE_URL}/sucursal/{id_sucursal_upper}", timeout=5)
            if response.status_code == 200:
                sucursal_actual = response.json()
            elif response.status_code == 404:
                flash(f"Sucursal con ID '{id_sucursal_upper}' no encontrada.", "error")
                return redirect(url_for('gestionar_sucursales_maestras'))
            else:
                flash(f"Error al cargar datos de la sucursal (API: {response.status_code}).", "error")
                return redirect(url_for('gestionar_sucursales_maestras'))
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Error de conexión/API al obtener sucursal {id_sucursal_upper} para editar: {e}")
            flash("Error de conexión al cargar la sucursal.", "danger")
            return redirect(url_for('gestionar_sucursales_maestras'))

    # Para POST, procesar la actualización
    if request.method == 'POST':
        nuevo_nombre_sucursal = request.form.get('nombre_sucursal', '').strip()
        if not nuevo_nombre_sucursal:
            flash("El nuevo nombre de la sucursal es obligatorio.", "warning")
            # Necesitamos repoblar sucursal_actual si hay un error para que el formulario se muestre bien
            # Si no se pudo obtener antes (en GET), sucursal_actual será None.
            # Es mejor obtenerlo de nuevo o pasarlo de alguna manera.
            # Por simplicidad, si falla la validación, se renderiza con los datos del form.
            return render_template('editar_sucursal.html', 
                                   sucursal={"id_sucursal": id_sucursal_upper, "nombre_sucursal": nuevo_nombre_sucursal}, # Usar datos del form
                                   current_year=get_current_year())
        
        payload = {"nombre_sucursal": nuevo_nombre_sucursal}
        try:
            api_url = f"{API_BASE_URL}/sucursal/{id_sucursal_upper}"
            response = requests.put(api_url, json=payload) # Usar método PUT

            if response.status_code == 200:
                flash(f"Sucursal '{id_sucursal_upper}' actualizada exitosamente a '{nuevo_nombre_sucursal}'.", "success")
                return redirect(url_for('gestionar_sucursales_maestras'))
            elif response.status_code == 409: # Conflicto por nombre duplicado
                flash(response.json().get("error", "Error: Nombre de sucursal duplicado."), "error")
            elif response.status_code == 404:
                 flash(f"Sucursal '{id_sucursal_upper}' no encontrada para actualizar.", "error")
            else:
                error_msg = response.json().get("error", "Error desconocido de la API.")
                flash(f"Error al actualizar sucursal (API {response.status_code}): {error_msg}", "error")
        except requests.exceptions.RequestException as e:
            flash(f"Error de conexión con la API al actualizar sucursal: {e}", "danger")
        
        # Si hay error, volver a renderizar el formulario con los datos del form
        return render_template('editar_sucursal.html', 
                               sucursal={"id_sucursal": id_sucursal_upper, "nombre_sucursal": nuevo_nombre_sucursal}, 
                               current_year=get_current_year())

    # Para GET, si sucursal_actual se obtuvo correctamente
    if sucursal_actual:
        return render_template('editar_sucursal.html', 
                               sucursal=sucursal_actual, 
                               current_year=get_current_year())
    else:
        # Si sucursal_actual es None después de un intento fallido de GET, redirigir.
        # Esto no debería pasar si el manejo de errores en GET funciona.
        return redirect(url_for('gestionar_sucursales_maestras'))


@app.route('/producto/asignar_sucursal', methods=['GET', 'POST'])
@app.route('/producto/<string:codigo_producto_param>/asignar_sucursal', methods=['GET', 'POST'])
def gestionar_asignacion_sucursal(codigo_producto_param=None):
    # ... (sin cambios) ...
    productos_api = []
    sucursales_api = []
    form_data_repopulate = {} 
    if request.method == 'POST':
        form_data_repopulate = request.form.to_dict()
    elif codigo_producto_param:
        form_data_repopulate['codigo_producto'] = codigo_producto_param.upper()
    try:
        res_prods = requests.get(f"{API_BASE_URL}/productos", timeout=5)
        if res_prods.status_code == 200:
            productos_api = res_prods.json()
        else:
            flash("No se pudieron cargar los productos desde la API.", "warning")
        res_sucs = requests.get(f"{API_BASE_URL}/sucursales_maestras", timeout=5)
        if res_sucs.status_code == 200:
            sucursales_api = res_sucs.json()
        else:
            flash("No se pudieron cargar las sucursales desde la API.", "warning")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al cargar datos para asignación: {e}")
        flash("Error de conexión al cargar datos para asignación.", "danger")
        return redirect(url_for('pagina_inicio'))

    if request.method == 'POST':
        codigo_producto = request.form.get('codigo_producto', '').strip().upper()
        id_sucursal = request.form.get('id_sucursal', '').strip().upper()
        cantidad_str = request.form.get('cantidad', '0')
        precio_local_str = request.form.get('precio_local', '0.0')
        if not codigo_producto or not id_sucursal:
            flash("Debe seleccionar un producto y una sucursal.", "warning")
        else:
            try:
                cantidad = int(cantidad_str)
                precio_local = float(precio_local_str)
                if cantidad < 0 or precio_local < 0:
                    flash("La cantidad y el precio no pueden ser negativos.", "warning")
                else:
                    payload = {"id_sucursal": id_sucursal, "cantidad": cantidad, "precio_local": precio_local}
                    api_url_post = f"{API_BASE_URL}/producto/{codigo_producto}/sucursal"
                    response = requests.post(api_url_post, json=payload)
                    if response.status_code == 200:
                        flash(response.json().get("mensaje", "Operación exitosa."), "success")
                        return redirect(url_for('buscar_producto_redirect', codigo_producto=codigo_producto))
                    else:
                        error_data = response.json()
                        error_msg = error_data.get("error", "Error desconocido.")
                        if "stock_disponible_casa_matriz" in error_data:
                            error_msg += f" Stock disponible: {error_data['stock_disponible_casa_matriz']}. Requerido: {error_data['requerido_para_mover_a_sucursal']}."
                        flash(f"Error al asignar (API {response.status_code}): {error_msg}", "error")
            except ValueError:
                flash("Cantidad y precio deben ser números válidos.", "warning")
            except requests.exceptions.RequestException as e:
                 flash(f"Error de conexión con la API al asignar: {e}", "danger")
        return render_template('agregar_a_sucursal.html',
                               productos=productos_api, sucursales=sucursales_api,
                               current_year=get_current_year(), form_data=form_data_repopulate)
    return render_template('agregar_a_sucursal.html',
                           productos=productos_api, sucursales=sucursales_api,
                           current_year=get_current_year(), form_data=form_data_repopulate)

@app.route('/producto/restock_casa_matriz', methods=['GET', 'POST'])
def pagina_restock_casa_matriz():
    # ... (sin cambios) ...
    productos_api = []
    try:
        res_prods = requests.get(f"{API_BASE_URL}/productos", timeout=5)
        if res_prods.status_code == 200:
            productos_api = res_prods.json()
        else:
            flash("No se pudieron cargar los productos desde la API para el restock.", "warning")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al cargar productos para restock: {e}")
        flash("Error de conexión al cargar productos para restock.", "danger")
        return redirect(url_for('pagina_inicio'))

    if request.method == 'POST':
        codigo_producto = request.form.get('codigo_producto', '').strip().upper()
        cantidad_a_agregar_str = request.form.get('cantidad_a_agregar', '0')

        if not codigo_producto:
            flash("Debe seleccionar un producto.", "warning")
        else:
            try:
                cantidad_a_agregar = int(cantidad_a_agregar_str)
                if cantidad_a_agregar <= 0:
                    flash("La cantidad a agregar debe ser un número positivo.", "warning")
                else:
                    payload = {"cantidad_a_agregar": cantidad_a_agregar}
                    api_url_post = f"{API_BASE_URL}/producto/{codigo_producto}/restock_matriz"
                    
                    app.logger.debug(f"Enviando a API para restock: URL={api_url_post}, Payload={payload}")
                    response = requests.post(api_url_post, json=payload)
                    
                    if response.status_code == 200:
                        flash(response.json().get("mensaje", "Stock actualizado exitosamente."), "success")
                        return redirect(url_for('buscar_producto_redirect', codigo_producto=codigo_producto))
                    else:
                        error_msg = response.json().get("error", "Error desconocido al hacer restock.")
                        flash(f"Error al hacer restock (API {response.status_code}): {error_msg}", "error")
            
            except ValueError:
                flash("La cantidad a agregar debe ser un número entero válido.", "warning")
            except requests.exceptions.RequestException as e:
                 flash(f"Error de conexión con la API al hacer restock: {e}", "danger")
        
        return render_template('restock_casa_matriz.html',
                               productos=productos_api,
                               current_year=get_current_year(),
                               form_data=request.form) 

    return render_template('restock_casa_matriz.html',
                           productos=productos_api,
                           current_year=get_current_year(),
                           form_data={})

@app.route('/buscar_redirect', methods=['GET'])
def buscar_producto_redirect():
    # ... (sin cambios) ...
    codigo_producto = request.args.get('codigo_producto')
    if not codigo_producto:
        return redirect(url_for('pagina_inicio'))
    class MockForm:
        def __init__(self, data): self._data = data
        def get(self, key, default=None): return self._data.get(key, default)
    original_form = request.form
    request.form = MockForm({'codigo_producto': codigo_producto}) 
    response_view = buscar_producto()
    request.form = original_form 
    return response_view

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
