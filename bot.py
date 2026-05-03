import asyncio
import json
import os
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
            [KeyboardButton(text="📝 Новый билет")],
            [KeyboardButton(text="🔁 Повторение")],
            [KeyboardButton(text="📊 Моя статистика")]
        ],
        resize_keyboard=True
    )

def anki_buttons():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Снова"), KeyboardButton(text="😐 Трудно")],
            [KeyboardButton(text="✅ Хорошо"), KeyboardButton(text="🚀 Легко")]
        ],
        resize_keyboard=True
    )

def load_questions():
    with open("questions.json", "r", encoding="utf-8") as f:
        return json.load(f)

def update_card_anki(card: Card, quality: str):
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
    
    prompt = f"""Ты строгий, но справедливый экзаменатор по магистерской программе «Безопасность систем ИИ». Ты проводишь устный экзамен и помогаешь студенту дойти до правильного ответа, а не просто ставишь оценку.

ВОПРОС: {question}

ЭТАЛОННЫЙ ОТВЕТ (что ожидает комиссия):
{reference}

ИСТОРИЯ ОТВЕТОВ СТУДЕНТА:
{history_text if history_text else "Пока нет предыдущих ответов."}
ТЕКУЩИЙ ОТВЕТ (попытка {attempts + 1}):
{student_answer}

ПРАВИЛА ПРОВЕРКИ:
1. Если это 1-я или 2-я попытка И ответ неполный (оценка < 7) — задай 1-2 КОРОТКИХ наводящих вопроса. Не давай полный разбор! Вердикт: "Нужно уточнить". clarifying_questions должен содержать вопросы.
2. Если это 3-я попытка (независимо от качества) ИЛИ ответ сразу хороший (оценка >= 7) — дай ФИНАЛЬНУЮ развёрнутую оценку: перечисли пропущенное, ошибки, и дай совет "как лучше ответить на экзамене". clarifying_questions пустой.
3. Не задавай наводящие вопросы, если ответ уже достаточно полный (>= 7 баллов).
4. Оценивай по смыслу, не дословно.

Ответь СТРОГО в JSON:
{{
  "score": 8,
  "verdict": "Зачтено",
  "clarifying_questions": [],
  "missing": ["пункт 1"],
  "mistakes": ["ошибка 1"],
  "advice": "совет по экзамену"
}}"""
    try:
        response = await client.chat.completions.create(
            model=settings.GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {
            "score": 0,
            "verdict": "Ошибка проверки",
            "clarifying_questions": [],
            "missing": [],
            "mistakes": [str(e)],
            "advice": "Попробуй позже."
        }

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
            "👋 Привет! Я твой экзаменационный бот.\n\n"
            "🎙️ Отвечай голосом или текстом — я всё проверю.\n"
            "📚 Если ответ неполный, я задам наводящие вопросы.\n"
            "Только после 2–3 попыток дам финальную оценку.\n\n"
            "Выбери действие 👇",
            reply_markup=main_menu()
        )
    else:
        await message.answer("С возвращением! Готов к экзамену? 💪", reply_markup=main_menu())
    session.close()

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    user_states.pop(message.from_user.id, None)
    await message.answer("❌ Отменено.", reply_markup=main_menu())

@dp.message(F.text == "📝 Новый билет")
async def new_question(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    card = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").order_by(func.random()).first()
    
    if not card:
        await message.answer("✅ Все билеты в работе! Жми 🔁 Повторение.", reply_markup=main_menu())
        session.close()
        return
    
    user_states[message.from_user.id] = {
        "card_id": card.id,
        "awaiting": "answer",
        "answers_history": []
    }
    text = f"📌 *Билет #{card.id} | {card.category}*\n\n🎯 *Вопрос:*\n{card.question}\n\n🎙️ Ответь голосом или текстом:"
    await message.answer(text, parse_mode="Markdown")
    session.close()

@dp.message(F.text == "🔁 Повторение")
async def review_mode(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    card = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status != "new").order_by(Card.due_date).first()
    
    if not card:
        new_count = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()
        msg = "🎉 На сегодня повторений нет!" + (f"\nОсталось {new_count} новых — жми 📝 Новый билет!" if new_count else "")
        await message.answer(msg, reply_markup=main_menu())
        session.close()
        return
    
    user_states[message.from_user.id] = {
        "card_id": card.id,
        "awaiting": "answer",
        "answers_history": []
    }
    text = f"🔁 *Повторение | {card.category}*\n📅 Было на: {card.due_date.strftime('%d.%m')}\n\n🎯 *Вопрос:*\n{card.question}\n\n🎙️ Ответь голосом или текстом:"
    await message.answer(text, parse_mode="Markdown")
    session.close()

@dp.message(F.text == "📊 Моя статистика")
async def show_stats(message: types.Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    total = session.query(Card).filter(Card.user_id == user.id).count()
    new = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()
    review = session.query(Card).filter(Card.user_id == user.id, Card.status == "review").count()
    due = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status == "review").count()
    by_cat = session.query(Card.category, func.count(Card.id)).filter(Card.user_id == user.id).group_by(Card.category).all()
    
    text = f"📊 *Твоя статистика*\n\nВсего: {total}\n🆕 Новых: {new}\n🔁 В повторении: {review}\n⏰ На сегодня: {due}\n\n*По категориям:*\n"
    for cat, cnt in by_cat:
        text += f"• {cat}: {cnt}\n"
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())
    session.close()

async def process_answer(message: types.Message, answer_text: str):
    user_id = message.from_user.id
    session = Session()
    card_id = user_states[user_id]["card_id"]
    card = session.query(Card).get(card_id)
    
    # Сохраняем историю
    user_states[user_id]["answers_history"].append(answer_text)
    attempts = len(user_states[user_id]["answers_history"]) - 1  # 0-based
    
    check_msg = await message.answer("🧠 *Думаю...*", parse_mode="Markdown")
    
    history = user_states[user_id]["answers_history"]
    result = await check_with_gpt(card.question, card.reference_answer, answer_text, attempts, history)
    
    # Если нужно уточнить и ещё есть попытки (0 или 1, т.е. 1-я или 2-я попытка)
    if result.get("verdict") == "Нужно уточнить" and attempts < 2:
        questions = result.get("clarifying_questions", [])
        text = f"⚠️ *Пока {result['score']}/10 — давай уточним*\n\n"
        if questions:
            text += "🎯 *Подумай над этим:*\n"
            for q in questions:
                text += f"• {q}\n"
        text += "\n📝 Напиши дополнение или уточнение:"
        
        await check_msg.edit_text(text, parse_mode="Markdown")
        user_states[user_id]["awaiting"] = "clarification"
        session.close()
        return
    
    # Иначе — финальная оценка
    emoji = {"Зачтено": "✅", "Частично": "⚠️", "Незачтено": "❌"}.get(result['verdict'], "📝")
    text = f"{emoji} *Финальная оценка: {result['score']}/10*\n⚖️ *Вердикт:* {result['verdict']}\n\n"
    
    if result.get("missing"):
        text += "❗ *Что стоит добавить:*\n" + "\n".join(f"• {m}" for m in result["missing"]) + "\n\n"
    if result.get("mistakes"):
        text += "❌ *Ошибки:*\n" + "\n".join(f"• {m}" for m in result["mistakes"]) + "\n\n"
    if result.get("advice"):
        text += f"💡 *Как ответить на экзамене:*\n_{result['advice']}_\n\n"
    
    text += "Как оценишь сложность ответа?"
    
    await check_msg.edit_text(text, parse_mode="Markdown")
    await message.answer("Выбери кнопку для повторения:", reply_markup=anki_buttons())
    user_states[user_id] = {
        "card_id": card.id,
        "awaiting": "anki_rating",
        "answers_history": user_states[user_id].get("answers_history", [])
    }
    session.close()

@dp.message(F.voice | F.audio)
async def handle_voice_answer(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("awaiting") not in ("answer", "clarification"):
        return
    
    voice = message.voice or message.audio
    if not voice:
        await message.answer("❌ Не удалось получить аудио.")
        return
    
    msg = await message.answer("🎙️ Распознаю голос...")
    try:
        file = await bot.get_file(voice.file_id)
        file_path = f"voice_{user_id}_{voice.file_id}.ogg"
        await bot.download_file(file.file_path, file_path)
        
        transcript = await transcribe_voice(file_path)
        os.remove(file_path)
        
        await msg.edit_text(f"📝 *Распознано:*\n_{transcript}_", parse_mode="Markdown")
        await process_answer(message, transcript)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}\nПопробуй текстом.")
        if os.path.exists(file_path):
            os.remove(file_path)

@dp.message(F.text.in_(["❌ Снова", "😐 Трудно", "✅ Хорошо", "🚀 Легко"]))
async def handle_anki(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states or user_states[user_id].get("awaiting") != "anki_rating":
        return
    
    mapping = {"❌ Снова": "again", "😐 Трудно": "hard", "✅ Хорошо": "good", "🚀 Легко": "easy"}
    quality = mapping[message.text]
    
    session = Session()
    card = session.query(Card).get(user_states[user_id]["card_id"])
    update_card_anki(card, quality)
    session.commit()
    
    next_date = card.due_date.strftime("%d.%m.%Y")
    await message.answer(
        f"✅ Сохранено!\n📅 Следующее повторение: *{next_date}*\n📈 Интервал: {card.interval} дн. | Ease: {card.ease_factor:.2f}",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    del user_states[user_id]
    session.close()

@dp.message(F.text)
async def handle_text_answer(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return
    state = user_states[user_id]
    if state.get("awaiting") in ("answer", "clarification"):
        await process_answer(message, message.text)
    elif state.get("awaiting") == "anki_rating":
        await message.answer("Выбери кнопку сложности ↓", reply_markup=anki_buttons())

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
                        f"☀️ Доброе утро!\n\n📚 *{due_count}* билетов на повторение.\n🆕 *{new_count}* новых билетов.\n\nЖми 🔁 Повторение!",
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
