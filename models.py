import psycopg2

DB_CONFIG = {
    'dbname': 'bober',
    'user': 'postgres',
    'password': 'admin',
    'host': 'localhost',
    'port': '5432'
}


def init_database():
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
    init_database()