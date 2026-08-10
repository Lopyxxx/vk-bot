import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import random
import re
import os
import threading
import logging
from datetime import datetime
from flask import Flask, cli

# ==============================================================================
# 0. ОТКЛЮЧЕНИЕ СИСТЕМНЫХ ПРОКСИ
# ==============================================================================
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''

# ==============================================================================
# 1. ОСНОВНЫЕ НАСТРОЙКИ | ТОКЕНЫ И КЭШ
# ==============================================================================
USER_TOKEN = os.environ.get('VK_USER_TOKEN')
GROUP_TOKEN = os.environ.get('VK_GROUP_TOKEN')
GROUP_ID = int(os.environ.get('VK_GROUP_ID', 216111208))

# Кэш слов и корней в ОЗУ (без чтения диска)
CACHED_KEYWORDS = []
CACHED_STEMS = set()

# ==============================================================================
# 2. ПРОСТАЯ ФУНКЦИЯ ПОИСКА КОРНЯ (СТЕММИНГ ДЛЯ РУССКОГО ЯЗЫКА)
# ==============================================================================
def get_stem(word):
    # Отрезание окончаний для поиска корня
    word = word.lower()
    if len(word) <= 3:
        return word
    rx = r'(иями|ями|ами|его|ого|ему|ому|их|ых|ею|ою|ем|ом|их|ых|ую|юю|ая|яя|ое|ее|ые|ие|ых|их|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|а|е|и|о|у|ы|э|ю|я|ь|й)$'
    stem = re.sub(rx, '', word)
    return stem if len(stem) >= 3 else word

# ==============================================================================
# 3. ФУНКЦИИ ЧТЕНИЯ ВНЕШНИХ ФАЙЛОВ И КЭШИРОВАНИЯ
# ==============================================================================
def load_keywords(filepath='keywords.txt'):
    # Загрузка списка триггерных слов из файла keywords.txt
    global CACHED_KEYWORDS, CACHED_STEMS
    if not os.path.exists(filepath):
        print(f"[ОШИБКА] Файл со словами {filepath} не найден!")
        return [], set()
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    words = [word.strip().lower() for word in re.split(r'[,\n]+', content) if word.strip()]
    # Автоматическое извлечение корней из всех загруженных ключевых слов
    stems = {get_stem(w) for w in words}

    # Сохранение слов и их корней в оперативно доступный кэш    
    CACHED_KEYWORDS = words
    CACHED_STEMS = stems
    return words, stems

def load_reply_text(filepath='reply.txt'):
    # Загрузка текста автоответа из файла reply.txt
    if not os.path.exists(filepath):
        print(f"[ОШИБКА] Файл с текстом ответа {filepath} не найден!")
        return "Текст автоответа не найден."
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read().strip()

# ==============================================================================
# 4. АЛГОРИТМ ПРОВЕРКИ ТЕКСТА (БЫСТРЫЙ И ТОЧНЫЙ ПОИСК ПО КОРНЯМ)
# ==============================================================================
def check_post_for_triggers(text):
    # Первичная инициализация кэша при первом обращении к функции
    if not CACHED_STEMS:
        load_keywords()
        
    if not CACHED_STEMS:
        return False, None

    # Извлечение отдельных слов из предложенного поста
    words_in_post = re.findall(r'\b\w+\b', text.lower())
    
    for word in words_in_post:
        # Выделение корня у текущего слова из текста поста
        word_stem = get_stem(word)

        # Точная проверка: совпадает ли корень слова с корнями триггерных слов
        if word_stem in CACHED_STEMS or word in CACHED_KEYWORDS:
            return True, word

    return False, None

# ==============================================================================
# 5. ЛОГИРОВАНИЕ ДЕЙСТВИЙ БОТА
# ==============================================================================
def log_action(message):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} {message}", flush=True)

# ==============================================================================
# 6. ОСНОВНОЙ ЦИКЛ РАБОТЫ БОТА
# ==============================================================================
def main():
    # Запуск веб-сервера в отдельном фоновом потоке
    threading.Thread(target=run_web_server, daemon=True).start()

    # Загрузка и первичная обработка триггеров в ОЗУ перед запуском прослушивания
    initial_words, _ = load_keywords()
    log_action("==================================/")
    log_action("Бот запущен и отслеживает записи /")
    log_action(f"Загружено слов: {len(initial_words)}              /")
    log_action("===============================/")
    
    was_disconnected = False
    disconnect_start_time = None
    retry_count = 0

    while True:
        try:
            # Инициализация сессии сообщества для отслеживания предложки через LongPoll
            vk_group_session = vk_api.VkApi(token=GROUP_TOKEN)
            vk_group_session.http.trust_env = False
            longpoll = VkBotLongPoll(vk_group_session, GROUP_ID)

            # Инициализация сессии пользователя для отправки личных сообщений
            vk_user_session = vk_api.VkApi(token=USER_TOKEN)
            vk_user_session.http.trust_env = False
            vk_user = vk_user_session.get_api()

            # Восстановление после обрыва связи
            if was_disconnected:
                duration = int((datetime.now() - disconnect_start_time).total_seconds())
                minutes, seconds = divmod(duration, 60)
                time_str = f"{minutes} мин {seconds} сек" if minutes > 0 else f"{seconds} сек"

                print() 
                log_action(f"[СВЯЗЬ ВОССТАНОВЛЕНА] Время простоя: {time_str} (Попыток: {retry_count})")
                
                was_disconnected = False
                disconnect_start_time = None
                retry_count = 0

            # Прослушивание событий из VK
            for event in longpoll.listen():
                if event.type == VkBotEventType.WALL_POST_NEW:
                    obj = event.object
                    post = obj.get('post') if isinstance(obj, dict) and 'post' in obj else obj

                    # Фильтрация предложенных новостей
                    if isinstance(post, dict) and post.get('post_type') == 'suggest':
                        post_text = post.get('text', '')
                        
                        found, matched_keyword = check_post_for_triggers(post_text)
                        
                        if found:
                            current_reply_text = load_reply_text()
                            author_id = post.get('signer_id') or post.get('from_id')
                            
                            if author_id and author_id > 0:
                                try:
                                    # Отправка ответа автору поста
                                    vk_user.messages.send(
                                        user_id=author_id,
                                        message=current_reply_text,
                                        random_id=0
                                    )
                                    log_action(f"[ОК] Триггер '{matched_keyword}'. Отправлено id{author_id}")
                                except vk_api.exceptions.ApiError as e:
                                    log_action(f"[ОШИБКА VK] Не удалось отправить id{author_id}: {e}")
                                except Exception as e:
                                    log_action(f"[ОШИБКА] Сбой при отправке id{author_id}: {e}")

                                # Задержка для защиты от блокировок VK за спам
                                delay = round(random.uniform(2.5, 4.5), 2)
                                time.sleep(delay)
                                
        except Exception as e:
            if not was_disconnected:
                was_disconnected = True
                disconnect_start_time = datetime.now()
                err_msg = str(e).split('(')[0].strip() or type(e).__name__
                log_action(f"[СБОЙ СЕТИ/VK] Потеряно соединение ({err_msg}). Ожидание сети...")

            # Динамическое обновление строки в консоли без засорения файла
            retry_count += 1
            log_action(f"[ПОВТОР #{retry_count}] Попытка переподключения через 5 сек...")
            time.sleep(5)

# ==============================================================================
# 7. ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖКИ АКТИВНОСТИ
# ==============================================================================
app = Flask(__name__)

# Отключение служебного вывода Flask для чистоты консоли
cli.show_server_banner = lambda *_: None
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
if __name__ == '__main__':
    main()
