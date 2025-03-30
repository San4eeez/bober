from flask import Flask, render_template, request, jsonify
import psycopg2

app = Flask(__name__)

# Конфигурация БД
DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()

    # Получаем категории и подкатегории с количеством объектов
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
    for category, subcategory, count in cur.fetchall():
        if category not in categories:
            categories[category] = {'count': 0, 'subcategories': []}
        if subcategory:
            categories[category]['subcategories'].append({
                'name': subcategory,
                'count': count
            })
            categories[category]['count'] += count

    # Получаем все сущности
    entities = get_all_data()

    return render_template('index.html',
                           categories=[{'name': k, **v} for k, v in categories.items()],
                           entities=entities)

@app.route('/filter')
def filter_entities():
    category = request.args.get('category')
    subcategory = request.args.get('subcategory')

    conn = get_db_connection()
    cur = conn.cursor()

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
                e.name AS entity,
                o.name AS object
            FROM objects o
            JOIN entities e ON o.entity_id = e.id
            WHERE o.name ILIKE %s
            ORDER BY e.name, o.name;
        """, (f"%{query}%",))

        results = []
        for row in cur.fetchall():
            entity, object_name = row
            results.append({
                'entity': entity,
                'object': object_name
            })

        return jsonify(results)
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
        query = """
            SELECT e.name AS entity, o.name AS object, ec.name AS characteristic, ov.value
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
        results = cur.fetchall()

        filtered_data = []
        for row in results:
            entity, object_name, characteristic, value = row
            filtered_data.append({
                'entity': entity,
                'object': object_name,
                'characteristic': characteristic,
                'value': value
            })

        return jsonify(filtered_data)
    finally:
        cur.close()
        conn.close()

def get_all_data():
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 1. Получаем все сущности с категориями
        cur.execute("""
            SELECT e.id, e.name, c.name as category, sc.name as subcategory
            FROM entities e
            LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
            LEFT JOIN categories c ON sc.category_id = c.id
            ORDER BY e.name
        """)
        entities = {}
        for row in cur.fetchall():
            entity_id, entity_name, category, subcategory = row
            entities[entity_id] = {
                'id': entity_id,
                'name': entity_name,
                'category': category if category else '',
                'subcategory': subcategory if subcategory else '',
                'characteristics': [],
                'objects': []
            }

        # 2. Получаем все характеристики для сущностей
        cur.execute("""
            SELECT ec.id, ec.entity_id, ec.name, ec.data_type, ec.unit
            FROM entity_characteristics ec
            ORDER BY ec.entity_id, ec.name
        """)
        characteristics = {}
        for row in cur.fetchall():
            char_id, entity_id, char_name, data_type, unit = row
            char_info = {
                'id': char_id,
                'name': char_name,
                'data_type': data_type if data_type else '',
                'unit': unit if unit else ''
            }
            if entity_id in entities:
                entities[entity_id]['characteristics'].append(char_info)
            characteristics[char_id] = char_info

        # 3. Получаем все объекты
        cur.execute("""
            SELECT o.id, o.entity_id, o.name
            FROM objects o
            ORDER BY o.entity_id, o.name
        """)
        objects = {}
        for row in cur.fetchall():
            obj_id, entity_id, obj_name = row
            if entity_id in entities:
                obj_info = {
                    'id': obj_id,
                    'name': obj_name,
                    'values': {}
                }
                entities[entity_id]['objects'].append(obj_info)
                objects[obj_id] = obj_info

        # 4. Получаем все значения характеристик объектов
        cur.execute("""
            SELECT ov.object_id, ov.characteristic_id, ov.value
            FROM object_values ov
            ORDER BY ov.object_id, ov.characteristic_id
        """)
        for row in cur.fetchall():
            obj_id, char_id, value = row
            if obj_id in objects and char_id in characteristics:
                objects[obj_id]['values'][str(char_id)] = value

        result = []
        for entity in entities.values():
            for obj in entity['objects']:
                obj['characteristics_info'] = {}
                for char_id, value in obj['values'].items():
                    if int(char_id) in characteristics:
                        char_info = characteristics[int(char_id)]
                        obj['characteristics_info'][char_id] = {
                            'name': char_info['name'],
                            'value': value,
                            'unit': char_info['unit']
                        }
            result.append(entity)

        return result
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)