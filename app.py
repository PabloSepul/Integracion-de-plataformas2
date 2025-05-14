from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import datetime
import logging

app = Flask(__name__)
app.secret_key = 'tu_super_secreto_aqui_cambialo_por_algo_seguro'

logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

API_BASE_URL = "http://127.0.0.1:5001/api"

def get_current_year():
    return datetime.datetime.now().year

@app.route('/')
def pagina_inicio():
    productos_existentes = []
    try:
        response = requests.get(f"{API_BASE_URL}/productos", timeout=5)
        if response.status_code == 200:
            productos_existentes = response.json()
        else:
            app.logger.warning(f"No se pudieron cargar los productos. API devolvió: {response.status_code}")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al obtener lista de productos: {e}")

    return render_template('index.html', 
                           current_year=get_current_year(),
                           productos_existentes=productos_existentes)

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
            "codigo_producto": codigo_producto,
            "nombre_producto": nombre_producto,
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

@app.route('/producto/asignar_sucursal', methods=['GET', 'POST'])
@app.route('/producto/<string:codigo_producto_param>/asignar_sucursal', methods=['GET', 'POST'])
def gestionar_asignacion_sucursal(codigo_producto_param=None):
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

# --- Ruta para Eliminación Definitiva de Productos ---
@app.route('/producto/<string:codigo_producto>/eliminar', methods=['POST'])
def eliminar_producto(codigo_producto):
    app.logger.debug(f"Intentando eliminar producto con código (desde URL): '{codigo_producto}'")
    
    if not codigo_producto or codigo_producto.isspace():
        flash("Error: Código de producto inválido para eliminar.", "error")
        return redirect(url_for('pagina_inicio'))

    try:
        api_url = f"{API_BASE_URL}/producto/{codigo_producto.upper()}" # El método DELETE se especifica en la llamada
        app.logger.debug(f"Llamando a API para eliminar físicamente: {api_url} con método DELETE")
        
        response = requests.delete(api_url) # Usar requests.delete()
        
        app.logger.debug(f"Respuesta de API (eliminar) - Status: {response.status_code}, Contenido: {response.text}")

        if response.status_code == 200:
            flash(response.json().get("mensaje", f"Producto {codigo_producto.upper()} eliminado permanentemente."), "success")
        elif response.status_code == 404:
            flash(f"Producto {codigo_producto.upper()} no encontrado para eliminar (API).", "error")
        else:
            error_msg = "Error desconocido de la API."
            try:
                error_msg = response.json().get("error", error_msg)
            except ValueError:
                app.logger.warning(f"Respuesta de API (eliminar) no fue JSON: {response.text}")
            flash(f"Error al eliminar producto (API {response.status_code}): {error_msg}", "error")
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión/API al eliminar producto: {e}")
        flash("Error de conexión al eliminar producto.", "danger")
    
    return redirect(url_for('pagina_inicio')) # Siempre redirigir a inicio después de eliminar


@app.route('/buscar_redirect', methods=['GET'])
def buscar_producto_redirect():
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
    app.run(host='0.0.0.0', port=5000, debug=True)
