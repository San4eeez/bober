import pandas as pd
import psycopg2
from tqdm import tqdm

DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}


def parse_excel(file_path):
    """Анализирует Excel-файл и возвращает структурированные данные"""
    df = pd.read_excel(file_path)

    # Очищаем данные - удаляем полностью пустые строки
    df = df.dropna(how='all').reset_index(drop=True)

    # Извлекаем сущности из второго столбца
    df['entity'] = df.iloc[:, 1].str.extract(r'^(.*?)(?:\s+тип\s+\d+)?$')[0]
    df['category'] = df.iloc[:, 14]  # Столбец 15 (индекс 14)
    df['subcategory'] = df.iloc[:, 11]  # Столбец 12 (индекс 11)

    data = {}
    current_entity = None
    current_object = None

    for index, row in df.iterrows():
        # Пропускаем заголовки (первые 4 строки)
        if index < 4:
            continue

        # Обновляем текущую сущность
        if pd.notna(row['entity']):
            current_entity = row['entity']
            if current_entity not in data:
                data[current_entity] = {
                    'category': row['category'],
                    'subcategory': row['subcategory'],
                    'characteristics': {},
                    'objects': {}
                }

        # Обновляем текущий объект
        object_name = row.iloc[1]
        if pd.notna(object_name) and current_entity:
            current_object = object_name
            if current_object not in data[current_entity]['objects']:
                data[current_entity]['objects'][current_object] = {}

        # Пропускаем строки без характеристик
        characteristic = row.iloc[5]
        if pd.isna(characteristic) or not current_entity or not current_object:
            continue

        # Обработка единиц измерения
        unit = row.iloc[10] if pd.notna(row.iloc[10]) and row.iloc[10] != '-' else None

        # Обработка значений (min, max, обычное значение)
        min_val = row.iloc[6] if pd.notna(row.iloc[6]) else None
        max_val = row.iloc[7] if pd.notna(row.iloc[7]) else None

        # Формируем значение
        if min_val is not None and max_val is not None:
            value = f"{min_val}...{max_val}"
        elif min_val is not None:
            value = f"≥{min_val}"
        elif max_val is not None:
            value = f"≤{max_val}"
        else:
            value = row.iloc[8] if pd.notna(row.iloc[8]) else row.iloc[9] if pd.notna(row.iloc[9]) else None

        # Добавляем характеристику если есть значение
        if value is not None:
            # Добавляем характеристику в список характеристик сущности
            if characteristic not in data[current_entity]['characteristics']:
                data[current_entity]['characteristics'][characteristic] = {
                    'unit': unit,
                    'data_type': row.iloc[4] if pd.notna(row.iloc[4]) else None
                }

            # Добавляем значение характеристики для объекта
            data[current_entity]['objects'][current_object][characteristic] = value

    return data


def import_to_database(data):
    """Импортирует данные в БД"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        # 1. Импорт категорий и подкатегорий
        categories = set()
        subcategories = set()

        for entity in data.values():
            if pd.notna(entity['category']):
                categories.add((entity['category'],))
            if pd.notna(entity['subcategory']):
                subcategories.add((entity['category'], entity['subcategory']))

        # Вставляем категории
        cur.executemany(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            categories
        )

        # Вставляем подкатегории
        for cat, subcat in subcategories:
            cur.execute("""
                INSERT INTO subcategories (category_id, name)
                SELECT id, %s FROM categories WHERE name = %s
                ON CONFLICT (category_id, name) DO NOTHING
            """, (subcat, cat))

        # 2. Импорт сущностей и характеристик
        for entity_name, entity_data in tqdm(data.items(), desc="Импорт сущностей"):
            # Получаем ID подкатегории
            cur.execute("""
                SELECT sc.id FROM subcategories sc
                JOIN categories c ON sc.category_id = c.id
                WHERE c.name = %s AND sc.name = %s
            """, (entity_data['category'], entity_data['subcategory']))
            subcategory_id = cur.fetchone()[0] if cur.rowcount > 0 else None

            # Вставляем сущность
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

            # 3. Импорт характеристик сущности
            characteristics_map = {}  # Для хранения соответствия имен характеристик их ID
            for char_name, char_data in entity_data['characteristics'].items():
                cur.execute("""
                    INSERT INTO entity_characteristics (entity_id, name, data_type, unit)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (entity_id, name) DO UPDATE
                    SET data_type = EXCLUDED.data_type,
                        unit = EXCLUDED.unit
                    RETURNING id
                """, (entity_id, char_name, char_data.get('data_type'), char_data.get('unit')))
                char_id = cur.fetchone()[0]
                characteristics_map[char_name] = char_id

            # 4. Импорт объектов и их значений
            for obj_name, obj_data in entity_data['objects'].items():
                cur.execute("""
                    INSERT INTO objects (entity_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (entity_id, name) DO NOTHING
                    RETURNING id
                """, (entity_id, obj_name))
                obj_id = cur.fetchone()[0] if cur.rowcount > 0 else None

                if not obj_id:
                    cur.execute("""
                        SELECT id FROM objects 
                        WHERE entity_id = %s AND name = %s
                    """, (entity_id, obj_name))
                    obj_id = cur.fetchone()[0]

                # 5. Импорт значений характеристик
                for char_name, value in obj_data.items():
                    if char_name in characteristics_map:
                        char_id = characteristics_map[char_name]
                        cur.execute("""
                            INSERT INTO object_values (object_id, characteristic_id, value)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (object_id, characteristic_id)
                            DO UPDATE SET value = EXCLUDED.value
                        """, (obj_id, char_id, str(value)))

        conn.commit()
        print("\nИмпорт данных успешно завершен!")

        # Проверка количества записей
        cur.execute("SELECT COUNT(*) FROM entity_characteristics")
        print(f"Характеристик импортировано: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM object_values")
        print(f"Значений характеристик импортировано: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"\nОшибка при импорте: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def import_to_database(data):
    """Импортирует данные в БД"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        # 1. Импорт категорий и подкатегорий
        categories = set()
        subcategories = set()

        for entity in data.values():
            if pd.notna(entity['category']):
                categories.add((entity['category'],))
            if pd.notna(entity['subcategory']):
                subcategories.add((entity['category'], entity['subcategory']))

        # Вставляем категории
        cur.executemany(
            "INSERT INTO categories (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            categories
        )

        # Вставляем подкатегории
        for cat, subcat in subcategories:
            cur.execute("""
                INSERT INTO subcategories (category_id, name)
                SELECT id, %s FROM categories WHERE name = %s
                ON CONFLICT (category_id, name) DO NOTHING
            """, (subcat, cat))

        # 2. Импорт сущностей
        for entity_name, entity_data in tqdm(data.items(), desc="Импорт сущностей"):
            # Получаем ID подкатегории
            cur.execute("""
                SELECT sc.id FROM subcategories sc
                JOIN categories c ON sc.category_id = c.id
                WHERE c.name = %s AND sc.name = %s
            """, (entity_data['category'], entity_data['subcategory']))
            subcategory_id = cur.fetchone()[0] if cur.rowcount > 0 else None

            # Вставляем сущность
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

            # 3. Импорт характеристик сущности
            for char_name, char_data in entity_data['characteristics'].items():
                cur.execute("""
                    INSERT INTO entity_characteristics (entity_id, name, data_type, unit)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (entity_id, name) DO UPDATE
                    SET data_type = EXCLUDED.data_type,
                        unit = EXCLUDED.unit
                    RETURNING id
                """, (entity_id, char_name, char_data.get('data_type'), char_data.get('unit')))

            # 4. Импорт объектов
            for obj_name, obj_data in entity_data['objects'].items():
                cur.execute("""
                    INSERT INTO objects (entity_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (entity_id, name) DO NOTHING
                    RETURNING id
                """, (entity_id, obj_name))
                obj_id = cur.fetchone()[0] if cur.rowcount > 0 else None

                if not obj_id:
                    cur.execute("""
                        SELECT id FROM objects 
                        WHERE entity_id = %s AND name = %s
                    """, (entity_id, obj_name))
                    obj_id = cur.fetchone()[0]

                # 5. Импорт значений характеристик
                for char_name, value in obj_data.items():
                    cur.execute("""
                        SELECT id FROM entity_characteristics
                        WHERE entity_id = %s AND name = %s
                    """, (entity_id, char_name))
                    res = cur.fetchone()
                    if res:
                        char_id = res[0]
                        cur.execute("""
                            INSERT INTO object_values (object_id, characteristic_id, value)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (object_id, characteristic_id)
                            DO UPDATE SET value = EXCLUDED.value
                        """, (obj_id, char_id, str(value)))

        conn.commit()
        print("\nИмпорт данных успешно завершен!")

        # Проверка количества записей
        cur.execute("SELECT COUNT(*) FROM entity_characteristics")
        print(f"Характеристик импортировано: {cur.fetchone()[0]}")
        cur.execute("SELECT COUNT(*) FROM object_values")
        print(f"Значений характеристик импортировано: {cur.fetchone()[0]}")

    except Exception as e:
        conn.rollback()
        print(f"\nОшибка при импорте: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def init_database():
    """Инициализирует структуру базы данных"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Удаляем существующие таблицы
        cur.execute("DROP TABLE IF EXISTS object_values")
        cur.execute("DROP TABLE IF EXISTS objects")
        cur.execute("DROP TABLE IF EXISTS entity_characteristics")
        cur.execute("DROP TABLE IF EXISTS entities")
        cur.execute("DROP TABLE IF EXISTS subcategories")
        cur.execute("DROP TABLE IF EXISTS categories")

        # Создаем таблицы
        cur.execute("""
            CREATE TABLE categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE subcategories (
                id SERIAL PRIMARY KEY,
                category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                UNIQUE(category_id, name)
            )
        """)

        cur.execute("""
            CREATE TABLE entities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                description TEXT,
                category VARCHAR(255),
                subcategory VARCHAR(255),
                subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL
            )
        """)

        cur.execute("""
            CREATE TABLE entity_characteristics (
                id SERIAL PRIMARY KEY,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                data_type VARCHAR(50),
                unit VARCHAR(50),
                UNIQUE(entity_id, name)
            )
        """)

        cur.execute("""
            CREATE TABLE objects (
                id SERIAL PRIMARY KEY,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                UNIQUE(entity_id, name)
            )
        """)

        cur.execute("""
            CREATE TABLE object_values (
                id SERIAL PRIMARY KEY,
                object_id INTEGER NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
                characteristic_id INTEGER NOT NULL REFERENCES entity_characteristics(id),
                value TEXT,
                UNIQUE(object_id, characteristic_id)
            )
        """)

        print("База данных успешно инициализирована")
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    # 1. Инициализация БД
    print("Инициализация структуры БД...")
    init_database()

    # 2. Импорт данных из Excel
    file_path = 'part.xlsx'  # Укажите путь к вашему файлу
    print(f"\nАнализ файла {file_path}...")
    data = parse_excel(file_path)

    # Вывод информации о данных перед импортом
    print("\nНайдены следующие данные:")
    for entity_name, entity_data in data.items():
        print(f"\nСущность: {entity_name}")
        print(f"Категория: {entity_data['category']}")
        print(f"Подкатегория: {entity_data['subcategory']}")
        print(f"Характеристики: {len(entity_data['characteristics'])}")
        print(f"Объекты: {len(entity_data['objects'])}")
        for obj_name, obj_data in entity_data['objects'].items():
            print(f"  Объект '{obj_name}': {len(obj_data)} значений характеристик")

    # 3. Импорт в БД
    print("\nНачинаем импорт в базу данных...")
    import_to_database(data)