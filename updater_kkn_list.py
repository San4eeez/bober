import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime

# URL страницы, которую вы хотите получить
url = 'https://www.gz-spb.ru/content/2831'

try:
    print("Запуск обновления сборника ККН")
    # Отправляем GET-запрос с отключенной проверкой SSL
    response = requests.get(url, verify=False)

    soup = BeautifulSoup(response.text, 'html.parser')

    # Ищем ссылку на файл xlsx
    doc_link = soup.find('a', type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if doc_link is None:
        raise ValueError("Ссылка на файл xlsx не найдена")

    doc_link = doc_link.get('href')
    doc_link = f'https://www.gz-spb.ru{doc_link}'

    # Получаем текущую дату и время
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open('update_log.txt', 'a') as file:
        file.write(f"{current_time} - {doc_link}\n")

    # Загружаем файл с отображением прогресса
    response = requests.get(doc_link, stream=True, verify=False)
    total_size_in_bytes = int(response.headers.get('content-length', 0))
    block_size = 1024  # 1 Kibibyte

    with open('doc.xlsx', 'wb') as file, tqdm(
        total=total_size_in_bytes,
        unit='iB',
        unit_scale=True,
        desc='Загрузка файла'
    ) as progress_bar:
        for data in response.iter_content(block_size):
            file.write(data)
            progress_bar.update(len(data))

    print("Файл успешно загружен")

except requests.exceptions.RequestException as e:
    # В случае ошибки выводим сообщение об ошибке
    print(f'Ошибка при запросе страницы: {e}')
except ValueError as e:
    print(f'Ошибка: {e}')