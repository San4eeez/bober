# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import psycopg2
from flask import Flask, render_template, request, jsonify, send_file
import psycopg2
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import io


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Замените на надежный ключ в продакшене

# Конфигурация БД
DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    """Создаёт подключение к базе данных."""
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        raise

def filter_entities_by_default(category, subcategory):
    """Функция для фильтрации по первой категории и подкатегории"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Получаем категории для боковой панели
        cur.execute("""
            SELECT c.name as category, sc.name as subcategory, 
                   COUNT(DISTINCT o.id) as object_count
            FROM categories c
            LEFT JOIN subcategories sc ON c.id = sc.category_id
            LEFT JOIN entities e ON e.subcategory_id = sc.id
            LEFT JOIN objects o ON o.entity_id = e.id
            GROUP BY c.name, sc.name
            ORDER BY c.name, sc.name
        """)
        categories_data = {}
        for cat, subcat, count in cur.fetchall():
            if cat not in categories_data:
                categories_data[cat] = {'count': 0, 'subcategories': []}
            if subcat:
                categories_data[cat]['subcategories'].append({
                    'name': subcat,
                    'count': count
                })
                categories_data[cat]['count'] += count

        # Получаем отфильтрованные сущности
        cur.execute("""
            SELECT e.id
            FROM entities e
            JOIN subcategories sc ON e.subcategory_id = sc.id
            JOIN categories c ON sc.category_id = c.id
            WHERE c.name = %s AND sc.name = %s
        """, (category, subcategory))
        entity_ids = [row[0] for row in cur.fetchall()]
        all_entities = get_all_data()
        filtered_entities = [e for e in all_entities if e['id'] in entity_ids]
        return render_template('index.html',
                               categories=[{'name': k, **v} for k, v in categories_data.items()],
                               entities=filtered_entities)
    finally:
        cur.close()
        conn.close()



import logging

logging.basicConfig(level=logging.INFO)

@app.route('/generate_table', methods=['POST'])
def generate_table():
    cart_items = request.json.get('cart_items')
    object_names = []

    # Получаем имена объектов из корзины
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for object_id in cart_items.keys():
            cur.execute("SELECT o.name FROM objects o WHERE o.id = %s", (object_id,))
            object_name = cur.fetchone()
            if object_name:
                object_names.append(object_name[0])
                logging.info(f"Added object name: {object_name[0]}")
    finally:
        cur.close()
        conn.close()

    # Чтение файла Excel
    file_path = "doc.xlsx"
    try:
        df = pd.read_excel(file_path, header=None)
    except Exception as e:
        logging.error(f"Error reading Excel file: {e}")
        return jsonify({'error': 'Error reading Excel file'}), 500

    # Получение заголовков (первые 4 строки)
    headers = df.iloc[:4]

    # Создание нового DataFrame для хранения результатов
    result_df = headers.copy()

    # Проходим по каждому наименованию объекта
    for name in object_names:
        logging.info(f"Processing object name: {name}")
        # Нахождение индексов строк, где наименование объекта совпадает
        matching_rows = df[df[1] == name]
        if not matching_rows.empty:
            start_index = matching_rows.index[0]

            # Находим следующее наименование объекта или конец файла
            if start_index + 1 < len(df):
                next_name_index = df[df[1].notna()].index[df[df[1].notna()].index > start_index].min()
            else:
                next_name_index = len(df)

            # Выборка данных между найденными индексами
            selected_data = df.iloc[start_index:next_name_index]

            # Добавление выбранных данных в результирующий DataFrame
            result_df = pd.concat([result_df, selected_data], ignore_index=True)
        else:
            logging.warning(f"No matching rows found for object name: {name}")

    # Сохранение результата в новый файл Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        result_df.to_excel(writer, index=False, header=False)
    output.seek(0)

    return send_file(output, as_attachment=True, download_name='filtered_part.xlsx')





@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Получаем все категории и подкатегории с количеством объектов
        cur.execute("""
            SELECT c.name as category, sc.name as subcategory, 
                   COUNT(DISTINCT o.id) as object_count
            FROM categories c
            LEFT JOIN subcategories sc ON c.id = sc.category_id
            LEFT JOIN entities e ON e.subcategory_id = sc.id
            LEFT JOIN objects o ON o.entity_id = e.id
            GROUP BY c.name, sc.name
            ORDER BY c.name, sc.name
        """)
        categories = {}
        first_category = None
        first_subcategory = None
        for category, subcategory, count in cur.fetchall():
            if category not in categories:
                categories[category] = {'count': 0, 'subcategories': []}
            if subcategory:
                categories[category]['subcategories'].append({
                    'name': subcategory,
                    'count': count
                })
                categories[category]['count'] += count
            # Сохраняем первую категорию и подкатегорию
            if first_category is None and category:
                first_category = category
            if first_subcategory is None and subcategory:
                first_subcategory = subcategory

        # Если найдена первая категория и подкатегория, перенаправляем на них
        if first_category and first_subcategory:
            return filter_entities_by_default(first_category, first_subcategory)

        # Если категорий нет, показываем пустую страницу
        entities = get_all_data()
        return render_template('index.html',
                               categories=[{'name': k, **v} for k, v in categories.items()],
                               entities=entities)
    finally:
        cur.close()
        conn.close()

@app.route('/filter')
def filter_entities():
    category = request.args.get('category')
    subcategory = request.args.get('subcategory')
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Получаем категории для боковой панели
        cur.execute("""
            SELECT c.name as category, sc.name as subcategory, 
                   COUNT(DISTINCT o.id) as object_count
            FROM categories c
            LEFT JOIN subcategories sc ON c.id = sc.category_id
            LEFT JOIN entities e ON e.subcategory_id = sc.id
            LEFT JOIN objects o ON o.entity_id = e.id
            GROUP BY c.name, sc.name
            ORDER BY c.name, sc.name
        """)
        categories_data = {}
        for cat, subcat, count in cur.fetchall():
            if cat not in categories_data:
                categories_data[cat] = {'count': 0, 'subcategories': []}
            if subcat:
                categories_data[cat]['subcategories'].append({
                    'name': subcat,
                    'count': count
                })
                categories_data[cat]['count'] += count

        # Получаем отфильтрованные сущности
        cur.execute("""
            SELECT e.id
            FROM entities e
            JOIN subcategories sc ON e.subcategory_id = sc.id
            JOIN categories c ON sc.category_id = c.id
            WHERE c.name = %s AND sc.name = %s
        """, (category, subcategory))
        entity_ids = [row[0] for row in cur.fetchall()]
        all_entities = get_all_data()
        filtered_entities = [e for e in all_entities if e['id'] in entity_ids]
        return render_template('index.html',
                               categories=[{'name': k, **v} for k, v in categories_data.items()],
                               entities=filtered_entities)
    finally:
        cur.close()
        conn.close()

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                e.id AS entity_id,
                e.name AS entity_name,
                o.id AS object_id,
                o.name AS object_name,
                ec.id AS characteristic_id,
                ec.name AS characteristic_name,
                ov.value AS characteristic_value,
                c.name AS category_name,
                sc.name AS subcategory_name
            FROM objects o
            JOIN entities e ON o.entity_id = e.id
            LEFT JOIN object_values ov ON ov.object_id = o.id
            LEFT JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
            LEFT JOIN categories c ON sc.category_id = c.id
            WHERE o.name ILIKE %s OR e.name ILIKE %s
            ORDER BY e.name, o.name;
        """, (f"%{query}%", f"%{query}%"))
        results = cur.fetchall()

        # Группируем данные по сущностям и объектам
        grouped_data = {}
        for row in results:
            entity_id, entity_name, object_id, object_name, char_id, char_name, char_value, category_name, subcategory_name = row
            if entity_id not in grouped_data:
                grouped_data[entity_id] = {
                    'id': entity_id,
                    'name': entity_name,
                    'category': category_name if category_name else '',
                    'subcategory': subcategory_name if subcategory_name else '',
                    'objects': {}
                }
            if object_id not in grouped_data[entity_id]['objects']:
                grouped_data[entity_id]['objects'][object_id] = {
                    'id': object_id,
                    'name': object_name,
                    'characteristics_info': {}
                }
            if char_id and char_name and char_value:
                grouped_data[entity_id]['objects'][object_id]['characteristics_info'][char_id] = {
                    'name': char_name,
                    'value': char_value
                }

        # Преобразуем данные в список
        entities = []
        for entity_data in grouped_data.values():
            entity = {
                'id': entity_data['id'],
                'name': entity_data['name'],
                'category': entity_data['category'],
                'subcategory': entity_data['subcategory'],
                'objects': list(entity_data['objects'].values())
            }
            entities.append(entity)
        return jsonify(entities)
    finally:
        cur.close()
        conn.close()

@app.route('/get_characteristics_for_entity')
def get_characteristics_for_entity():
    """Получает список характеристик для конкретной сущности"""
    entity_name = request.args.get('entity_name')
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ec.name 
            FROM entity_characteristics ec
            JOIN entities e ON ec.entity_id = e.id
            WHERE e.name = %s
        """, (entity_name,))
        characteristics = [row[0] for row in cur.fetchall()]
        return jsonify(characteristics)
    finally:
        cur.close()
        conn.close()

@app.route('/get_characteristic_values')
def get_characteristic_values():
    """Получает уникальные значения для характеристики"""
    entity_name = request.args.get('entity_name')
    characteristic_name = request.args.get('characteristic_name')
    if not entity_name or not characteristic_name:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT ov.value
            FROM object_values ov
            JOIN objects o ON ov.object_id = o.id
            JOIN entities e ON o.entity_id = e.id
            JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            WHERE e.name = %s AND ec.name = %s
        """, (entity_name, characteristic_name))
        values = [row[0] for row in cur.fetchall()]
        return jsonify(values)
    finally:
        cur.close()
        conn.close()

@app.route('/filter_by_params', methods=['POST'])
def filter_by_params():
    data = request.json
    entity_name = data.get('entity')
    filters = data.get('filters')
    if not entity_name or not filters:
        return jsonify([])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. Получаем ID объектов, которые соответствуют фильтрам
        query = """
            SELECT DISTINCT o.id
            FROM object_values ov
            JOIN objects o ON ov.object_id = o.id
            JOIN entities e ON o.entity_id = e.id
            JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            WHERE e.name = %s
        """
        params = [entity_name]
        for char_name, value in filters.items():
            query += " AND ec.name = %s AND ov.value = %s"
            params.extend([char_name, value])
        cur.execute(query, params)
        filtered_object_ids = [row[0] for row in cur.fetchall()]

        # Если нет подходящих объектов, возвращаем пустой список
        if not filtered_object_ids:
            return jsonify([])

        # 2. Получаем полные данные для отфильтрованных объектов
        all_entities = get_all_data()
        filtered_entities = []
        for entity in all_entities:
            if entity['name'] == entity_name:
                # Фильтруем объекты по их ID
                filtered_objects = [
                    obj for obj in entity['objects']
                    if obj['id'] in filtered_object_ids
                ]
                if filtered_objects:
                    filtered_entity = {
                        'id': entity['id'],
                        'name': entity['name'],
                        'category': entity['category'],
                        'subcategory': entity['subcategory'],
                        'characteristics': entity['characteristics'],
                        'objects': filtered_objects
                    }
                    filtered_entities.append(filtered_entity)
        return jsonify(filtered_entities)
    finally:
        cur.close()
        conn.close()

def get_all_data():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                e.id AS entity_id,
                e.name AS entity_name,
                c.name AS category,
                sc.name AS subcategory,
                ec.id AS characteristic_id,
                ec.name AS characteristic_name,
                ec.data_type,
                ec.unit,
                o.id AS object_id,
                o.name AS object_name,
                ov.value AS characteristic_value
            FROM entities e
            LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
            LEFT JOIN categories c ON sc.category_id = c.id
            LEFT JOIN objects o ON o.entity_id = e.id
            LEFT JOIN object_values ov ON ov.object_id = o.id
            LEFT JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            ORDER BY e.name, o.name;
        """)
        results = cur.fetchall()

        # Группируем данные
        grouped_data = {}
        for row in results:
            entity_id, entity_name, category, subcategory, char_id, char_name, data_type, unit, obj_id, obj_name, char_value = row
            if entity_id not in grouped_data:
                grouped_data[entity_id] = {
                    'id': entity_id,
                    'name': entity_name,
                    'category': category if category else '',
                    'subcategory': subcategory if subcategory else '',
                    'objects': {},
                    'characteristics': {}
                }
            if obj_id and obj_id not in grouped_data[entity_id]['objects']:
                grouped_data[entity_id]['objects'][obj_id] = {
                    'id': obj_id,
                    'name': obj_name,
                    'characteristics_info': {}
                }
            if char_id:
                grouped_data[entity_id]['characteristics'][char_id] = {
                    'id': char_id,
                    'name': char_name,
                    'data_type': data_type if data_type else '',
                    'unit': unit if unit else ''
                }
                if obj_id and char_value:
                    grouped_data[entity_id]['objects'][obj_id]['characteristics_info'][char_id] = {
                        'name': char_name,
                        'value': char_value,
                        'unit': unit if unit else ''
                    }

        # Преобразуем данные в список
        result = []
        for entity_data in grouped_data.values():
            entity = {
                'id': entity_data['id'],
                'name': entity_data['name'],
                'category': entity_data['category'],
                'subcategory': entity_data['subcategory'],
                'characteristics': list(entity_data['characteristics'].values()),
                'objects': list(entity_data['objects'].values())
            }
            result.append(entity)
        return result
    finally:
        cur.close()
        conn.close()

# Маршруты для корзины
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    object_id = request.json.get('object_id')
    quantity = int(request.json.get('quantity', 1))
    if 'cart' not in session:
        session['cart'] = {}
    session['cart'][object_id] = session['cart'].get(object_id, 0) + quantity
    session.modified = True
    return jsonify({
        'success': True,
        'cart_count': sum(session['cart'].values())
    })

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    object_id = request.json.get('object_id')
    if 'cart' in session and object_id in session['cart']:
        del session['cart'][object_id]
        session.modified = True
    return jsonify({
        'success': True,
        'cart_count': sum(session.get('cart', {}).values())
    })

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    if 'cart' in session:
        session.pop('cart')
        session.modified = True
    return jsonify({
        'success': True,
        'cart_count': 0
    })

@app.route('/update_cart_quantity', methods=['POST'])
def update_cart_quantity():
    object_id = request.json.get('object_id')
    quantity = int(request.json.get('quantity', 1))
    if 'cart' in session and object_id in session['cart']:
        session['cart'][object_id] = quantity
        session.modified = True
    return jsonify({
        'success': True,
        'cart_count': sum(session.get('cart', {}).values())
    })

@app.route('/cart_count')
def cart_count():
    """Возвращает количество товаров в корзине."""
    count = sum(session.get('cart', {}).values())
    return jsonify({'success': True, 'count': count})

@app.route('/cart')
def view_cart():
    """Страница корзины."""
    if 'cart' not in session or not session['cart']:
        return render_template('cart.html', cart_entities=[], cart_items={})
    cart_entities = get_entities_by_object_ids(session['cart'].keys())
    return render_template('cart.html',
                           cart_entities=cart_entities,
                           cart_items=session['cart'])
def get_entities_by_object_ids(object_ids):
    if not object_ids:
        return []
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        placeholders = ','.join(['%s'] * len(object_ids))
        cur.execute(f"""
            SELECT 
                e.id AS entity_id,
                e.name AS entity_name,
                c.name AS category,
                sc.name AS subcategory,
                ec.id AS characteristic_id,
                ec.name AS characteristic_name,
                ec.data_type,
                ec.unit,
                o.id AS object_id,
                o.name AS object_name,
                ov.value AS characteristic_value
            FROM objects o
            JOIN entities e ON o.entity_id = e.id
            LEFT JOIN object_values ov ON ov.object_id = o.id
            LEFT JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
            LEFT JOIN categories c ON sc.category_id = c.id
            WHERE o.id IN ({placeholders})
            ORDER BY e.name, o.name;
        """, tuple(object_ids))
        results = cur.fetchall()

        grouped_data = {}
        for row in results:
            entity_id, entity_name, category, subcategory, char_id, char_name, data_type, unit, obj_id, obj_name, char_value = row
            if entity_id not in grouped_data:
                grouped_data[entity_id] = {
                    'id': entity_id,
                    'name': entity_name,
                    'category': category if category else '',
                    'subcategory': subcategory if subcategory else '',
                    'objects': {},
                    'characteristics': {}
                }
            if obj_id not in grouped_data[entity_id]['objects']:
                grouped_data[entity_id]['objects'][obj_id] = {
                    'id': obj_id,
                    'name': obj_name,
                    'characteristics_info': {}
                }
            if char_id:
                grouped_data[entity_id]['characteristics'][char_id] = {
                    'id': char_id,
                    'name': char_name,
                    'data_type': data_type if data_type else '',
                    'unit': unit if unit else ''
                }
                if char_value:
                    grouped_data[entity_id]['objects'][obj_id]['characteristics_info'][char_id] = {
                        'name': char_name,
                        'value': char_value,
                        'unit': unit if unit else ''
                    }

        return [{'id': e['id'], 'name': e['name'], 'category': e['category'],
                 'subcategory': e['subcategory'], 'objects': list(e['objects'].values()),
                 'characteristics': list(e['characteristics'].values())}
                for e in grouped_data.values()]
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)