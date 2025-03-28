import pandas as pd
import psycopg2
import re
import logging

# Параметры подключения к базе данных
db_params = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

# Чтение данных из xlsx файла
file_path = 'part.xlsx'
df = pd.read_excel(file_path)

# Выделение уникальных сущностей
df['entity'] = df[df.columns[1]].str.replace(r" тип \d+", "", regex=True)
unique_entities = df.drop_duplicates(subset='entity')['entity'].dropna().tolist()

# Инициализация переменных
entity_data = {}
current_entity = None

# Проход по строкам и группировка данных
for index, row in df.iterrows():
    if index < 4:
        continue  # Пропускаем первые 4 строки

    entity = row['entity']
    object_name = row.iloc[1]  # Имя объекта (включая тип)
    characteristic = row.iloc[5]  # Характеристика
    value_9 = row.iloc[8]  # Значение характеристики в столбце I
    value_10 = row.iloc[9]  # Значение характеристики в столбце J

    if pd.notna(entity):
        current_entity = entity

    if pd.notna(characteristic) and current_entity is not None and pd.notna(object_name):
        value = value_9 if pd.notna(value_9) else (value_10 if pd.notna(value_10) else None)
        if current_entity not in entity_data:
            entity_data[current_entity] = {}
        if object_name not in entity_data[current_entity]:
            entity_data[current_entity][object_name] = []
        entity_data[current_entity][object_name].append((characteristic, value))

# Подключение к базе данных
conn = psycopg2.connect(**db_params)
cur = conn.cursor()

# Создание таблиц
try:
    # Таблица сущностей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entities (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL
    );
    """)

    # Таблица характеристик (общая для всех сущностей)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS characteristics (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL
    );
    """)

    # Таблица объектов
    cur.execute("""
    CREATE TABLE IF NOT EXISTS objects (
        id SERIAL PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES entities(id),
        name VARCHAR(255) NOT NULL,
        CONSTRAINT unique_object UNIQUE (entity_id, name)
    );
    """)

    # Таблица значений характеристик объектов
    cur.execute("""
    CREATE TABLE IF NOT EXISTS object_characteristics (
        id SERIAL PRIMARY KEY,
        object_id INTEGER NOT NULL REFERENCES objects(id),
        characteristic_id INTEGER NOT NULL REFERENCES characteristics(id),
        value TEXT,
        CONSTRAINT unique_object_characteristic UNIQUE (object_id, characteristic_id)
    );
    """)

    conn.commit()

    # Вставка данных
    for entity, objects in entity_data.items():
        # Вставка сущности
        cur.execute("""
        INSERT INTO entities (name) VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id;
        """, (entity,))

        entity_id_result = cur.fetchone()
        if not entity_id_result:
            cur.execute("SELECT id FROM entities WHERE name = %s;", (entity,))
            entity_id_result = cur.fetchone()
        entity_id = entity_id_result[0]

        # Обработка объектов сущности
        for object_name, characteristics in objects.items():
            # Вставка объекта
            cur.execute("""
            INSERT INTO objects (entity_id, name) VALUES (%s, %s)
            ON CONFLICT (entity_id, name) DO NOTHING
            RETURNING id;
            """, (entity_id, object_name))

            object_id_result = cur.fetchone()
            if not object_id_result:
                cur.execute("""
                SELECT id FROM objects 
                WHERE entity_id = %s AND name = %s;
                """, (entity_id, object_name))
                object_id_result = cur.fetchone()
            object_id = object_id_result[0]

            # Вставка характеристик и их значений
            for characteristic, value in characteristics:
                # Вставка характеристики (если еще нет)
                cur.execute("""
                INSERT INTO characteristics (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id;
                """, (characteristic,))

                char_id_result = cur.fetchone()
                if not char_id_result:
                    cur.execute("""
                    SELECT id FROM characteristics 
                    WHERE name = %s;
                    """, (characteristic,))
                    char_id_result = cur.fetchone()
                char_id = char_id_result[0]

                # Вставка значения характеристики для объекта
                cur.execute("""
                INSERT INTO object_characteristics 
                (object_id, characteristic_id, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (object_id, characteristic_id) 
                DO UPDATE SET value = EXCLUDED.value;
                """, (object_id, char_id, value))

    conn.commit()
    print("Данные успешно вставлены в базу данных.")

except Exception as e:
    conn.rollback()
    print(f"Ошибка: {e}")
finally:
    cur.close()
    conn.close()