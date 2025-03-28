from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2 import sql

app = Flask(__name__)

# Конфигурация БД
DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}


def get_db():
    return psycopg2.connect(**DB_CONFIG)


@app.route('/')
def index():
    entities = get_all_data()
    return render_template('index.html', entities=entities)


def get_all_data():
    """Получает все данные из БД в структурированном виде"""
    conn = get_db()
    cur = conn.cursor()

    try:
        # Получаем все сущности с их характеристиками
        cur.execute("""
            SELECT e.id, e.name, ec.id, ec.name, ec.data_type
            FROM entities e
            LEFT JOIN entity_characteristics ec ON e.id = ec.entity_id
            ORDER BY e.name, ec.name;
        """)

        entities = {}
        characteristics = {}  # Словарь для быстрого доступа к характеристикам

        for row in cur.fetchall():
            entity_id, entity_name, char_id, char_name, data_type = row
            if entity_id not in entities:
                entities[entity_id] = {
                    'id': entity_id,
                    'name': entity_name,
                    'characteristics': [],
                    'objects': []
                }
            if char_id:
                char_info = {
                    'id': char_id,
                    'name': char_name,
                    'data_type': data_type
                }
                entities[entity_id]['characteristics'].append(char_info)
                characteristics[char_id] = char_info

        # Получаем все объекты с их значениями
        cur.execute("""
            SELECT o.id, o.entity_id, o.name, 
                   json_object_agg(
                       ov.characteristic_id, ov.value
                   ) FILTER (WHERE ov.characteristic_id IS NOT NULL) as values
            FROM objects o
            LEFT JOIN object_values ov ON o.id = ov.object_id
            GROUP BY o.id, o.entity_id, o.name
            ORDER BY o.entity_id, o.name;
        """)

        for row in cur.fetchall():
            object_id, entity_id, object_name, values = row
            if entity_id in entities:
                obj = {
                    'id': object_id,
                    'name': object_name,
                    'values': values or {}  # Гарантируем, что values будет словарём
                }
                entities[entity_id]['objects'].append(obj)

        # Преобразуем в список и добавляем информацию о характеристиках в объекты
        result = []
        for entity in entities.values():
            # Создаем список ID характеристик для быстрой проверки
            char_ids = [str(char['id']) for char in entity['characteristics']]

            # Добавляем информацию о характеристиках в каждый объект
            for obj in entity['objects']:
                obj['characteristics_info'] = {}
                for char_id, value in obj['values'].items():
                    if int(char_id) in characteristics:
                        obj['characteristics_info'][char_id] = {
                            'name': characteristics[int(char_id)]['name'],
                            'value': value
                        }

            result.append(entity)

        return result

    finally:
        cur.close()
        conn.close()


@app.route('/search', methods=['GET'])
def search():
    """Поиск по значениям характеристик"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT 
                e.name AS entity,
                o.name AS object,
                ec.name AS characteristic,
                ov.value AS value
            FROM object_values ov
            JOIN objects o ON ov.object_id = o.id
            JOIN entities e ON o.entity_id = e.id
            JOIN entity_characteristics ec ON ov.characteristic_id = ec.id
            WHERE ov.value ILIKE %s
            ORDER BY e.name, o.name, ec.name;
        """, (f"%{query}%",))

        results = []
        for row in cur.fetchall():
            results.append({
                'entity': row[0],
                'object': row[1],
                'characteristic': row[2],
                'value': row[3]
            })

        return jsonify(results)

    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    app.run(debug=True)