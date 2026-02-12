import pandas as pd
import psycopg2

DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}


# ===================== PARSE EXCEL =====================

def parse_excel(file_path):
    """Анализирует Excel-файл и возвращает структурированные данные"""
    df = pd.read_excel(file_path)

    df = df.dropna(how='all').reset_index(drop=True)

    df['entity'] = df.iloc[:, 1].str.extract(r'^(.*?)(?:\s+тип\s+\d+)?$')[0]
    df['category'] = df.iloc[:, 14]
    df['subcategory'] = df.iloc[:, 11]

    data = {}
    current_entity = None
    current_object = None

    for index, row in df.iterrows():
        if index < 4:
            continue

        if pd.notna(row['entity']):
            current_entity = row['entity']
            if current_entity not in data:
                data[current_entity] = {
                    'category': row['category'],
                    'subcategory': row['subcategory'],
                    'characteristics': {},
                    'objects': {}
                }

        object_name = row.iloc[1]
        if pd.notna(object_name) and current_entity:
            current_object = object_name
            if current_object not in data[current_entity]['objects']:
                data[current_entity]['objects'][current_object] = {}

        characteristic = row.iloc[5]
        if pd.isna(characteristic) or not current_entity or not current_object:
            continue

        unit = row.iloc[10] if pd.notna(row.iloc[10]) and row.iloc[10] != '-' else None

        min_val = row.iloc[6] if pd.notna(row.iloc[6]) else None
        max_val = row.iloc[7] if pd.notna(row.iloc[7]) else None

        if min_val is not None and max_val is not None:
            value = f"{min_val}...{max_val}"
        elif min_val is not None:
            value = f"≥{min_val}"
        elif max_val is not None:
            value = f"≤{max_val}"
        else:
            value = row.iloc[8] if pd.notna(row.iloc[8]) else row.iloc[9] if pd.notna(row.iloc[9]) else None

        if value is not None:
            if characteristic not in data[current_entity]['characteristics']:
                data[current_entity]['characteristics'][characteristic] = {
                    'unit': unit,
                    'data_type': row.iloc[4] if pd.notna(row.iloc[4]) else None
                }

            data[current_entity]['objects'][current_object][characteristic] = value

    return data


# ===================== DATABASE IMPORT =====================

def import_to_database(data, progress_cb=None):
    """Импортирует данные в БД с прогрессом"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        categories = set()
        subcategories = set()

        for entity in data.values():
            if pd.notna(entity['category']):
                categories.add((entity['category'],))
            if pd.notna(entity['subcategory']):
                subcategories.add((entity['category'], entity['subcategory']))

        cur.executemany(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            categories
        )

        for cat, subcat in subcategories:
            cur.execute("""
                INSERT INTO subcategories (category_id, name)
                SELECT id, %s FROM categories WHERE name = %s
                ON CONFLICT (category_id, name) DO NOTHING
            """, (subcat, cat))

        total = len(data)
        processed = 0

        for entity_name, entity_data in data.items():
            processed += 1
            if progress_cb:
                progress_cb(int(processed / total * 100))

            cur.execute("""
                SELECT sc.id FROM subcategories sc
                JOIN categories c ON sc.category_id = c.id
                WHERE c.name = %s AND sc.name = %s
            """, (entity_data['category'], entity_data['subcategory']))
            res = cur.fetchone()
            subcategory_id = res[0] if res else None

            cur.execute("""
                INSERT INTO entities (name, category, subcategory, subcategory_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                SET category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    subcategory_id = EXCLUDED.subcategory_id
                RETURNING id
            """, (entity_name, entity_data['category'], entity_data['subcategory'], subcategory_id))
            entity_id = cur.fetchone()[0]

            characteristics_map = {}

            for char_name, char_data in entity_data['characteristics'].items():
                cur.execute("""
                    INSERT INTO entity_characteristics (entity_id, name, data_type, unit)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (entity_id, name) DO UPDATE
                    SET data_type = EXCLUDED.data_type,
                        unit = EXCLUDED.unit
                    RETURNING id
                """, (entity_id, char_name, char_data.get('data_type'), char_data.get('unit')))
                characteristics_map[char_name] = cur.fetchone()[0]

            for obj_name, obj_data in entity_data['objects'].items():
                cur.execute("""
                    INSERT INTO objects (entity_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (entity_id, name) DO NOTHING
                    RETURNING id
                """, (entity_id, obj_name))
                row = cur.fetchone()
                if row:
                    obj_id = row[0]
                else:
                    cur.execute("SELECT id FROM objects WHERE entity_id=%s AND name=%s",
                                (entity_id, obj_name))
                    obj_id = cur.fetchone()[0]

                for char_name, value in obj_data.items():
                    if char_name in characteristics_map:
                        cur.execute("""
                            INSERT INTO object_values (object_id, characteristic_id, value)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (object_id, characteristic_id)
                            DO UPDATE SET value = EXCLUDED.value
                        """, (obj_id, characteristics_map[char_name], str(value)))

        conn.commit()

    finally:
        cur.close()
        conn.close()
