import psycopg2
import pandas as pd
from tqdm import tqdm
import re

# Конфигурация БД
DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}


def init_database():
    """Инициализирует структуру базы данных"""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Удаляем существующие таблицы (для чистой установки)
        cur.execute("DROP TABLE IF EXISTS object_values")
        cur.execute("DROP TABLE IF EXISTS objects")
        cur.execute("DROP TABLE IF EXISTS entity_characteristics")
        cur.execute("DROP TABLE IF EXISTS entities")

        # Создаем таблицы
        cur.execute("""
            CREATE TABLE entities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                description TEXT
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


def get_db_connection():
    """Возвращает соединение с базой данных"""
    return psycopg2.connect(**DB_CONFIG)


def parse_excel(file_path):
    """Анализирует Excel-файл и возвращает структурированные данные"""
    df = pd.read_excel(file_path)

    # Очищаем данные
    df = df.dropna(how='all')
    df = df.reset_index(drop=True)

    # Извлекаем сущности из второго столбца
    df['entity'] = df.iloc[:, 1].str.extract(r'^(.*?)(?:\s+тип\s+\d+)?$')[0]

    # Собираем данные
    data = {}
    current_entity = None
    current_object = None

    for index, row in df.iterrows():
        # Пропускаем заголовки
        if index < 4:
            continue

        # Обновляем текущую сущность
        if pd.notna(row['entity']):
            current_entity = row['entity']
            if current_entity not in data:
                data[current_entity] = {
                    'characteristics': {},  # Теперь храним словарь с характеристиками и единицами измерения
                    'objects': {}
                }

        # Обновляем текущий объект
        object_name = row.iloc[1]
        if pd.notna(object_name) and current_entity:
            current_object = object_name
            if current_object not in data[current_entity]['objects']:
                data[current_entity]['objects'][current_object] = {}

        # Добавляем характеристики и их единицы измерения
        characteristic = row.iloc[5]
        unit = row.iloc[10] if pd.notna(row.iloc[10]) and row.iloc[10] != '-' else None

        # Получаем минимальное и максимальное значения
        min_value = row.iloc[6] if pd.notna(row.iloc[6]) else None
        max_value = row.iloc[7] if pd.notna(row.iloc[7]) else None

        # Формируем значение для характеристики
        if pd.notna(characteristic) and current_entity and current_object:
            # Сохраняем характеристику и единицу измерения
            if characteristic not in data[current_entity]['characteristics']:
                data[current_entity]['characteristics'][characteristic] = unit

            # Формируем значение в зависимости от наличия min/max
            if min_value is not None and max_value is not None:
                value = f"{min_value}...{max_value}"
            elif min_value is not None:
                value = f"≥{min_value}"
            elif max_value is not None:
                value = f"≤{max_value}"
            else:
                value = row.iloc[8] if pd.notna(row.iloc[8]) else row.iloc[9] if pd.notna(row.iloc[9]) else None

            if value is not None:
                data[current_entity]['objects'][current_object][characteristic] = value

    return data

def import_to_database(data):
    """Импортирует структурированные данные в БД"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Импорт сущностей и их характеристик
        for entity_name, entity_data in tqdm(data.items(), desc="Импорт сущностей"):
            # Добавляем сущность
            cur.execute(
                "INSERT INTO entities (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id;",
                (entity_name,)
            )
            entity_id = cur.fetchone()[0] if cur.rowcount > 0 else None

            if not entity_id:
                cur.execute("SELECT id FROM entities WHERE name = %s;", (entity_name,))
                entity_id = cur.fetchone()[0]

            # Добавляем характеристики сущности с единицами измерения
            for char_name, unit in entity_data['characteristics'].items():
                cur.execute(
                    """INSERT INTO entity_characteristics (entity_id, name, unit)
                    VALUES (%s, %s, %s) 
                    ON CONFLICT (entity_id, name) 
                    DO UPDATE SET unit = EXCLUDED.unit;""",
                    (entity_id, char_name, unit)
                )

        # Импорт объектов и их значений
        for entity_name, entity_data in tqdm(data.items(), desc="Импорт объектов"):
            # Получаем ID сущности
            cur.execute("SELECT id FROM entities WHERE name = %s;", (entity_name,))
            entity_id = cur.fetchone()[0]

            # Получаем характеристики сущности
            cur.execute(
                "SELECT id, name FROM entity_characteristics WHERE entity_id = %s;",
                (entity_id,)
            )
            characteristics = {name: id for id, name in cur.fetchall()}

            # Добавляем объекты
            for obj_name, obj_data in entity_data['objects'].items():
                # Добавляем объект
                cur.execute(
                    """INSERT INTO objects (entity_id, name)
                    VALUES (%s, %s) ON CONFLICT (entity_id, name) DO NOTHING RETURNING id;""",
                    (entity_id, obj_name)
                )
                obj_id = cur.fetchone()[0] if cur.rowcount > 0 else None

                if not obj_id:
                    cur.execute(
                        "SELECT id FROM objects WHERE entity_id = %s AND name = %s;",
                        (entity_id, obj_name)
                    )
                    obj_id = cur.fetchone()[0]

                # Добавляем значения характеристик
                for char_name, value in obj_data.items():
                    if char_name in characteristics and pd.notna(value):
                        cur.execute(
                            """INSERT INTO object_values (object_id, characteristic_id, value)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (object_id, characteristic_id)
                            DO UPDATE SET value = EXCLUDED.value;""",
                            (obj_id, characteristics[char_name], str(value))
                        )

        conn.commit()
        print("Импорт данных успешно завершен!")

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при импорте: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def main():
    # Инициализация базы данных
    init_database()

    # Путь к файлу Excel
    file_path = 'part.xlsx'

    print(f"Анализ файла {file_path}...")
    structured_data = parse_excel(file_path)

    print("\nНайдены следующие данные:")
    for entity, data in structured_data.items():
        print(f"\nСущность: {entity}")
        print(f"Характеристики: {len(data['characteristics'])}")
        print(f"Объекты: {len(data['objects'])}")

    print("\nНачинаем импорт в базу данных...")
    import_to_database(structured_data)


if __name__ == '__main__':
    main()