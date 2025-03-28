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

# Выделение уникальных сущностей
df['entity'] = df[df.columns[1]].str.replace(r" тип \d+", "", regex=True)
unique_entities = df.drop_duplicates(subset='entity')['entity'].dropna().tolist()

# Инициализация переменных
current_entity = None
entity_data = {}

# Проход по строкам и группировка данных
for index, row in df.iterrows():
    if index < 4:
        continue  # Пропускаем первые 4 строки

    entity = row['entity']
    characteristic = row[5]  # Характеристика
    value_9 = row[8]  # Значение характеристики в столбце I
    value_10 = row[9]  # Значение характеристики в столбце J

    if pd.notna(entity):
        current_entity = entity

    if pd.notna(characteristic) and current_entity is not None:
        value = value_9 if pd.notna(value_9) else (value_10 if pd.notna(value_10) else None)
        if current_entity not in entity_data:
            entity_data[current_entity] = []
        entity_data[current_entity].append((characteristic, value))

# Подключение к базе данных
conn = psycopg2.connect(**db_params)
cur = conn.cursor()

# Создание таблиц и вставка данных для каждой сущности
for entity in unique_entities:
    # Заменяем недопустимые символы на подчеркивания и добавляем префикс, если имя начинается с цифры
    table_name = re.sub(r'\W+', '_', entity.lower()).strip('_')
    if table_name[0].isdigit():
        table_name = f"entity_{table_name}"

    # Создание таблицы (если она еще не существует)
    create_table_query = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id SERIAL PRIMARY KEY,
        characteristic text,
        value text
    );
    """
    cur.execute(create_table_query)
    conn.commit()

    # Вставка данных в таблицу
    if entity in entity_data:
        insert_query = f"INSERT INTO {table_name} (characteristic, value) VALUES (%s, %s);"
        cur.executemany(insert_query, entity_data[entity])
        conn.commit()

# Закрытие соединения
cur.close()
conn.close()

print("Данные успешно вставлены в базу данных.")