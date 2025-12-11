from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List


def create_kb(width: int,
              *args: str,
              **kwargs: str) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру на лету с заданными параметрами.

    Эта функция позволяет динамически создавать клавиатуры используя:
    - Кнопки с callback-данными (передаются через kwargs)
    - Кнопки без callback-данных (передаются через args, в текущей реализации не используются)

    Параметры:
        width (int): Количество кнопок в одном ряду
        *args (str): Параметр для будущего расширения (в текущей реализации не используется)
        **kwargs (str): Пара "callback_data: text" для кнопок, где:
            key - данные для callback
            value - отображаемый текст

    Возвращает:
        InlineKeyboardMarkup: Объект инлайн-клавиатуры

    Пример использования:
        create_kb(2, button1="Текст1", button2="Текст2")
        создаст клавиатуру с двумя кнопками в одном ряду
    """
    # Инициализируем билдер для создания инлайн-клавиатуры
    kb_builder = InlineKeyboardBuilder()
    # Список для хранения созданных кнопок
    buttons: List[InlineKeyboardButton] = []

    # В текущей реализации args не используется, оставлено для будущего расширения
    if args:
        # Здесь может быть добавлена обработка позиционных аргументов
        pass

    # Обрабатываем именованные аргументы (callback_data: text)
    if kwargs:
        for button_data, button_text in kwargs.items():
            # Создаем кнопку с текстом и callback-данными
            buttons.append(InlineKeyboardButton(
                text=button_text,
                callback_data=button_data
            ))

    # Распаковываем список кнопок в билдер, формируя ряды по width кнопок
    kb_builder.row(*buttons, width=width)

    # Возвращаем собранную клавиатуру
    return kb_builder.as_markup()


def kb_button(button_text, button_url):
    button = InlineKeyboardButton(text=button_text, url=button_url)
    kb = InlineKeyboardMarkup(inline_keyboard=[[button]])
    return kb
