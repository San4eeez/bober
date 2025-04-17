import pandas as pd

# Список наименований объектов, которые нужно найти
object_names = [
    "Герб Российской Федерации тип 1",
    "Краска для рисования¹ тип 1",
    # Добавьте другие наименования здесь
]

# Чтение файла Excel
file_path = "part.xlsx"
df = pd.read_excel(file_path, header=None)

# Получение заголовков (первые 4 строки)
headers = df.iloc[:4]

# Создание нового DataFrame для хранения результатов
result_df = headers.copy()

# Проходим по каждому наименованию объекта
for name in object_names:
    # Нахождение индексов строк, где наименование объекта совпадает
    start_index = df[df[1] == name].index[0]

    # Находим следующее наименование объекта или конец файла
    if start_index + 1 < len(df):
        next_name_index = df[df[1].notna()].index[df[df[1].notna()].index > start_index].min()
    else:
        next_name_index = len(df)

    # Выборка данных между найденными индексами
    selected_data = df.iloc[start_index:next_name_index]

    # Добавление выбранных данных в результирующий DataFrame
    result_df = pd.concat([result_df, selected_data], ignore_index=True)

# Сохранение результата в новый файл Excel
output_file_path = "filtered_part.xlsx"
result_df.to_excel(output_file_path, index=False, header=False)

print(f"Результат сохранен в {output_file_path}")