import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import time
import random
import re
import os
from datetime import datetime

# ==============================================================================
# 0. ОТКЛЮЧЕНИЕ СИСТЕМНЫХ ПРОКСИ
# ==============================================================================
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''

# ==============================================================================
# 1. ОСНОВНЫЕ НАСТРОЙКИ | ТОКЕНЫ И НАСТРОЙКА ОПЕЧАТОК
# ==============================================================================
USER_TOKEN = 'vk1.a.oFNBUXjpJ3pMsEZqN9JpjutXmcS9bKuZGvjLAU9fn41sZ74MooKqbIHchrWn_voYIewqrD0jJPqQHaFrW5qdgd-too1-04zft-THOsOd8nGCJDAZoDmMyyPVkFA_IBPde9xjlqYOpMYVNPeU5tFJM3Y1JhuklyIx7289oFgsEJ8-BqQyzdq-9HjvB61c9L5M'
GROUP_TOKEN = 'vk1.a.RTKpaUP2VQ6HqXsPizxaPTZctNSxwpWzT4TI3z6m-svAPQQ4A2zgLzKmN50siDlqyD3g-foWQZDpwTJdk0VllMrYKbIowiYl3xfxtO4de7BDgUJZQ_QWEgGU4rgZCR1L0bJQ8FoSGTRx1M2VWLtMgTDzomQzfxejkZCxPKVhbW4HGTmURMJ4yZsgjuXwpdTjjjPnuC984bvc_asM62hCcw'
GROUP_ID = 216111208
MAX_TYPO_DISTANCE = 2 # Допустимое количество ошибок в слове

# ==============================================================================
# 2. ФУНКЦИИ ЧТЕНИЯ ВНЕШНИХ ФАЙЛОВ
# ==============================================================================
def load_keywords(filepath='keywords.txt'):
    if not os.path.exists(filepath):
        print(f"[ОШИБКА] Файл со словами {filepath} не найден!")
        return [], set()
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    words = [word.strip().lower() for word in re.split(r'[,\n]+', content) if word.strip()]
    return words, set(words)

def load_reply_text(filepath='reply.txt'):
    if not os.path.exists(filepath):
        print(f"[ОШИБКА] Файл с текстом ответа {filepath} не найден!")
        return "Текст автоответа не найден."
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read().strip()

# ==============================================================================
# 3. АЛГОРИТМ ПРОВЕРКИ ТЕКСТА И ПОИСКА ОПЕЧАТОК
# ==============================================================================
def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def check_post_for_triggers(text):
    keywords_list, keywords_set = load_keywords()
    
    if not keywords_list:
        return False, None

    words_in_post = re.findall(r'\b\w+\b', text.lower())
    words_set = set(words_in_post)
    
    exact_matches = words_set & keywords_set
    if exact_matches:
        matched_word = list(exact_matches)[0]
        return True, matched_word

    for word in words_in_post:
        if len(word) < 4:
            continue
            
        for keyword in keywords_list:
            if len(keyword) >= 4 and abs(len(word) - len(keyword)) <= MAX_TYPO_DISTANCE:
                if levenshtein_distance(word, keyword) <= MAX_TYPO_DISTANCE:
                    return True, f"{keyword} (найдено как: '{word}')"
                
    return False, None

# ==============================================================================
# 4. ЛОГИРОВАНИЕ ДЕЙСТВИЙ БОТА
# ==============================================================================
def log_action(message, log_file='bot_log.txt'):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    log_entry = f"{timestamp} {message}"
    
    # Выводим в консоль
    print(log_entry)
    
    # Записываем в файл
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    except Exception as e:
        print(f"[ОШИБКА ЗАПИСИ ЛОГА] {e}")

# ==============================================================================
# 5. ОСНОВНОЙ ЦИКЛ РАБОТЫ БОТА
# ==============================================================================
def main():
    initial_words, _ = load_keywords()
    log_action("====================================")
    log_action("Бот запущен и отслеживает предложку")
    log_action(f"Загружено триггерных слов: {len(initial_words)}")
    log_action("====================================")
    
    was_disconnected = False

    while True:
        try:
            # Инициализация сессий ВК
            vk_group_session = vk_api.VkApi(token=GROUP_TOKEN)
            vk_group_session.http.trust_env = False
            longpoll = VkBotLongPoll(vk_group_session, GROUP_ID)
            
            vk_user_session = vk_api.VkApi(token=USER_TOKEN)
            vk_user_session.http.trust_env = False
            vk_user = vk_user_session.get_api()

            if was_disconnected:
                log_action("[СВЯЗЬ ВОССТАНОВЛЕНА] Соединение с VK успешно переподключено.")
                was_disconnected = False

            # Прослушивание новых событий из группы
            for event in longpoll.listen():
                if event.type == VkBotEventType.WALL_POST_NEW:
                    obj = event.object
                    post = obj.get('post') if isinstance(obj, dict) and 'post' in obj else obj
                    
                    # Проверяем, что пост именно из ПРЕДЛОЖКИ ('suggest')
                    if isinstance(post, dict) and post.get('post_type') == 'suggest':
                        post_text = post.get('text', '')
                        
                        # Шаг А: Проверка текста поста на наличие триггеров
                        found, matched_keyword = check_post_for_triggers(post_text)
                        
                        if found:
                            # Шаг Б: Загрузка текст ответа из reply.txt
                            current_reply_text = load_reply_text()
                            
                            author_id = post.get('signer_id') or post.get('from_id')
                            
                            if author_id and author_id > 0:
                                try:
                                    # Шаг В: Отправка сообщения автору предложки
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
                                
                                # Задержка перед следующим ответом (чтобы ВК не дал бан за спам)
                                delay = round(random.uniform(2.5, 4.5), 2)
                                time.sleep(delay)
                                
        except Exception as e:
            was_disconnected = True
            err_msg = str(e).split('(')[0].strip() or type(e).__name__
            log_action(f"[СБОЙ СЕТИ/VK] Потеряно соединение ({err_msg}). Повтор через 5 сек...")
            time.sleep(5)

#- - - - - - - - - - - - - - -
if __name__ == '__main__':
    main()
