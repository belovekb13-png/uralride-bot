"""
Бот-«приемная» Урал Райд + Аквабанк (красная икра).

Что делает:
  1. Спрашивает, что интересует: мангалы, сноуборды, сноусерфы, красная икра.
  2. Задает короткие вопросы по выбранному направлению.
  3. Собирает имя и контакт.
  4. Присылает вам готовую заявку в Telegram и записывает ее в leads.csv.
  5. На любом шаге есть кнопка «Написать лично»: бот зовет вас и пересылает
     сообщения клиента вам.

Все тексты, цены и вопросы лежат в блоке НАСТРОЙКИ ниже. Правьте их там.
"""

import asyncio
import csv
import logging
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # .env не обязателен, можно задать переменные окружения вручную
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/uralride")
LEADS_FILE = Path(os.getenv("LEADS_FILE", "leads.csv"))

# ======================================================================
# НАСТРОЙКИ: тексты, цены, вопросы
# ======================================================================

WELCOME = (
    "Привет! Это <b>Урал Райд</b> и магазин красной икры <b>Аквабанк</b>.\n\n"
    "Что вас интересует? Выберите ниже, я задам пару вопросов и передам заявку "
    "владельцу. Он свяжется с вами лично."
)

# Цена и дата предзаказа икры: меняйте здесь, когда откроете новый период
# Цены (в рублях). Меняйте здесь.
FIRE_PRICES = {"Таганай 32 см": 5500, "Конжак 40 см": 7500}  # сталь Ст3
FIRE_STAINLESS_EXTRA = 2000  # доплата за нержавеющую сталь
BOARD_PRICE = 65000  # сноуборд «Свобода»
SURF_PRICE = 55000  # сноусерф

# Цена икры за 1 кг в рублях по видам. Пока цены не утверждены, оставьте None:
# бот не называет цену и просто собирает заявки. Когда утвердите, впишите числа, например 15000.
CAVIAR_PRICES = {"Кета": None, "Горбуша": None}
CAVIAR_PRICE_UNTIL = "конца ноября"  # до какой даты зафиксирована цена (когда цены заданы)


def _caviar_price_line() -> str:
    known = {k: v for k, v in CAVIAR_PRICES.items() if v}
    if not known:
        return "Цены на текущий период сейчас формируем. Оставьте заявку, и Дмитрий пришлет цену, как только она будет утверждена."
    parts = ", ".join(f"{k}: {v:,}".replace(",", " ") + " ₽/кг" for k, v in known.items())
    return f"Цена зафиксирована до {CAVIAR_PRICE_UNTIL}: {parts}."

# Вес фасовок в кг. «Больше 1 кг» бот не считает, цену вы обсуждаете лично.
CAVIAR_PACK_KG = {"250 г": 0.25, "500 г": 0.5, "1 кг": 1.0}

# История бренда. Здесь только то, что точно известно. Дополните своими фактами.
STORY = (
    "📖 <b>История Урал Райд</b>\n\n"
    "Меня зовут Дмитрий Белов, я основатель Урал Райд и Аквабанк. Профессионально я занимался "
    "волейболом, а в 2014 году встал на сноуборд на Белой горе в Свердловской области и с тех пор "
    "не расстаюсь с ним ни одного сезона.\n\n"
    "В 2016 году я впервые приехал в Шерегеш, и бесконечный лесной фрирайд решил всё: мне нужна "
    "своя доска. Потом захотелось сделать доску под свои параметры и наш уральский частый лес. "
    "В 2024 году я познакомился в Екатеринбурге с мастером, который с 2016 года делал спортивные "
    "доски, и стал его партнером. За сезон мы сделали больше 20 досок для спортсменов и обычных людей.\n\n"
    "В 2025 году я договорился с основателем японского бренда TJ Brand, Тоши, и привез первую партию "
    "досок из Японии. Это оказалось настоящее искусство и почти все доски для фрирайда. "
    "Целый сезон я откатал на доске 159 при росте 202 см и весе 100 кг и влюбился в эти шейпы.\n\n"
    "Сегодня я эксклюзивный дистрибьютор TJ Brand и сам произвожу доски для фрирайда по обновленной "
    "технологии. Вы можете заказать доску из Японии или нашего производства, и в обоих случаях "
    "это будет правильный выбор.\n\n"
    "Рядом живут костровые системы Урал Райд (более 20 комплектов уже по всей России) и Аквабанк: "
    "красная икра и деликатесы, за качество которых мы отвечаем уже больше 6 лет."
)

# Подробные описания (кнопка «Подробнее о товаре»)
DESCRIPTIONS = {
    "fire": (
        "🔥 <b>Костровые системы Урал Райд</b>\n\n"
        "<b>Модели:</b> Таганай 32 см и Конжак 40 см.\n"
        "<b>Материал:</b> сталь Ст3 или нержавеющая сталь, толщина стали 3 мм.\n"
        "<b>Вес:</b> Таганай 5,5 кг, Конжак 7,5 кг.\n"
        "<b>На сколько человек:</b> Таганай на 2–3 человека, Конжак на 3–6 человек.\n"
        "<b>Что можно готовить:</b> на обеих моделях готовят в казане, садже и афганском казане "
        "на специальной мульти-решетке.\n"
        "<b>Цена:</b> Таганай 5 500 ₽, Конжак 7 500 ₽ (Ст3). Нержавеющая сталь: +2 000 ₽.\n\n"
        "<b>В комплекте (для любой стали):</b>\n"
        "• мангал из 3 стенок с двумя уровнями жара;\n"
        "• мульти-решетка 2 в 1, она же подставка под казан, садж и афганский казан;\n"
        "• 2 кочерги;\n"
        "• чехол из карпета ручной работы;\n"
        "• транспортировочная упаковка из гофрокартона.\n\n"
        "<b>Срок изготовления:</b> 1–3 дня. Наличие пополняем каждую неделю.\n"
        "<b>Доставка:</b> по всей России за счет покупателя (в отдельных случаях часть доставки компенсируем)."
    ),
    "board": (
        "🏂 <b>Сноуборды для фрирайда</b>\n\n"
        "Мы эксклюзивный дистрибьютор японского бренда <b>TJ Brand</b> и сами производим доски для фрирайда. "
        "Цену и наличие досок TJ Brand называем лично под ваш рост и вес.\n\n"
        "<b>Серия «Свобода» (наше производство)</b>\n"
        "<b>Цена:</b> 65 000 ₽. Цена складывается из сложного технологического процесса, "
        "натуральных материалов и эксклюзивной ручной сборки по технологиям топовых заводских производителей.\n\n"
        "<b>Характеристики:</b>\n"
        "• форма: направленная (directional), тип катания: фрирайд;\n"
        "• сердечник: наборный деревянный из осины (aspen);\n"
        "• скользящая поверхность: экструдированный PTEX;\n"
        "• стальные канты.\n\n"
        "<b>Размерный ряд «Свобода»</b> (линейка рассчитана на рост от 160 до 200 см):\n"
        "• <b>152</b> (рост 160–170 см): длина 1500 мм, нос/талия/хвост 305/255/280 мм, радиус 7,1 м, рабочий кант 1035 мм, "
        "вес около 2,09 кг, гибкость средняя;\n"
        "• <b>156</b> (рост 170–180 см): длина 1560 мм, 310/258/290 мм, радиус 6,9 м, рабочий кант 1080 мм, "
        "вес около 2,28 кг, гибкость очень жесткая;\n"
        "• <b>162</b> (рост 180–200 см): длина 1620 мм, 320/262/295 мм, радиус 7,0 м, рабочий кант 1130 мм, "
        "вес около 2,52 кг, гибкость очень жесткая.\n"
        "Вес райдера учитываем индивидуально: жесткость настраиваем под каждого. Гибкость и вес доски расчетные (модельная оценка). Прогиб 4–5 мм, подъем носа и хвоста 70–75 и 26–30 мм.\n\n"
        "<b>Сборка (сверху вниз):</b> шпон 0,6 мм, карбоновый UD-стрингер 0° на всю длину, трехосное стекло 700 г/м², "
        "осиновый сердечник переменной толщины, трехосное стекло 700 г/м², демпфирующая резина VDS 0,2 мм, "
        "PTEX-основа со стальными кантами.\n\n"
        "<b>Что можно выбрать:</b>\n"
        "• ростовку под ваш рост;\n"
        "• жесткость под вес райдера (дополнительные стрингеры и стекловолокно), базовая настройка бесплатно;\n"
        "• шпон: дуб, ясень или орех бесплатно; свой вариант и оттенок обсуждается с производителем.\n\n"
        "<b>Срок изготовления:</b> 2–3 недели. Сейчас только предзаказ."
    ),
    "surf": (
        "🏄 <b>Сноусерфы Урал Райд</b>\n\n"
        "<b>Цена:</b> 55 000 ₽. Все из натуральных материалов, ручная сборка по собственной технологии.\n\n"
        "<b>Характеристики:</b> длина 1480 мм, одна жесткость и одна ростовка.\n"
        "<b>Конструкция:</b> желобообразное дно с центральным каналом по ширине стопы, два вклеенных канта, "
        "которые вгрызаются в снег при наклоне доски, и два небольших плавника под смолой и стеклом. "
        "Носик в форме ложки.\n"
        "<b>Материалы:</b> фанера павловнии с натуральным шпоном, трехосная стеклоткань, эпоксидная смола. "
        "Вакуумная сборка вручную. Скользящая поверхность стеклянная, без спеченного P-Tex.\n"
        "<b>Что можно выбрать:</b> цвет нижней и верхней поверхности, шпон (дуб, ясень, орех и другие).\n\n"
        "<b>Срок изготовления:</b> 2–3 недели. Сейчас только предзаказ."
    ),
    "caviar": (
        "🐟 <b>Красная икра, Аквабанк</b>\n\n"
        "<b>Виды:</b> кета и горбуша. Поставки из Сахалина напрямую с рыбного завода.\n"
        f"<b>Цена:</b> {_caviar_price_line()}\n"
        "<b>Фасовки:</b> 250 г, 500 г, 1 кг. Больше 1 кг: цену обсуждаем лично.\n"
        "<b>Упаковка:</b> герметичная, вакуумная. <b>Срок хранения:</b> до месяца в холодильнике.\n"
        "<b>Где:</b> самовывоз и доставка только по Екатеринбургу.\n"
        "<b>Как проходит:</b> набираем заказы примерно две недели на куб икры (12,5 кг), открываем свежий куб "
        "и в тот же или на следующий день развозим заказчикам. Есть самовывоз.\n\n"
        "<b>Как появился Аквабанк.</b> Когда я работал в IT, мой друг-волейболист временно переехал во Владивосток "
        "и присылал мне фото и видео с рыночных прилавков с очень интересными ценами. Мы созванивались очень рано "
        "или очень поздно из-за разницы во времени, а он периодически отправлял мне настоящие деликатесы: "
        "кукумарию, морских ежей, красную икру, крабов, гребешки. Я влюбился в эти продукты и показал знакомым, "
        "что цены могут быть доступнее магазинных, а товар свежее. Был период, когда у нас был свой магазин, "
        "сейчас мы полностью перешли в онлайн.\n\n"
        "<b>Аквабанк за качество отвечает.</b> Это наш девиз с Игорем: мы дружим больше 20 лет, "
        "и все, кто нас знает, это подтвердят."
    ),
    "delicacy": (
        "🦀 <b>Дальневосточные деликатесы под заказ</b>\n\n"
        "Сейчас деликатесы временно не продаются в обычном режиме, но мы можем привезти ограниченную партию "
        "в Екатеринбург, например к Новому году. Средний срок поставки около 4 недель. "
        "Напишите, что вы хотите: кукумарию, морских ежей, крабов, гребешки или что-то другое. "
        "Так мы поймем, сколько и чего заказывать."
    ),
}

# Вопросы, которые бот задает в конце для любого направления
CONTACT_STEPS = [
    {"key": "name", "label": "Имя", "q": "Как к вам обращаться?"},
    {
        "key": "contact_method",
        "label": "Как удобнее связаться",
        "q": "Где вам удобнее общаться?",
        "options": ["Telegram", "WhatsApp", "MAX", "Звонок"],
    },
    {
        "key": "contact",
        "label": "Контакт",
        "q": "Напишите номер телефона или ник, по которому с вами связаться.",
    },
]

# Направления: у каждого есть вступление и список вопросов.
# Вопрос с "options" показывается кнопками, без "options" ждет текст.
DIRECTIONS = {
    "fire": {
        "title": "🔥 Мангалы, костровые чаши",
        "intro": (
            "🔥 <b>Костровые системы Урал Райд</b>\n"
            "Модели: <b>Таганай 32 см</b> (5 500 ₽) и <b>Конжак 40 см</b> (7 500 ₽), сталь Ст3. "
            "Нержавеющая сталь: +2 000 ₽.\n"
            "В комплекте: мангал из 3 стенок с двумя уровнями жара, мульти-решетка 2 в 1 "
            "(она же подставка под казан, садж и афганский казан), 2 кочерги, "
            "чехол из карпета ручной работы и транспортировочная упаковка из гофрокартона.\n"
            "Срок изготовления 1–3 дня, наличие пополняем каждую неделю. "
            "Отправляем по всей России, доставка за счет покупателя."
        ),
        "steps": [
            {
                "key": "model",
                "label": "Модель",
                "q": "Какая модель вам интересна?",
                "options": ["Таганай 32 см", "Конжак 40 см", "Пока не знаю"],
            },
            {
                "key": "material",
                "label": "Материал",
                "q": "Из какой стали?",
                "options": ["Ст3", "Нержавеющая сталь", "Подскажите"],
            },
            {"key": "city", "label": "Город", "q": "В какой город нужна доставка?"},
        ],
    },
    "board": {
        "title": "🏂 Сноуборды «Свобода»",
        "intro": (
            "🏂 <b>Сноуборды для фрирайда</b>: наши «Свобода» и японские TJ Brand (мы эксклюзивный дистрибьютор).\n\n"
            "<b>Серия «Свобода» (наше производство)</b>\n"
            "Ростовку и жесткость подбираем под вес райдера "
            "(дополнительные стрингеры и стекловолокно). "
            "Шпон: дуб, ясень, орех или ваш вариант и оттенок.\n"
            "Цена: <b>65 000 ₽</b>. Выбор шпона из предложенных и базовая настройка жесткости бесплатно.\n"
            "Срок изготовления 2–3 недели. Сейчас идет <b>предзаказ</b>."
        ),
        "steps": [
            {
                "key": "line",
                "label": "Линейка",
                "q": "Какую доску рассматриваете?",
                "options": ["Урал Райд «Свобода»", "TJ Brand (Япония)", "Подскажите"],
            },
            {"key": "height", "label": "Рост", "q": "Ваш рост (в см)?"},
            {"key": "weight", "label": "Вес", "q": "Ваш вес (в кг)? Он нужен, чтобы подобрать жесткость."},
            {
                "key": "level",
                "label": "Опыт",
                "q": "Какой у вас уровень катания?",
                "options": ["Начинающий", "Средний", "Опытный"],
            },
            {
                "key": "size",
                "label": "Размер",
                "q": "Какой размер вам интересен? Если не знаете, выберите «Подскажите», подберем по росту и весу.",
                "options": ["152 (1500 мм)", "156 (1560 мм)", "162 (1620 мм)", "Подскажите"],
                "only_own": True,
            },
            {
                "key": "veneer",
                "label": "Шпон",
                "q": "Какой шпон хотите?",
                "options": ["Дуб", "Ясень", "Орех", "Свой вариант"],
                "only_own": True,  # для досок TJ Brand не спрашиваем
            },
            {
                "key": "color",
                "label": "Оттенок и пожелания",
                "q": "Напишите оттенок шпона и другие пожелания. Если пока не решили, напишите «подскажите».",
                "only_own": True,
            },
        ],
    },
    "surf": {
        "title": "🏄 Сноусерфы",
        "intro": (
            "🏄 <b>Сноусерфы Урал Райд</b>\n"
            "Жесткость и ростовка одна. Вы выбираете шпон (дуб, ясень, орех и другие) "
            "и цвет нижней и верхней поверхности.\n"
            "Цена: <b>55 000 ₽</b>. Все из натуральных материалов, ручная сборка по собственной технологии.\n"
            "Срок изготовления 2–3 недели. Сейчас идет <b>предзаказ</b>."
        ),
        "steps": [
            {
                "key": "veneer",
                "label": "Шпон",
                "q": "Какой шпон хотите?",
                "options": ["Дуб", "Ясень", "Орех", "Другой"],
            },
            {
                "key": "colors",
                "label": "Цвета",
                "q": "Какой цвет верхней и нижней поверхности? Если не решили, напишите «подскажите».",
            },
            {"key": "weight", "label": "Вес райдера", "q": "Ваш вес (в кг)?"},
        ],
    },
    "caviar": {
        "title": "🐟 Красная икра (предзаказ)",
        "intro": (
            "🐟 <b>Красная икра, Аквабанк</b>\n"
            "Кета и горбуша, поставки из Сахалина напрямую с рыбного завода.\n"
            f"{_caviar_price_line()}\n"
            "Фасовки: 250 г, 500 г, 1 кг. Больше 1 кг обсуждаем лично. "
            "Упаковка герметичная, вакуумная, хранится до месяца в холодильнике.\n"
            "Набираем заказы примерно две недели на куб икры (12,5 кг), открываем "
            "свежий куб и в тот же или на следующий день развозим. "
            "Самовывоз и доставка только по Екатеринбургу."
        ),
        "steps": [
            {
                "key": "kind",
                "label": "Вид икры",
                "q": "Какая икра вас интересует?",
                "options": ["Кета", "Горбуша", "Обе / подскажите"],
            },
            {
                "key": "pack",
                "label": "Фасовка",
                "q": "Какая фасовка вам нужна?",
                "options": ["250 г", "500 г", "1 кг", "Больше 1 кг"],
            },
            {"key": "qty", "label": "Количество", "q": "Сколько банок выбранной фасовки нужно? Напишите число."},
            {
                "key": "delivery",
                "label": "Получение",
                "q": "Как будете получать?",
                "options": ["Самовывоз (Екатеринбург)", "Доставка по Екатеринбургу"],
            },
        ],
    },
    "delicacy": {
        "title": "🦀 Деликатесы под заказ",
        "intro": (
            "🦀 <b>Дальневосточные деликатесы под заказ</b>\n"
            "Сейчас деликатесы временно не продаются в обычном режиме, но мы можем привезти ограниченную партию "
            "в Екатеринбург, например к Новому году. Средний срок поставки около 4 недель. "
            "Ответьте на пару вопросов, чтобы мы поняли, что заказывать."
        ),
        "steps": [
            {
                "key": "item",
                "label": "Что интересует",
                "q": "Какой деликатес вы хотите?",
                "options": ["Кукумария", "Морские ежи", "Крабы", "Гребешки", "Другое"],
            },
            {
                "key": "details",
                "label": "Количество и пожелания",
                "q": "Сколько примерно нужно и к какому сроку? Например: 2 кг к Новому году.",
            },
        ],
    },
}

# ======================================================================
# Код бота. Обычно ниже ничего менять не нужно.
# ======================================================================

HUMAN_MODE: set[int] = set()  # клиенты, которым вы ответите лично (до перезапуска бота)


class Flow(StatesGroup):
    answering = State()


def rub(value: float) -> str:
    return f"{round(value):,}".replace(",", " ") + " ₽"


def calc_caviar(pack: str, qty: int, price_per_kg: int | None):
    """Возвращает (сумма в рублях, всего кг) или None, если считать нельзя."""
    kg_each = CAVIAR_PACK_KG.get(pack)
    if kg_each is None or qty <= 0 or not price_per_kg:
        return None
    kg = kg_each * qty
    return kg * price_per_kg, kg


def suggest_size(height_text: str) -> str:
    """Подсказка размера доски «Свобода» по росту. Пустая строка, если рост не распознан."""
    match = re.search(r"\d+[.,]?\d*", height_text or "")
    if not match:
        return ""
    h = float(match.group().replace(",", "."))
    if 1.4 <= h <= 2.5:  # рост указан в метрах
        h *= 100
    if h < 160 or h > 200:
        return "рост вне диапазона 160–200 см, подберем лично"
    if h < 170:
        return "152"
    if h == 170:
        return "152 или 156 (рост на границе, решит вес)"
    if h < 180:
        return "156"
    if h == 180:
        return "156 или 162 (рост на границе, решит вес)"
    return "162"


def price_summary(direction: str, answers: dict):
    """Возвращает (сообщение клиенту, строка суммы для заявки)."""
    if direction == "fire":
        base = FIRE_PRICES.get(answers.get("model"))
        steel = answers.get("material", "")
        if base is None:
            return (
                f"Цены: Таганай 32 см — {rub(FIRE_PRICES['Таганай 32 см'])}, "
                f"Конжак 40 см — {rub(FIRE_PRICES['Конжак 40 см'])} (сталь Ст3), "
                f"нержавеющая сталь +{rub(FIRE_STAINLESS_EXTRA)}. Модель подберем вместе.",
                "модель не выбрана",
            )
        if steel == "Нержавеющая сталь":
            total = base + FIRE_STAINLESS_EXTRA
            text = f"Предварительная стоимость: <b>{rub(total)}</b> (нержавеющая сталь)."
            return text + " Комплектация и доставка: см. описание выше, доставка за счет покупателя.", rub(total)
        if steel == "Ст3":
            text = f"Предварительная стоимость: <b>{rub(base)}</b> (сталь Ст3)."
            return text + " Комплектация и доставка: см. описание выше, доставка за счет покупателя.", rub(base)
        return (
            f"Стоимость: <b>{rub(base)}</b> в стали Ст3 и "
            f"<b>{rub(base + FIRE_STAINLESS_EXTRA)}</b> в нержавеющей. Подскажем, что лучше для ваших задач.",
            f"{rub(base)} (Ст3) или {rub(base + FIRE_STAINLESS_EXTRA)} (нержавейка), сталь не выбрана",
        )
    if direction == "board" and "TJ" in answers.get("line", ""):
        return (
            "Цену и наличие досок TJ Brand лично уточнит Дмитрий и подберет варианты под ваш рост и вес.",
            "TJ Brand: цена и наличие уточняются",
        )
    price = BOARD_PRICE if direction == "board" else SURF_PRICE
    custom = answers.get("veneer") in ("Свой вариант", "Другой")
    text = f"Предварительная стоимость: <b>{rub(price)}</b>. Выбор шпона из предложенных бесплатно."
    total = rub(price)
    if direction == "board":
        text += " Базовая настройка жесткости тоже бесплатно."
    if direction == "board" and answers.get("size") == "Подскажите":
        hint = suggest_size(answers.get("height", ""))
        if hint:
            text += f" По росту вам подойдет размер: <b>{hint}</b>. Дмитрий уточнит с учетом веса."
            total += f" (размер по росту: {hint})"
    if direction == "board" and answers.get("line") == "Подскажите":
        text += " Также можем предложить доски TJ Brand из Японии, это обсудим лично."
        total += " (или TJ Brand, уточняется)"
    if custom:
        text += " Свой вариант шпона обсудит с вами мастер."
        total += " + свой шпон обсуждается"
    return text, total


def steps_for(direction: str) -> list[dict]:
    return DIRECTIONS[direction]["steps"] + CONTACT_STEPS


def main_menu():
    kb = InlineKeyboardBuilder()
    for key, d in DIRECTIONS.items():
        kb.button(text=d["title"], callback_data=f"dir:{key}")
    kb.button(text="📖 Наша история", callback_data="story")
    kb.button(text="💬 Написать лично", callback_data="human")
    kb.button(text="📣 Наш канал", url=CHANNEL_URL)
    kb.adjust(1)
    return kb.as_markup()


def question_kb(step: dict):
    kb = InlineKeyboardBuilder()
    options = step.get("options", [])
    for i, opt in enumerate(options):
        kb.button(text=opt, callback_data=f"opt:{i}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text="💬 Написать лично", callback_data="human"),
        InlineKeyboardButton(text="↩️ В начало", callback_data="menu"),
    )
    return kb.as_markup()


def user_label(user) -> str:
    name = escape(user.full_name or "без имени")
    link = f'<a href="tg://user?id={user.id}">{name}</a>'
    if user.username:
        link += f" (@{escape(user.username)})"
    return link


async def notify_admin(bot: Bot, text: str):
    if not ADMIN_ID:
        logging.warning("ADMIN_ID не задан, уведомление не отправлено")
        return
    try:
        await bot.send_message(ADMIN_ID, text, disable_web_page_preview=True)
    except Exception:
        logging.exception("Не удалось отправить уведомление админу")


async def send_question(message: Message, direction: str, idx: int, answers: dict | None = None):
    step = steps_for(direction)[idx]
    text = step["q"]
    if direction == "caviar" and step["key"] == "qty" and (answers or {}).get("pack") == "Больше 1 кг":
        text = "Сколько килограммов вам нужно? Цену для больших объемов обсудим лично."
    await message.answer(text, reply_markup=question_kb(step))


async def finish(message: Message, user, state: FSMContext, bot: Bot):
    data = await state.get_data()
    direction = data["direction"]
    answers: dict = data["answers"]
    source = data.get("source", "")
    steps = steps_for(direction)

    # 1. запись в таблицу leads.csv (открывается в Excel и Google Таблицах)
    new_file = not LEADS_FILE.exists()
    with LEADS_FILE.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["Дата", "Направление", "Источник", "TG id", "TG ник", "Ответы"])
        w.writerow(
            [
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                DIRECTIONS[direction]["title"],
                source,
                user.id,
                user.username or "",
                " | ".join(f"{s['label']}: {answers.get(s['key'], '-')}" for s in steps)
                + (f" | Сумма: {answers['total']}" if answers.get("total") else ""),
            ]
        )

    # 2. уведомление вам
    lines = [f"🆕 <b>Новая заявка:</b> {escape(DIRECTIONS[direction]['title'])}"]
    if source:
        lines.append(f"Источник: {escape(source)}")
    lines.append(f"Клиент: {user_label(user)}")
    lines.append("")
    for s in steps:
        lines.append(f"<b>{escape(s['label'])}:</b> {escape(str(answers.get(s['key'], '-')))}")
    if answers.get("total"):
        lines.append(f"<b>💰 Сумма:</b> {escape(answers['total'])}")
    await notify_admin(bot, "\n".join(lines))

    # 3. ответ клиенту
    kb = InlineKeyboardBuilder()
    kb.button(text="📣 Перейти в канал", url=CHANNEL_URL)
    kb.button(text="↩️ В начало", callback_data="menu")
    kb.adjust(1)
    await message.answer(
        "Спасибо! Заявку передал. Владелец свяжется с вами лично в ближайшее время.\n"
        "А пока загляните в наш канал: там новости, фото и отзывы.",
        reply_markup=kb.as_markup(),
    )
    await state.clear()


async def record_and_advance(message: Message, user, state: FSMContext, bot: Bot, value: str):
    data = await state.get_data()
    direction, idx = data["direction"], data["idx"]
    steps = steps_for(direction)
    answers = dict(data["answers"])
    key = steps[idx]["key"]
    value = value.strip()

    if direction == "caviar" and key == "qty":
        pack = answers.get("pack", "")
        if pack in CAVIAR_PACK_KG:
            digits = "".join(ch for ch in value if ch.isdigit())
            if not digits or int(digits) <= 0 or int(digits) > 500:
                await message.answer("Напишите, пожалуйста, число банок, например: 2")
                return
            qty = int(digits)
            value = str(qty)
            price = CAVIAR_PRICES.get(answers.get("kind", ""))
            result = calc_caviar(pack, qty, price)
            if result:
                total, kg = result
                kg_text = f"{kg:g}".replace(".", ",")
                answers["total"] = f"{rub(total)} ({kg_text} кг по {rub(price)}/кг)"
                await message.answer(
                    f"Предварительная сумма: <b>{rub(total)}</b> за {kg_text} кг.\n"
                    f"Цена зафиксирована до {CAVIAR_PRICE_UNTIL}. Детали уточнит владелец."
                )
            else:
                answers["total"] = "цена на текущий период формируется, сообщить клиенту"
                await message.answer(
                    "Цена на этот период пока формируется. Я записал вашу заявку, и Дмитрий пришлет точную сумму, "
                    "как только цена будет утверждена."
                )
        else:
            answers["total"] = "объем больше 1 кг, цена обсуждается лично"

    answers[key] = value
    n_dir = len(DIRECTIONS[direction]["steps"])
    nxt = idx + 1
    while nxt < len(steps) and steps[nxt].get("only_own") and "TJ" in answers.get("line", ""):
        nxt += 1
    if direction in ("fire", "board", "surf") and idx < n_dir <= nxt:
        note, total_text = price_summary(direction, answers)
        answers["total"] = total_text
        await message.answer(note)
    idx = nxt
    await state.update_data(answers=answers, idx=idx)
    if idx >= len(steps):
        await finish(message, user, state, bot)
    else:
        await send_question(message, direction, idx, answers)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext):
        # ссылка вида t.me/ИМЯ_БОТА?start=instagram запишет источник заявки
        parts = (message.text or "").split(maxsplit=1)
        source = parts[1] if len(parts) > 1 else ""
        HUMAN_MODE.discard(message.from_user.id)
        await state.clear()
        await state.update_data(source=source)
        await message.answer(WELCOME, reply_markup=main_menu())

    @dp.message(Command("leads"))
    async def leads(message: Message):
        if message.from_user.id != ADMIN_ID:
            return
        if LEADS_FILE.exists():
            await message.answer_document(FSInputFile(LEADS_FILE))
        else:
            await message.answer("Заявок пока нет.")

    @dp.callback_query(F.data == "menu")
    async def to_menu(call: CallbackQuery, state: FSMContext):
        await call.answer()
        data = await state.get_data()
        await state.clear()
        await state.update_data(source=data.get("source", ""))
        await call.message.answer(WELCOME, reply_markup=main_menu())

    @dp.callback_query(F.data.startswith("dir:"))
    async def choose_direction(call: CallbackQuery, state: FSMContext):
        await call.answer()
        direction = call.data.split(":", 1)[1]
        if direction not in DIRECTIONS:
            return
        HUMAN_MODE.discard(call.from_user.id)
        await state.update_data(direction=direction, idx=0, answers={})
        await state.set_state(Flow.answering)
        info_kb = InlineKeyboardBuilder()
        info_kb.button(text="ℹ️ Подробнее о товаре", callback_data=f"info:{direction}")
        await call.message.answer(DIRECTIONS[direction]["intro"], reply_markup=info_kb.as_markup())
        await send_question(call.message, direction, 0)

    @dp.callback_query(F.data.startswith("info:"))
    async def product_info(call: CallbackQuery):
        await call.answer()
        direction = call.data.split(":", 1)[1]
        if direction in DESCRIPTIONS:
            await call.message.answer(DESCRIPTIONS[direction])

    @dp.callback_query(F.data == "story")
    async def story(call: CallbackQuery):
        await call.answer()
        await call.message.answer(STORY, reply_markup=main_menu())

    @dp.callback_query(F.data.startswith("opt:"), Flow.answering)
    async def choose_option(call: CallbackQuery, state: FSMContext, bot: Bot):
        await call.answer()
        data = await state.get_data()
        step = steps_for(data["direction"])[data["idx"]]
        options = step.get("options", [])
        i = int(call.data.split(":", 1)[1])
        if i >= len(options):
            return
        await call.message.answer(f"✅ {options[i]}")
        await record_and_advance(call.message, call.from_user, state, bot, options[i])

    @dp.callback_query(F.data == "human")
    async def human(call: CallbackQuery, state: FSMContext, bot: Bot):
        await call.answer()
        data = await state.get_data()
        text = f"💬 <b>Клиент просит написать лично</b>\n{user_label(call.from_user)}"
        if data.get("direction"):
            text += f"\nНаправление: {escape(DIRECTIONS[data['direction']]['title'])}"
            steps = steps_for(data["direction"])
            for s in steps:
                if s["key"] in data.get("answers", {}):
                    text += f"\n{escape(s['label'])}: {escape(str(data['answers'][s['key']]))}"
        await notify_admin(bot, text)
        HUMAN_MODE.add(call.from_user.id)
        await state.clear()
        await call.message.answer(
            "Передал. Владелец напишет вам лично. Можете сразу написать здесь свой вопрос, я перешлю."
        )

    @dp.message(Flow.answering, F.text)
    async def text_answer(message: Message, state: FSMContext, bot: Bot):
        await record_and_advance(message, message.from_user, state, bot, message.text)

    @dp.message(F.text | F.photo | F.document | F.voice)
    async def fallback(message: Message, bot: Bot):
        if message.from_user.id in HUMAN_MODE and ADMIN_ID:
            await notify_admin(bot, f"✉️ Сообщение от {user_label(message.from_user)}:")
            try:
                await message.forward(ADMIN_ID)
            except Exception:
                logging.exception("Не удалось переслать сообщение")
            return
        await message.answer("Выберите, что вас интересует:", reply_markup=main_menu())

    return dp


async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Создайте файл .env по образцу .env.example")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
