import pandas as pd
import psycopg2
import re
from tqdm import tqdm

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
                    'characteristics': set(),
                    'objects': {}
                }

        # Обновляем текущий объект
        object_name = row.iloc[1]
        if pd.notna(object_name) and current_entity:
            current_object = object_name
            if current_object not in data[current_entity]['objects']:
                data[current_entity]['objects'][current_object] = {}

        # Добавляем характеристики
        characteristic = row.iloc[5]
        value = row.iloc[8] if pd.notna(row.iloc[8]) else row.iloc[9]

        if pd.notna(characteristic) and current_entity and current_object:
            data[current_entity]['characteristics'].add(characteristic)
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

            # Добавляем характеристики сущности
            for char_name in entity_data['characteristics']:
                cur.execute(
                    """INSERT INTO entity_characteristics (entity_id, name)
                    VALUES (%s, %s) ON CONFLICT (entity_id, name) DO NOTHING;""",
                    (entity_id, char_name)
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


if __name__ == '__main__':
    file_path = 'part.xlsx'
    print(f"Анализ файла {file_path}...")
    structured_data = parse_excel(file_path)

    print("\nНайдены следующие данные:")
    for entity, data in structured_data.items():
        print(f"\nСущность: {entity}")


    print("\nНачинаем импорт в базу данных...")
    import_to_database(structured_data)