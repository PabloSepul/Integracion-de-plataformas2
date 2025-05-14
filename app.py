from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import datetime

app = Flask(__name__)
app.secret_key = 'tu_super_secreto_aqui_cambialo'

API_BASE_URL = "http://127.0.0.1:5001/api"

def get_current_year():
    return datetime.datetime.now().year

@app.route('/')
def pagina_inicio():
    return render_template('index.html', current_year=get_current_year())

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
    except requests.exceptions.ConnectionError:
        flash(f"Error de conexión con la API en {API_BASE_URL}. Verifique que esté activa.", "danger")
    except Exception as e:
        app.logger.error(f"Error inesperado: {e}", exc_info=True)
        flash("Ocurrió un error inesperado.", "danger")
    return redirect(url_for('pagina_inicio'))

# --- Rutas para Gestión de Productos ---

@app.route('/producto/nuevo', methods=['GET', 'POST'])
def gestionar_nuevo_producto():
    if request.method == 'POST':
        codigo_producto = request.form.get('codigo_producto', '').strip().upper()
        nombre_producto = request.form.get('nombre_producto', '').strip()
        stock_casa_matriz_str = request.form.get('stock_casa_matriz', '0')

        if not codigo_producto or not nombre_producto:
            flash("El código y el nombre del producto son obligatorios.", "warning")
            return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=request.form)

        try:
            stock_casa_matriz = int(stock_casa_matriz_str)
            if stock_casa_matriz < 0:
                flash("El stock en casa matriz no puede ser negativo.", "warning")
                return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=request.form)
        except ValueError:
            flash("El stock en casa matriz debe ser un número entero.", "warning")
            return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=request.form)

        payload = {
            "codigo_producto": codigo_producto,
            "nombre_producto": nombre_producto,
            "stock_casa_matriz": stock_casa_matriz
        }
        try:
            response = requests.post(f"{API_BASE_URL}/producto", json=payload)
            if response.status_code == 201: # Created
                flash(f"Producto '{nombre_producto}' ({codigo_producto}) creado exitosamente.", "success")
                return redirect(url_for('pagina_inicio')) # O a la página de resultados del nuevo producto
            elif response.status_code == 409: # Conflict
                 flash(f"Error: Ya existe un producto con el código '{codigo_producto}'.", "error")
            else:
                error_msg = response.json().get("error", "Error desconocido de la API.")
                flash(f"Error al crear producto (API {response.status_code}): {error_msg}", "error")
        except requests.exceptions.ConnectionError:
            flash(f"Error de conexión con la API al crear producto.", "danger")
        
        return render_template('nuevo_producto.html', current_year=get_current_year(), form_data=request.form)

    return render_template('nuevo_producto.html', current_year=get_current_year())


@app.route('/producto/asignar_sucursal', methods=['GET', 'POST'])
@app.route('/producto/<string:codigo_producto_param>/asignar_sucursal', methods=['GET', 'POST'])
def gestionar_asignacion_sucursal(codigo_producto_param=None):
    productos_api = []
    sucursales_api = []
    form_data = request.form if request.method == 'POST' else {}
    if codigo_producto_param: # Si viene de la página de resultados
        form_data = {'codigo_producto': codigo_producto_param.upper()}


    try:
        # Obtener lista de productos para el selector
        res_prods = requests.get(f"{API_BASE_URL}/productos")
        if res_prods.status_code == 200:
            productos_api = res_prods.json()
        else:
            flash("No se pudieron cargar los productos desde la API.", "warning")
        
        # Obtener lista de sucursales maestras para el selector
        res_sucs = requests.get(f"{API_BASE_URL}/sucursales_maestras")
        if res_sucs.status_code == 200:
            sucursales_api = res_sucs.json()
        else:
            flash("No se pudieron cargar las sucursales desde la API.", "warning")

    except requests.exceptions.ConnectionError:
        flash("Error de conexión con la API al cargar datos para asignación.", "danger")
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
                    payload = {
                        "id_sucursal": id_sucursal,
                        "cantidad": cantidad,
                        "precio_local": precio_local
                    }
                    api_url = f"{API_BASE_URL}/producto/{codigo_producto}/sucursal"
                    response = requests.post(api_url, json=payload)

                    if response.status_code == 200:
                        flash(response.json().get("mensaje", "Operación exitosa."), "success")
                        # Redirigir a la página de resultados del producto modificado
                        return redirect(url_for('buscar_producto_redirect', codigo_producto=codigo_producto))
                    else:
                        error_msg = response.json().get("error", "Error desconocido.")
                        flash(f"Error al asignar a sucursal (API {response.status_code}): {error_msg}", "error")
            
            except ValueError:
                flash("Cantidad y precio deben ser números válidos.", "warning")
            except requests.exceptions.ConnectionError:
                 flash(f"Error de conexión con la API al asignar producto a sucursal.", "danger")
        
        # Si hay error, volver a renderizar el formulario con los datos y listas
        return render_template('agregar_a_sucursal.html',
                               productos=productos_api,
                               sucursales=sucursales_api,
                               current_year=get_current_year(),
                               form_data=request.form, # Para repoblar el formulario
                               selected_product_code=codigo_producto_param.upper() if codigo_producto_param else request.form.get('codigo_producto'))


    # Método GET
    return render_template('agregar_a_sucursal.html',
                           productos=productos_api,
                           sucursales=sucursales_api,
                           current_year=get_current_year(),
                           selected_product_code=codigo_producto_param.upper() if codigo_producto_param else None)

@app.route('/buscar_redirect', methods=['GET'])
def buscar_producto_redirect():
    """
    Ruta intermedia para simular un POST a /buscar desde un redirect.
    Esto es para poder ver los resultados actualizados después de una modificación.
    """
    codigo_producto = request.args.get('codigo_producto')
    if not codigo_producto:
        return redirect(url_for('pagina_inicio'))
    
    # Simular la estructura de datos de un formulario POST
    class MockForm:
        def get(self, key, default=None):
            if key == 'codigo_producto':
                return codigo_producto
            return default

    original_form = request.form
    request.form = MockForm() # Sobrescribir request.form temporalmente
    response = buscar_producto()
    request.form = original_form # Restaurar request.form
    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
