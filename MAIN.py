import pandas as pd
import psycopg2
import re

# Параметры подключения к базе данных
db_params = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}

# Чтение данных из xlsx файла
file_path = 'part.xlsx'
df = pd.read_excel(file_path)

# Очистка названий сущностей
def clean_entity_name(name):
    if pd.isna(name):
        return None
    # Удаляем лишние символы (например, цифры и специальные знаки)
    name = re.sub(r'[^\w\s]', '', str(name)).strip()
    return name

# Выделение уникальных сущностей
df['entity'] = df[df.columns[1]].apply(clean_entity_name)
unique_entities = df.drop_duplicates(subset='entity')['entity'].dropna().tolist()

# Инициализация переменных
entity_data = {}
current_entity = None  # Инициализируем current_entity

# Проход по строкам и группировка данных
for index, row in df.iterrows():
    if index < 4:
        continue  # Пропускаем первые 4 строки

    entity = row['entity']
    object_name = row[1]  # Имя объекта (включая тип)
    characteristic = row[5]  # Характеристика
    value_9 = row[8]  # Значение характеристики в столбце I
    value_10 = row[9]  # Значение характеристики в столбце J

    if pd.notna(entity):
        current_entity = entity

    if pd.notna(characteristic) and current_entity is not None:
        value = value_9 if pd.notna(value_9) else (value_10 if pd.notna(value_10) else None)
        if current_entity not in entity_data:
            entity_data[current_entity] = []
        entity_data[current_entity].append((object_name, characteristic, value))

# Подключение к базе данных
conn = psycopg2.connect(**db_params)
cur = conn.cursor()

# Создание таблиц
create_entities_table_query = """
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE
);
"""
cur.execute(create_entities_table_query)
conn.commit()

create_objects_table_query = """
CREATE TABLE IF NOT EXISTS objects (
    id SERIAL PRIMARY KEY,
    entity_id INT REFERENCES entities(id),
    name VARCHAR(255),
    CONSTRAINT unique_object UNIQUE (entity_id, name)
);
"""
cur.execute(create_objects_table_query)
conn.commit()

create_characteristics_table_query = """
CREATE TABLE IF NOT EXISTS characteristics (
    id SERIAL PRIMARY KEY,
    object_id INT REFERENCES objects(id),
    characteristic VARCHAR(255),
    value text
);
"""
cur.execute(create_characteristics_table_query)
conn.commit()

# Вставка данных в таблицы
for entity, data in entity_data.items():
    # Вставка сущности
    cur.execute("INSERT INTO entities (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id;", (entity,))
    entity_id = cur.fetchone()[0] if cur.rowcount > 0 else cur.execute("SELECT id FROM entities WHERE name = %s;", (entity,)).fetchone()[0]

    for object_name, characteristic, value in data:
        if pd.isna(object_name):
            continue  # Пропускаем строки с пропущенным именем объекта

        # Вставка объекта
        cur.execute("INSERT INTO objects (entity_id, name) VALUES (%s, %s) ON CONFLICT (entity_id, name) DO NOTHING RETURNING id;", (entity_id, object_name))
        object_id = cur.fetchone()[0] if cur.rowcount > 0 else cur.execute("SELECT id FROM objects WHERE entity_id = %s AND name = %s;", (entity_id, object_name)).fetchone()[0]

        # Вставка характеристики
        cur.execute("INSERT INTO characteristics (object_id, characteristic, value) VALUES (%s, %s, %s);", (object_id, characteristic, value))

    conn.commit()

# Закрытие соединения
cur.close()
conn.close()

print("Данные успешно вставлены в базу данных.")