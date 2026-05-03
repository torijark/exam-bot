import asyncio
import json
import os
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from openai import AsyncOpenAI
from sqlalchemy import func
from aiohttp import web

from config import settings
from models import Session, Card, User

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

user_states = {}

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новый билет"), KeyboardButton(text="📋 Выбрать билет"), KeyboardButton(text="🔁 Повторение")],
            [KeyboardButton(text="📊 Статы"), KeyboardButton(text="🎯 Тест"), KeyboardButton(text="💡 Материалы")]
        ],
        resize_keyboard=True
    )

def anki_buttons():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Уууу"), KeyboardButton(text="😐 Ну такое")],
            [KeyboardButton(text="✅ Намана"), KeyboardButton(text="🚀 Изи")]
        ],
        resize_keyboard=True
    )

def materials_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧠 Мнемоника"), KeyboardButton(text="🔗 Связи")],
            [KeyboardButton(text="🧩 Кейс"), KeyboardButton(text="🏠 В меню")]
        ],
        resize_keyboard=True
    )

def test_buttons():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="A"), KeyboardButton(text="B"), KeyboardButton(text="C"), KeyboardButton(text="D")]
        ],
        resize_keyboard=True
    )

def load_questions():
    with open("questions.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_tests():
    with open("test.json", "r", encoding="utf-8") as f:
        return json.load(f)

def update_card_anki(card: Card, quality: str, score: int = None):
    if score is not None:
        card.last_score = score
        if score < 5:
            card.fail_count += 1
        elif score >= 6:
            card.fail_count = max(0, card.fail_count - 1)
    
    if card.fail_count >= 2:
        card.interval = 1
        card.due_date = datetime.utcnow() + timedelta(days=1)
        card.status = "review"
        return
    
    if quality == "again":
        card.repetitions = 0
        card.interval = 1
        card.ease_factor = max(1.3, card.ease_factor - 0.2)
    elif quality == "hard":
        card.interval = max(1, int(card.interval * 1.2))
        card.ease_factor = max(1.3, card.ease_factor - 0.15)
    elif quality == "good":
        if card.repetitions == 0:
            card.interval = 1
        elif card.repetitions == 1:
            card.interval = 6
        else:
            card.interval = int(card.interval * card.ease_factor)
        card.repetitions += 1
    elif quality == "easy":
        if card.repetitions == 0:
            card.interval = 4
        else:
            card.interval = int(card.interval * card.ease_factor * 1.3)
        card.repetitions += 1
        card.ease_factor = min(2.5, card.ease_factor + 0.15)
    
    card.due_date = datetime.utcnow() + timedelta(days=card.interval)
    card.status = "review"

async def check_with_gpt(question: str, reference: str, student_answer: str, attempts: int, history: list):
    history_text = ""
    for i, h in enumerate(history[:-1], 1):
        history_text += f"\nПопытка {i}: {h}\n"
    
    prompt = f"""Ты — строгий профессор-экзаменатор по магистерской программе «Безопасность систем ИИ». Ты не прощаешь воды, расплывчатых формулировок и пропущенных ключевых пунктов. Твоя задача — дать объективную, жёсткую оценку.

ВОПРОС: {question}

ЭТАЛОННЫЙ ОТВЕТ (то, что должен знать студент):
{reference}

ИСТОРИЯ ОТВЕТОВ:
{history_text if history_text else "Пока нет предыдущих ответов."}
ТЕКУЩИЙ ОТВЕТ (попытка {attempts + 1}):
{student_answer}

ШКАЛА ОЦЕНОК (строго):
• 0–3 балла — ответ близок к нулевому знанию: не названы базовые термины, сплошная вода, ответ не по теме, студент явно не готовился.
• 4–5 баллов — знает отдельные слова, но нет структуры, пропущены ключевые пункты эталона, нет понимания связей между понятиями. Это оценка «удовлетворительно» с натяжкой.
• 6–7 баллов — ответ средний: основная мысль уловлена, но нет детализации, пропущены важные подпункты, есть неточности. НЕ ставь 7, если студент не назвал хотя бы половину ключевых пунктов эталона.
• 8–9 баллов — хороший ответ, почти полный, мелкие недочёты или не хватает 1–2 второстепенных пунктов.
• 10 баллов — идеальный ответ: полная структура, все пункты, примеры, чёткая терминология.

ПРАВИЛА ПРОВЕРКИ:
1. Если ответ расплывчатый, без конкретных терминов из эталона — смело снижай до 3–4 баллов. Не давай «подарочных» баллов за общие фразы.
2. Если пропущен ключевой блок эталона (например, целый уровень полномочий, канал угрозы или классификация) — минимум −3 балла.
3. Если студент пересказывает «своими словами» и теряет суть — это ошибка, а не достоинство.
4. На 1-й или 2-й попытке при оценке < 8 — задай 1–2 КОРОТКИХ наводящих вопроса. Вердикт: "Нужно уточнить".
5. На 3-й попытке ИЛИ если оценка ≥ 8 — дай ФИНАЛЬНУЮ оценку. В поле full_answer напиши ПОЛНЫЙ, РАЗВЁРНУТЫЙ, СТРУКТУРИРОВАННЫЙ ответ, как на экзамене: вступление, основная часть с пунктами, заключение, примеры. Не сокращай.
6. В полях missing и mistakes указывай ТОЛЬКО конкретные термины и факты из эталонного ответа. НИКОГДА не пиши placeholder'ы типа "пункт 1", "ошибка 1", "недостаточная детализация". Вместо этого перечисляй реальные недостающие понятия: например, «Не названы уровни полномочий: административный, системный, физический» или «Пропущена классификация по каналам утечки: электромагнитный, акустический, оптический».

Ответь СТРОГО в JSON.

Если это 1-я или 2-я попытка и оценка < 8:
{{
  "score": 4,
  "verdict": "Нужно уточнить",
  "clarifying_questions": ["Что вы можете добавить про ...?", "Как связаны понятия ... и ...?"],
  "missing": ["конкретный недостающий пункт из эталона"],
  "mistakes": ["конкретная ошибка студента"],
  "advice": "",
  "full_answer": ""
}}

Если это финальная оценка (3-я попытка или оценка >= 8):
{{
  "score": 8,
  "verdict": "Зачтено",
  "clarifying_questions": [],
  "missing": [],
  "mistakes": [],
  "advice": "краткий жёсткий совет",
  "full_answer": "Полный развёрнутый ответ на экзамен: ..."
}}"""
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"score": 0, "verdict": "Ошибка проверки", "clarifying_questions": [], "missing": [], "mistakes": [str(e)], "advice": "Попробуй позже."}

async def generate_mnemonic(question: str, reference: str) -> str:
    prompt = f"Придумай короткую запоминалку/мнемонику (1-2 предложения) для экзаменационного билета. Используй абсурдные ассоциации. Вопрос: {question[:120]}. Ключевые понятия: {reference[:250]}."
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )
        return response.choices[0].message.content
    except:
        return "Не удалось сгенерировать мнемонику."

async def generate_connections(question: str, reference: str, card_id: int) -> str:
    session = Session()
    others = session.query(Card).filter(Card.id != card_id).all()
    others_text = "\n".join([f"Билет {c.id} ({c.category}): {c.question[:80]}..." for c in others[:15]])
    session.close()
    prompt = f"С какими другими темами связан этот билет? Текущий билет: {question[:120]}. Другие билеты:\n{others_text}\nПеречисли 2-3 связи коротко."
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        return response.choices[0].message.content
    except:
        return "Не удалось найти связи."

async def generate_case(question: str, reference: str) -> str:
    prompt = f"""Создай короткий практический кейс (1 абзац) на основе экзаменационного билета. Затем задай 1 конкретный вопрос по этому кейсу, на который студент должен ответить устно.

Вопрос билета: {question[:120]}
Контекст: {reference[:250]}

Формат:
📋 КЕЙС: <текст кейса>
❓ ВОПРОС: <вопрос для ответа>"""
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6
        )
        return response.choices[0].message.content
    except:
        return "📋 КЕЙС: Не удалось сгенерировать кейс.\n❓ ВОПРОС: Попробуй позже."

async def transcribe_voice(voice_file_path: str) -> str:
    with open(voice_file_path, "rb") as audio_file:
        transcript = await client.audio.transcriptions.create(
            model=settings.WHISPER_MODEL,
            file=audio_file
        )
    return transcript.text

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    
    if not user:
        user = User(telegram_id=message.from_user.id, username=message.from_user.username)
        session.add(user)
        session.commit()
        questions = load_questions()
        for q in questions:
            card = Card(user_id=user.id, question=q["question"], reference_answer=q["answer"], category=q["category"])
            session.add(card)
        session.commit()
        await message.answer(
            "⚔️ Да пребудет с тобой Сила, юный падаван!\n\n"
            "🎙️ Отвечай голосом или текстом\n"
            "📚 Если ответ неполный, я задам больше вопросов.\n"
            "💡 Можешь выбрать билет, посмотреть мнемоники, связи и кейсы.\n"
            "🎯 Есть тест для быстрой проверки твоей Силы.\n\n"
            "Выбери действие 👇",
            reply_markup=main_menu()
        )
    else:
        await message.answer("С возвращением, о юный падаван! Готов к битве? 💪", reply_markup=main_menu())
    session.close()

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    user_states.pop(message.from_user.id, None)
    await message.answer("❌ Галя, отмена.", reply_markup=main_menu())

@dp.message(F.text == "📝 Новый билет")
async def new_question(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    card = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").order_by(func.random()).first()
    
    if not card:
        await message.answer("✅ Все билеты в работе! Жми 🔁 Повторение или 📋 Выбрать билет.", reply_markup=main_menu())
        session.close()
        return
    
    user_states[message.from_user.id] = {
        "card_id": card.id,
        "awaiting": "answer",
        "answers_history": [],
        "last_card_id": card.id
    }
    text = f"📌 *Билет #{card.id} | {card.category}*\n\n🎯 *Вопрос:*\n{card.question}\n\n🎙️ Ответь голосом или текстом:"
    await message.answer(text, parse_mode="Markdown")
    session.close()

@dp.message(F.text == "📋 Выбрать билет")
async def select_card_menu(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    cards = session.query(Card).filter(Card.user_id == user.id).order_by(Card.id).all()
    text = "📋 *Все билеты:*\n\n"
    for c in cards:
        status = "🆕" if c.status == "new" else f"📈 {c.last_score or '?'}/10"
        if c.fail_count >= 2:
            status += " 🔥"
        text += f"{c.id}. *{c.category}* — {status}\n"
    text += "\n✏️ Напиши номер билета (1–26):"
    await message.answer(text, parse_mode="Markdown")
    user_states[message.from_user.id] = {"awaiting": "select_card"}
    session.close()

@dp.message(F.text == "🔁 Повторение")
async def review_mode(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    
    problem_card = session.query(Card).filter(
        Card.user_id == user.id,
        Card.due_date <= datetime.utcnow(),
        Card.status != "new"
    ).filter((Card.fail_count >= 2) | (Card.last_score < 5)).order_by(Card.fail_count.desc()).first()
    
    if problem_card:
        card = problem_card
        prefix = "🔥 *Нот симпли лавли эт олл!*\n"
    else:
        card = session.query(Card).filter(
            Card.user_id == user.id,
            Card.due_date <= datetime.utcnow(),
            Card.status != "new"
        ).order_by(Card.due_date).first()
        prefix = ""
    
    if not card:
        new_count = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()
        msg = " Свободен, уходи!" + (f"\nОсталось {new_count} новых — жми 📝 Новый билет!" if new_count else "")
        await message.answer(msg, reply_markup=main_menu())
        session.close()
        return
    
    user_states[message.from_user.id] = {
        "card_id": card.id,
        "awaiting": "answer",
        "answers_history": [],
        "last_card_id": card.id
    }
    text = f"{prefix}🔁 *Повторение | {card.category}*\n📅 Было на: {card.due_date.strftime('%d.%m')}\n\n🎯 *Вопрос:*\n{card.question}\n\n🎙️ Ответь голосом или текстом:"
    await message.answer(text, parse_mode="Markdown")
    session.close()

@dp.message(F.text == "📊 Статы")
async def show_stats(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    cards = session.query(Card).filter(Card.user_id == user.id).order_by(Card.id).all()
    
    total = len(cards)
    new = sum(1 for c in cards if c.status == "new")
    review = sum(1 for c in cards if c.status == "review")
    due = sum(1 for c in cards if c.due_date <= datetime.utcnow() and c.status == "review")
    
    cats = {}
    for c in cards:
        if c.category not in cats:
            cats[c.category] = {"scores": [], "fail": 0, "count": 0}
        cats[c.category]["count"] += 1
        if c.last_score is not None:
            cats[c.category]["scores"].append(c.last_score)
        if c.fail_count >= 2 or (c.last_score is not None and c.last_score < 5):
            cats[c.category]["fail"] += 1
    
    text = f"📊 *Твои статы*\n\nВсего: {total} | 🆕 {new} | 🔁 {review} | ⏰ {due}\n\n"
    
    text += "*📉 Слепые зоны (средний балл):*\n"
    for cat, data in cats.items():
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        bar = "█" * int(avg / 2) + "░" * (5 - int(avg / 2))
        text += f"• {cat}: {bar} {avg:.1f}/10"
        if data["fail"] > 0:
            text += f" ⚠️ {data['fail']} проблемных"
        text += "\n"
    
    text += "\n*📈 Прогресс по билетам:*\n"
    for c in cards:
        if c.last_score is not None:
            bar = "█" * int(c.last_score / 2) + "░" * (5 - int(c.last_score / 2))
            text += f"#{c.id}: {bar} {c.last_score}/10"
            if c.fail_count >= 2:
                text += " 🔥"
            text += "\n"
        else:
            text += f"#{c.id}: [🆕]\n"
    
    problems = [c for c in cards if c.fail_count >= 2 or (c.last_score is not None and c.last_score < 5)]
    if problems:
        text += "\n*🔥 Учи лучше:*\n"
        for c in problems[:5]:
            text += f"Билет #{c.id} ({c.category}) — {c.last_score or '?'}/10, ошибок: {c.fail_count}\n"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())
    session.close()

@dp.message(F.text == "🎯 Тест")
async def start_test(message: types.Message):
    tests = load_tests()
    test = random.choice(tests)
    user_states[message.from_user.id] = {"awaiting": "test", "test_id": test["id"]}
    text = f"🎯 *Тест*\n\n{test['question']}\n\n"
    for i, opt in enumerate(test['options']):
        text += f"{'ABCD'[i]}) {opt}\n"
    await message.answer(text, parse_mode="Markdown", reply_markup=test_buttons())

@dp.message(F.text == "💡 Материалы")
async def materials_cmd(message: types.Message):
    await message.answer("💡 *Дополнительные материалы*\n\nТкни на кпопку:", parse_mode="Markdown", reply_markup=materials_menu())
    state = user_states.get(message.from_user.id, {})
    user_states[message.from_user.id] = {"awaiting": "materials", "last_card_id": state.get("last_card_id")}

@dp.message(F.text == "🏠 В меню")
async def back_to_menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu())
    user_states.pop(message.from_user.id, None)

@dp.message(F.text.in_(["A", "B", "C", "D"]))
async def handle_test_answer(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("awaiting") != "test":
        return
    
    tests = load_tests()
    test_id = user_states[user_id]["test_id"]
    test = next((t for t in tests if t["id"] == test_id), None)
    if not test:
        await message.answer("❌ Ошибка теста.", reply_markup=main_menu())
        return
    
    answer_idx = "ABCD".index(message.text)
    if answer_idx == test["correct"]:
        text = f"✅ *Smooth Operator!*\n\n{test['explanation']}"
    else:
        correct_letter = "ABCD"[test["correct"]]
        text = f"❌ *No No Mr Fish.* Правильный ответ: *{correct_letter}*\n\n{test['explanation']}"
    
    await message.answer(text, parse_mode="Markdown")
    await message.answer("Ещё тест или в меню?", reply_markup=main_menu())
    user_states[user_id] = {"awaiting": "after_test"}

@dp.message(F.text.in_(["🧠 Мнемоника", "🔗 Связи", "🧩 Кейс"]))
async def handle_material(message: types.Message):
    user_id = message.from_user.id
    state = user_states.get(user_id, {})
    if state.get("awaiting") != "materials":
        return
    
    card_id = state.get("last_card_id")
    if not card_id:
        await message.answer("❌ Сначала пройди хотя бы один билет через 📝 или 📋.", reply_markup=main_menu())
        return
    
    session = Session()
    card = session.query(Card).get(card_id)
    
    if message.text == "🧠 Мнемоника":
        if card.mnemonic:
            text = f"🧠 *Мнемоника для билета #{card.id}:*\n_{card.mnemonic}_"
        else:
            await message.answer("🧠 Генерирую мнемонику...")
            mnemonic = await generate_mnemonic(card.question, card.reference_answer)
            card.mnemonic = mnemonic
            session.commit()
            text = f"🧠 *Мнемоника:*\n_{mnemonic}_"
    
    elif message.text == "🔗 Связи":
        if card.connections:
            text = f"🔗 *Связи для билета #{card.id}:*\n{card.connections}"
        else:
            await message.answer("🔗 Ищу связи...")
            connections = await generate_connections(card.question, card.reference_answer, card.id)
            card.connections = connections
            session.commit()
            text = f"🔗 *Связи:*\n{connections}"
    
    elif message.text == "🧩 Кейс":
        if card.case_text:
            case_text = card.case_text
        else:
            await message.answer("🧩 Генерирую кейс...")
            case_text = await generate_case(card.question, card.reference_answer)
            card.case_text = case_text
            session.commit()
        
        await message.answer(f"🧩 *Кейс для билета #{card.id}:*\n{case_text}", parse_mode="Markdown")
        await message.answer("📝 *Напиши или скажи голосом свой ответ на вопрос кейса:*", parse_mode="Markdown")
        
        user_states[user_id] = {
            "awaiting": "case_answer",
            "case_prompt": case_text,
            "last_card_id": card.id
        }
        session.close()
        return  # ВАЖНО: выходим, чтобы не сработал общий код в конце функции
    
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())
    session.close()
    user_states[user_id] = {"awaiting": None, "last_card_id": card_id}

async def process_answer(message: types.Message, answer_text: str):
    user_id = message.from_user.id
    session = Session()
    card_id = user_states[user_id]["card_id"]
    card = session.query(Card).get(card_id)
    
    user_states[user_id]["answers_history"].append(answer_text)
    attempts = len(user_states[user_id]["answers_history"]) - 1
    
    check_msg = await message.answer("🧠 *Думаю...*", parse_mode="Markdown")
    history = user_states[user_id]["answers_history"]
    result = await check_with_gpt(card.question, card.reference_answer, answer_text, attempts, history)
    
    score = result.get("score", 0)
    
    # --- УТОЧНЕНИЕ (1-я или 2-я попытка, оценка < 8) ---
    is_clarification = (result.get("verdict") == "Нужно уточнить") or (attempts < 2 and score < 8)
    
    if is_clarification and attempts < 2:
        questions = result.get("clarifying_questions", [])
        text = f"⚠️ *Пока {score}/10 — давай уточним*\n\n"
        if questions:
            text += "🎯 *Подумай над этим:*\n"
            for q in questions:
                text += f"• {q}\n"
        else:
            text += "🎯 *Попробуй раскрыть ответ подробнее.*\n"
        
        text += "📝 Напиши дополнение или уточнение:"
        
        await check_msg.edit_text(text, parse_mode="Markdown")
        user_states[user_id]["awaiting"] = "clarification"
        session.close()
        return
    
    # --- ФИНАЛЬНАЯ ОЦЕНКА ---
    # Сохраняем full_answer от GPT, если пришёл и в базе ещё нет
    if result.get("full_answer") and not card.full_answer:
        card.full_answer = result["full_answer"]
        session.commit()
    
    # Берём лучший эталон: сгенерированный GPT или оригинал из JSON
    saved_full = card.full_answer or card.reference_answer
    
    emoji = {"Найс": "✅", "Соу соу": "⚠️", "Ю АР ЩТЮПИД!!!": "❌"}.get(result['verdict'], "📝")
    text = f"{emoji} *Финальная оценка: {score}/10*\n⚖️ *Вердикт:* {result['verdict']}\n\n"
    
    if result.get("missing"):
        text += "❗ *Что стоит добавить:*\n" + "\n".join(f"• {m}" for m in result["missing"]) + "\n\n"
    if result.get("mistakes"):
        text += "❌ *Ошибки:*\n" + "\n".join(f"• {m}" for m in result["mistakes"]) + "\n\n"
    
    # Показываем развёрнутый эталонный ответ (из базы или от GPT)
    if saved_full:
        text += f"📋 *Эталонный ответ:*\n_{saved_full}_\n\n"
    
    if result.get("advice"):
        text += f"💡 *Совет:* {result['advice']}\n\n"
    
    text += "Как оценишь сложность ответа?"
    
    await check_msg.edit_text(text, parse_mode="Markdown")
    await message.answer("Выбери кнопку для повторения:", reply_markup=anki_buttons())
    user_states[user_id] = {
        "card_id": card.id,
        "awaiting": "anki_rating",
        "answers_history": history,
        "last_card_id": card.id,
        "last_score": score
    }
    session.close()
async def process_case_answer(message: types.Message, answer_text: str):
    user_id = message.from_user.id
    state = user_states[user_id]
    case_prompt = state["case_prompt"]
    
    check_msg = await message.answer("🧠 *Проверяю ответ на кейс...*", parse_mode="Markdown")
    
    prompt = f"""Ты строгий экзаменатор по магистерской программе «Безопасность систем ИИ». Студенту дали кейс с вопросом. Оцени его устный ответ строго.

КЕЙС И ВОПРОС:
{case_prompt}

ОТВЕТ СТУДЕНТА:
{answer_text}

ПРАВИЛА:
1. Оцени от 0 до 10. Если ответ общий, не по кейсу или вода — снижай до 3–4.
2. Укажи конкретные недостатки (missing) и ошибки (mistakes) — только реальные термины, никаких "пункт 1".
3. Дай краткий совет, как улучшить ответ.
4. Напиши эталонный развёрнутый ответ на вопрос кейса (полный, структурированный).

Ответь СТРОГО в JSON:
{{
  "score": 7,
  "verdict": "Частично",
  "missing": [],
  "mistakes": [],
  "advice": "краткий совет",
  "full_answer": "Эталонный ответ на кейс..."
}}"""
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        import json
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        result = {"score": 0, "verdict": "Ошибка проверки", "missing": [], "mistakes": [str(e)], "advice": "Попробуй позже.", "full_answer": ""}
    
    score = result.get("score", 0)
    emoji = {"Найс": "✅", "Соу соу": "⚠️", "Ю АР ЩТЮПИД!!!": "❌"}.get(result['verdict'], "📝")
    text = f"{emoji} *Оценка кейса: {score}/10*\n⚖️ *Вердикт:* {result['verdict']}\n\n"
    
    if result.get("missing"):
        text += "❗ *Чего не хватило:*\n" + "\n".join(f"• {m}" for m in result["missing"]) + "\n\n"
    if result.get("mistakes"):
        text += "❌ *Ошибки:*\n" + "\n".join(f"• {m}" for m in result["mistakes"]) + "\n\n"
    if result.get("full_answer"):
        text += f"📋 *Эталонный ответ на кейс:*\n_{result['full_answer']}_\n\n"
    if result.get("advice"):
        text += f"💡 *Совет:* {result['advice']}\n\n"
    
    await check_msg.edit_text(text, parse_mode="Markdown")
    await message.answer("Главное меню:", reply_markup=main_menu())
    user_states[user_id] = {"awaiting": None, "last_card_id": state.get("last_card_id")}
    
@dp.message(F.voice | F.audio)
async def handle_voice_answer(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("awaiting") not in ("answer", "clarification", "case_answer"):
        return
    
    voice = message.voice or message.audio
    if not voice:
        await message.answer("❌ Не удалось получить аудио.")
        return
    
    msg = await message.answer("🎙️ А хто это у нас...")
    try:
        file = await bot.get_file(voice.file_id)
        file_path = f"voice_{user_id}_{voice.file_id}.ogg"
        await bot.download_file(file.file_path, file_path)
        
        transcript = await transcribe_voice(file_path)
        os.remove(file_path)
        
        await msg.edit_text(f"📝 *Кусь за бочок:*\n_{transcript}_", parse_mode="Markdown")
        
        if user_states[user_id].get("awaiting") in ("answer", "clarification"):
            await process_answer(message, transcript)
        elif user_states[user_id].get("awaiting") == "case_answer":
            await process_case_answer(message, transcript)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}\nПопробуй текстом.")
        if os.path.exists(file_path):
            os.remove(file_path)

@dp.message(F.text.in_(["❌ Уууу", "😐 Ну такое", "✅ Намана", "🚀 Изи"]))
async def handle_anki(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("awaiting") != "anki_rating":
        return
    
    mapping = {"❌ Уууу": "again", "😐 Ну такое": "hard", "✅ Намана": "good", "🚀 Изи": "easy"}
    quality = mapping[message.text]
    
    session = Session()
    card = session.query(Card).get(user_states[user_id]["card_id"])
    score = user_states[user_id].get("last_score")
    update_card_anki(card, quality, score)
    session.commit()
    
    next_date = card.due_date.strftime("%d.%m.%Y")
    await message.answer(
        f"✅ Сохранено!\n📅 Следующее повторение: *{next_date}*\n📈 Интервал: {card.interval} дн. | Ease: {card.ease_factor:.2f}",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    
    last_card_id = user_states[user_id].get("last_card_id")
    user_states[user_id] = {"awaiting": None, "last_card_id": last_card_id}
    session.close()

@dp.message(F.text)
async def handle_text_answer(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get("awaiting") == "select_card":
        try:
            card_id = int(message.text)
        except ValueError:
            await message.answer("❌ Введи число от 1 до 26")
            return
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
        card = session.query(Card).filter(Card.user_id == user.id, Card.id == card_id).first()
        
        if not card:
            await message.answer("❌ Нет такого билета. Введи номер от 1 до 26.")
            session.close()
            return
        
        user_states[user_id] = {
            "card_id": card.id,
            "awaiting": "answer",
            "answers_history": [],
            "last_card_id": card.id
        }
        text = f"📌 *Билет #{card.id} | {card.category}*\n\n🎯 *Вопрос:*\n{card.question}\n\n🎙️ Ответь голосом или текстом:"
        await message.answer(text, parse_mode="Markdown")
        session.close()
        return
    
    if state.get("awaiting") == "case_answer":
        await process_case_answer(message, message.text)
        return
    
    if state.get("awaiting") in ("answer", "clarification"):
        await process_answer(message, message.text)
        return
    
    if state.get("awaiting") == "anki_rating":
        await message.answer("Выбери кнопку сложности ↓", reply_markup=anki_buttons())
        return
    
    if state.get("awaiting") == "after_test":
        text = message.text.lower()
        if "тест" in text or "test" in text:
            await start_test(message)
        else:
            await back_to_menu(message)
        return

async def daily_reminder():
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=9, minute=0, second=0)
        if target < now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        
        session = Session()
        users = session.query(User).all()
        for user in users:
            due_count = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status == "review").count()
            new_count = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()
            if due_count > 0:
                try:
                    await bot.send_message(
                        user.telegram_id,
                        f"☀️ Проснулись-улыбнулись!\n\n📚 *{due_count}* билетов на повторение.\n🆕 *{new_count}* новых билетов.\n\nЖми 🔁 Повторение!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        session.close()
        await asyncio.sleep(60)

async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()

async def main():
    asyncio.create_task(daily_reminder())
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
