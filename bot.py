{\rtf1\ansi\ansicpg1251\cocoartf2821
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx566\tx1133\tx1700\tx2267\tx2834\tx3401\tx3968\tx4535\tx5102\tx5669\tx6236\tx6803\pardirnatural\partightenfactor0

\f0\fs24 \cf0 import asyncio\
import json\
import os\
from datetime import datetime, timedelta\
\
from aiogram import Bot, Dispatcher, F, types\
from aiogram.filters import Command\
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton\
from openai import AsyncOpenAI\
from sqlalchemy import func\
\
from config import settings\
from models import Session, Card, User\
\
bot = Bot(token=settings.BOT_TOKEN)\
dp = Dispatcher()\
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)\
\
user_states = \{\}\
\
def main_menu():\
    return ReplyKeyboardMarkup(\
        keyboard=[\
            [KeyboardButton(text="\uc0\u55357 \u56541  \u1053 \u1086 \u1074 \u1099 \u1081  \u1073 \u1080 \u1083 \u1077 \u1090 ")],\
            [KeyboardButton(text="\uc0\u55357 \u56577  \u1055 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 ")],\
            [KeyboardButton(text="\uc0\u55357 \u56522  \u1052 \u1086 \u1103  \u1089 \u1090 \u1072 \u1090 \u1080 \u1089 \u1090 \u1080 \u1082 \u1072 ")]\
        ],\
        resize_keyboard=True\
    )\
\
def anki_buttons():\
    return ReplyKeyboardMarkup(\
        keyboard=[\
            [KeyboardButton(text="\uc0\u10060  \u1057 \u1085 \u1086 \u1074 \u1072 "), KeyboardButton(text="\u55357 \u56848  \u1058 \u1088 \u1091 \u1076 \u1085 \u1086 ")],\
            [KeyboardButton(text="\uc0\u9989  \u1061 \u1086 \u1088 \u1086 \u1096 \u1086 "), KeyboardButton(text="\u55357 \u56960  \u1051 \u1077 \u1075 \u1082 \u1086 ")]\
        ],\
        resize_keyboard=True\
    )\
\
def load_questions():\
    with open("questions.json", "r", encoding="utf-8") as f:\
        return json.load(f)\
\
def update_card_anki(card: Card, quality: str):\
    if quality == "again":\
        card.repetitions = 0\
        card.interval = 1\
        card.ease_factor = max(1.3, card.ease_factor - 0.2)\
    elif quality == "hard":\
        card.interval = max(1, int(card.interval * 1.2))\
        card.ease_factor = max(1.3, card.ease_factor - 0.15)\
    elif quality == "good":\
        if card.repetitions == 0:\
            card.interval = 1\
        elif card.repetitions == 1:\
            card.interval = 6\
        else:\
            card.interval = int(card.interval * card.ease_factor)\
        card.repetitions += 1\
    elif quality == "easy":\
        if card.repetitions == 0:\
            card.interval = 4\
        else:\
            card.interval = int(card.interval * card.ease_factor * 1.3)\
        card.repetitions += 1\
        card.ease_factor = min(2.5, card.ease_factor + 0.15)\
    \
    card.due_date = datetime.utcnow() + timedelta(days=card.interval)\
    card.status = "review"\
\
async def check_with_gpt(question: str, reference: str, student_answer: str):\
    prompt = f"""\uc0\u1058 \u1099  \u1089 \u1090 \u1088 \u1086 \u1075 \u1080 \u1081 , \u1085 \u1086  \u1089 \u1087 \u1088 \u1072 \u1074 \u1077 \u1076 \u1083 \u1080 \u1074 \u1099 \u1081  \u1101 \u1082 \u1079 \u1072 \u1084 \u1077 \u1085 \u1072 \u1090 \u1086 \u1088  \u1087 \u1086  \u1084 \u1072 \u1075 \u1080 \u1089 \u1090 \u1077 \u1088 \u1089 \u1082 \u1086 \u1081  \u1087 \u1088 \u1086 \u1075 \u1088 \u1072 \u1084 \u1084 \u1077  \'ab\u1041 \u1077 \u1079 \u1086 \u1087 \u1072 \u1089 \u1085 \u1086 \u1089 \u1090 \u1100  \u1089 \u1080 \u1089 \u1090 \u1077 \u1084  \u1048 \u1048 \'bb.\
\
\uc0\u1042 \u1054 \u1055 \u1056 \u1054 \u1057 : \{question\}\
\
\uc0\u1069 \u1058 \u1040 \u1051 \u1054 \u1053 \u1053 \u1067 \u1049  \u1054 \u1058 \u1042 \u1045 \u1058 :\
\{reference\}\
\
\uc0\u1054 \u1058 \u1042 \u1045 \u1058  \u1057 \u1058 \u1059 \u1044 \u1045 \u1053 \u1058 \u1040 :\
\{student_answer\}\
\
\uc0\u1047 \u1072 \u1076 \u1072 \u1085 \u1080 \u1077 :\
1. \uc0\u1054 \u1094 \u1077 \u1085 \u1080  \u1086 \u1090 \u1074 \u1077 \u1090  \u1087 \u1086  \u1089 \u1084 \u1099 \u1089 \u1083 \u1091  \u1086 \u1090  1 \u1076 \u1086  10.\
2. \uc0\u1042 \u1077 \u1088 \u1076 \u1080 \u1082 \u1090 : \u1047 \u1072 \u1095 \u1090 \u1077 \u1085 \u1086  (7-10) / \u1063 \u1072 \u1089 \u1090 \u1080 \u1095 \u1085 \u1086  (4-6) / \u1053 \u1077 \u1079 \u1072 \u1095 \u1090 \u1077 \u1085 \u1086  (1-3).\
3. \uc0\u1055 \u1077 \u1088 \u1077 \u1095 \u1080 \u1089 \u1083 \u1080  \u1087 \u1088 \u1086 \u1087 \u1091 \u1097 \u1077 \u1085 \u1085 \u1099 \u1077  \u1082 \u1083 \u1102 \u1095 \u1077 \u1074 \u1099 \u1077  \u1087 \u1091 \u1085 \u1082 \u1090 \u1099 .\
4. \uc0\u1059 \u1082 \u1072 \u1078 \u1080  \u1086 \u1096 \u1080 \u1073 \u1082 \u1080 .\
5. \uc0\u1044 \u1072 \u1081  \u1082 \u1086 \u1085 \u1082 \u1088 \u1077 \u1090 \u1085 \u1099 \u1081  \u1089 \u1086 \u1074 \u1077 \u1090 .\
\
\uc0\u1054 \u1090 \u1074 \u1077 \u1090 \u1100  \u1057 \u1058 \u1056 \u1054 \u1043 \u1054  \u1074  JSON:\
\{\{\
  "score": 8,\
  "verdict": "\uc0\u1047 \u1072 \u1095 \u1090 \u1077 \u1085 \u1086 ",\
  "missing": ["\uc0\u1087 \u1091 \u1085 \u1082 \u1090  1"],\
  "mistakes": ["\uc0\u1086 \u1096 \u1080 \u1073 \u1082 \u1072  1"],\
  "advice": "\uc0\u1089 \u1086 \u1074 \u1077 \u1090 "\
\}\}"""\
    try:\
        response = await client.chat.completions.create(\
            model=settings.GPT_MODEL,\
            messages=[\{"role": "user", "content": prompt\}],\
            temperature=0.3,\
            response_format=\{"type": "json_object"\}\
        )\
        import json\
        return json.loads(response.choices[0].message.content)\
    except Exception as e:\
        return \{"score": 0, "verdict": "\uc0\u1054 \u1096 \u1080 \u1073 \u1082 \u1072  \u1087 \u1088 \u1086 \u1074 \u1077 \u1088 \u1082 \u1080 ", "missing": [], "mistakes": [str(e)], "advice": "\u1055 \u1086 \u1087 \u1088 \u1086 \u1073 \u1091 \u1081  \u1087 \u1086 \u1079 \u1078 \u1077 ."\}\
\
async def transcribe_voice(voice_file_path: str) -> str:\
    with open(voice_file_path, "rb") as audio_file:\
        transcript = await client.audio.transcriptions.create(\
            model=settings.WHISPER_MODEL,\
            file=audio_file\
        )\
    return transcript.text\
\
@dp.message(Command("start"))\
async def cmd_start(message: types.Message):\
    session = Session()\
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()\
    \
    if not user:\
        user = User(telegram_id=message.from_user.id, username=message.from_user.username)\
        session.add(user)\
        session.commit()\
        questions = load_questions()\
        for q in questions:\
            card = Card(user_id=user.id, question=q["question"], reference_answer=q["answer"], category=q["category"])\
            session.add(card)\
        session.commit()\
        await message.answer(\
            "\uc0\u55357 \u56395  \u1055 \u1088 \u1080 \u1074 \u1077 \u1090 ! \u1071  \u1090 \u1074 \u1086 \u1081  \u1101 \u1082 \u1079 \u1072 \u1084 \u1077 \u1085 \u1072 \u1094 \u1080 \u1086 \u1085 \u1085 \u1099 \u1081  \u1073 \u1086 \u1090 .\\n\\n"\
            "\uc0\u55356 \u57241 \u65039  \u1054 \u1090 \u1074 \u1077 \u1095 \u1072 \u1081  \u1075 \u1086 \u1083 \u1086 \u1089 \u1086 \u1084  \u1080 \u1083 \u1080  \u1090 \u1077 \u1082 \u1089 \u1090 \u1086 \u1084  \'97 \u1103  \u1074 \u1089 \u1105  \u1087 \u1088 \u1086 \u1074 \u1077 \u1088 \u1102 .\\n"\
            "\uc0\u55357 \u56538  \u1050 \u1072 \u1078 \u1076 \u1099 \u1081  \u1076 \u1077 \u1085 \u1100  \u1073 \u1091 \u1076 \u1091  \u1087 \u1088 \u1080 \u1089 \u1099 \u1083 \u1072 \u1090 \u1100  \u1073 \u1080 \u1083 \u1077 \u1090 \u1099 .\\n\\n\u1042 \u1099 \u1073 \u1077 \u1088 \u1080  \u1076 \u1077 \u1081 \u1089 \u1090 \u1074 \u1080 \u1077  \u55357 \u56391 ",\
            reply_markup=main_menu()\
        )\
    else:\
        await message.answer("\uc0\u1057  \u1074 \u1086 \u1079 \u1074 \u1088 \u1072 \u1097 \u1077 \u1085 \u1080 \u1077 \u1084 ! \u1043 \u1086 \u1090 \u1086 \u1074  \u1082  \u1101 \u1082 \u1079 \u1072 \u1084 \u1077 \u1085 \u1091 ? \u55357 \u56490 ", reply_markup=main_menu())\
    session.close()\
\
@dp.message(Command("cancel"))\
async def cmd_cancel(message: types.Message):\
    user_states.pop(message.from_user.id, None)\
    await message.answer("\uc0\u10060  \u1054 \u1090 \u1084 \u1077 \u1085 \u1077 \u1085 \u1086 .", reply_markup=main_menu())\
\
@dp.message(F.text == "\uc0\u55357 \u56541  \u1053 \u1086 \u1074 \u1099 \u1081  \u1073 \u1080 \u1083 \u1077 \u1090 ")\
async def new_question(message: types.Message):\
    session = Session()\
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()\
    card = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").order_by(func.random()).first()\
    \
    if not card:\
        await message.answer("\uc0\u9989  \u1042 \u1089 \u1077  \u1073 \u1080 \u1083 \u1077 \u1090 \u1099  \u1074  \u1088 \u1072 \u1073 \u1086 \u1090 \u1077 ! \u1046 \u1084 \u1080  \u55357 \u56577  \u1055 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 .", reply_markup=main_menu())\
        session.close()\
        return\
    \
    user_states[message.from_user.id] = \{"card_id": card.id, "awaiting": "answer"\}\
    text = f"\uc0\u55357 \u56524  *\u1041 \u1080 \u1083 \u1077 \u1090  #\{card.id\} | \{card.category\}*\\n\\n\u55356 \u57263  *\u1042 \u1086 \u1087 \u1088 \u1086 \u1089 :*\\n\{card.question\}\\n\\n\u55356 \u57241 \u65039  \u1054 \u1090 \u1074 \u1077 \u1090 \u1100  \u1075 \u1086 \u1083 \u1086 \u1089 \u1086 \u1084  \u1080 \u1083 \u1080  \u1090 \u1077 \u1082 \u1089 \u1090 \u1086 \u1084 :"\
    await message.answer(text, parse_mode="Markdown")\
    session.close()\
\
@dp.message(F.text == "\uc0\u55357 \u56577  \u1055 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 ")\
async def review_mode(message: types.Message):\
    session = Session()\
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()\
    card = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status != "new").order_by(Card.due_date).first()\
    \
    if not card:\
        new_count = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()\
        msg = "\uc0\u55356 \u57225  \u1053 \u1072  \u1089 \u1077 \u1075 \u1086 \u1076 \u1085 \u1103  \u1087 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1081  \u1085 \u1077 \u1090 !" + (f"\\n\u1054 \u1089 \u1090 \u1072 \u1083 \u1086 \u1089 \u1100  \{new_count\} \u1085 \u1086 \u1074 \u1099 \u1093  \'97 \u1078 \u1084 \u1080  \u55357 \u56541  \u1053 \u1086 \u1074 \u1099 \u1081  \u1073 \u1080 \u1083 \u1077 \u1090 !" if new_count else "")\
        await message.answer(msg, reply_markup=main_menu())\
        session.close()\
        return\
    \
    user_states[message.from_user.id] = \{"card_id": card.id, "awaiting": "answer"\}\
    text = f"\uc0\u55357 \u56577  *\u1055 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077  | \{card.category\}*\\n\u55357 \u56517  \u1041 \u1099 \u1083 \u1086  \u1085 \u1072 : \{card.due_date.strftime('%d.%m')\}\\n\\n\u55356 \u57263  *\u1042 \u1086 \u1087 \u1088 \u1086 \u1089 :*\\n\{card.question\}\\n\\n\u55356 \u57241 \u65039  \u1054 \u1090 \u1074 \u1077 \u1090 \u1100  \u1075 \u1086 \u1083 \u1086 \u1089 \u1086 \u1084  \u1080 \u1083 \u1080  \u1090 \u1077 \u1082 \u1089 \u1090 \u1086 \u1084 :"\
    await message.answer(text, parse_mode="Markdown")\
    session.close()\
\
@dp.message(F.text == "\uc0\u55357 \u56522  \u1052 \u1086 \u1103  \u1089 \u1090 \u1072 \u1090 \u1080 \u1089 \u1090 \u1080 \u1082 \u1072 ")\
async def show_stats(message: types.Message):\
    session = Session()\
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()\
    total = session.query(Card).filter(Card.user_id == user.id).count()\
    new = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()\
    review = session.query(Card).filter(Card.user_id == user.id, Card.status == "review").count()\
    due = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status == "review").count()\
    by_cat = session.query(Card.category, func.count(Card.id)).filter(Card.user_id == user.id).group_by(Card.category).all()\
    \
    text = f"\uc0\u55357 \u56522  *\u1058 \u1074 \u1086 \u1103  \u1089 \u1090 \u1072 \u1090 \u1080 \u1089 \u1090 \u1080 \u1082 \u1072 *\\n\\n\u1042 \u1089 \u1077 \u1075 \u1086 : \{total\}\\n\u55356 \u56725  \u1053 \u1086 \u1074 \u1099 \u1093 : \{new\}\\n\u55357 \u56577  \u1042  \u1087 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1080 : \{review\}\\n\u9200  \u1053 \u1072  \u1089 \u1077 \u1075 \u1086 \u1076 \u1085 \u1103 : \{due\}\\n\\n*\u1055 \u1086  \u1082 \u1072 \u1090 \u1077 \u1075 \u1086 \u1088 \u1080 \u1103 \u1084 :*\\n"\
    for cat, cnt in by_cat:\
        text += f"\'95 \{cat\}: \{cnt\}\\n"\
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())\
    session.close()\
\
async def process_answer(message: types.Message, answer_text: str, skip_send_question: bool = False):\
    user_id = message.from_user.id\
    session = Session()\
    card_id = user_states[user_id]["card_id"]\
    card = session.query(Card).get(card_id)\
    \
    check_msg = await message.answer("\uc0\u55358 \u56800  *\u1055 \u1088 \u1086 \u1074 \u1077 \u1088 \u1103 \u1102  \u1086 \u1090 \u1074 \u1077 \u1090 ...*", parse_mode="Markdown")\
    result = await check_with_gpt(card.question, card.reference_answer, answer_text)\
    \
    emoji = \{"\uc0\u1047 \u1072 \u1095 \u1090 \u1077 \u1085 \u1086 ": "\u9989 ", "\u1063 \u1072 \u1089 \u1090 \u1080 \u1095 \u1085 \u1086 ": "\u9888 \u65039 ", "\u1053 \u1077 \u1079 \u1072 \u1095 \u1090 \u1077 \u1085 \u1086 ": "\u10060 "\}.get(result['verdict'], "\u55357 \u56541 ")\
    text = f"\{emoji\} *\uc0\u1054 \u1094 \u1077 \u1085 \u1082 \u1072 : \{result['score']\}/10*\\n\u9878 \u65039  *\u1042 \u1077 \u1088 \u1076 \u1080 \u1082 \u1090 :* \{result['verdict']\}\\n\\n"\
    if result.get("missing"):\
        text += "\uc0\u10071  *\u1055 \u1088 \u1086 \u1087 \u1091 \u1097 \u1077 \u1085 \u1086 :*\\n" + "\\n".join(f"\'95 \{m\}" for m in result["missing"]) + "\\n\\n"\
    if result.get("mistakes"):\
        text += "\uc0\u10060  *\u1054 \u1096 \u1080 \u1073 \u1082 \u1080 :*\\n" + "\\n".join(f"\'95 \{m\}" for m in result["mistakes"]) + "\\n\\n"\
    if result.get("advice"):\
        text += f"\uc0\u55357 \u56481  *\u1057 \u1086 \u1074 \u1077 \u1090 :* \{result['advice']\}\\n\\n"\
    text += "\uc0\u1050 \u1072 \u1082  \u1086 \u1094 \u1077 \u1085 \u1080 \u1096 \u1100  \u1089 \u1083 \u1086 \u1078 \u1085 \u1086 \u1089 \u1090 \u1100 ?"\
    \
    await check_msg.edit_text(text, parse_mode="Markdown")\
    await message.answer("\uc0\u1042 \u1099 \u1073 \u1077 \u1088 \u1080  \u1082 \u1085 \u1086 \u1087 \u1082 \u1091 :", reply_markup=anki_buttons())\
    user_states[user_id] = \{"card_id": card.id, "awaiting": "anki_rating"\}\
    session.close()\
\
@dp.message(F.text)\
async def handle_text_answer(message: types.Message):\
    user_id = message.from_user.id\
    if user_id not in user_states or user_states[user_id].get("awaiting") != "answer":\
        return\
    await process_answer(message, message.text)\
\
@dp.message(F.voice | F.audio)\
async def handle_voice_answer(message: types.Message):\
    user_id = message.from_user.id\
    if user_id not in user_states or user_states[user_id].get("awaiting") != "answer":\
        return\
    \
    voice = message.voice or message.audio\
    if not voice:\
        await message.answer("\uc0\u10060  \u1053 \u1077  \u1091 \u1076 \u1072 \u1083 \u1086 \u1089 \u1100  \u1087 \u1086 \u1083 \u1091 \u1095 \u1080 \u1090 \u1100  \u1072 \u1091 \u1076 \u1080 \u1086 .")\
        return\
    \
    msg = await message.answer("\uc0\u55356 \u57241 \u65039  \u1056 \u1072 \u1089 \u1087 \u1086 \u1079 \u1085 \u1072 \u1102  \u1075 \u1086 \u1083 \u1086 \u1089 ...")\
    try:\
        file = await bot.get_file(voice.file_id)\
        file_path = f"voice_\{user_id\}_\{voice.file_id\}.ogg"\
        await bot.download_file(file.file_path, file_path)\
        \
        transcript = await transcribe_voice(file_path)\
        os.remove(file_path)\
        \
        await msg.edit_text(f"\uc0\u55357 \u56541  *\u1056 \u1072 \u1089 \u1087 \u1086 \u1079 \u1085 \u1072 \u1085 \u1086 :*\\n_\{transcript\}_", parse_mode="Markdown")\
        await process_answer(message, transcript, skip_send_question=True)\
    except Exception as e:\
        await msg.edit_text(f"\uc0\u10060  \u1054 \u1096 \u1080 \u1073 \u1082 \u1072 : \{e\}\\n\u1055 \u1086 \u1087 \u1088 \u1086 \u1073 \u1091 \u1081  \u1090 \u1077 \u1082 \u1089 \u1090 \u1086 \u1084 .")\
        if os.path.exists(file_path):\
            os.remove(file_path)\
\
@dp.message(F.text.in_(["\uc0\u10060  \u1057 \u1085 \u1086 \u1074 \u1072 ", "\u55357 \u56848  \u1058 \u1088 \u1091 \u1076 \u1085 \u1086 ", "\u9989  \u1061 \u1086 \u1088 \u1086 \u1096 \u1086 ", "\u55357 \u56960  \u1051 \u1077 \u1075 \u1082 \u1086 "]))\
async def handle_anki(message: types.Message):\
    user_id = message.from_user.id\
    if user_id not in user_states or user_states[user_id].get("awaiting") != "anki_rating":\
        return\
    \
    mapping = \{"\uc0\u10060  \u1057 \u1085 \u1086 \u1074 \u1072 ": "again", "\u55357 \u56848  \u1058 \u1088 \u1091 \u1076 \u1085 \u1086 ": "hard", "\u9989  \u1061 \u1086 \u1088 \u1086 \u1096 \u1086 ": "good", "\u55357 \u56960  \u1051 \u1077 \u1075 \u1082 \u1086 ": "easy"\}\
    quality = mapping[message.text]\
    \
    session = Session()\
    card = session.query(Card).get(user_states[user_id]["card_id"])\
    update_card_anki(card, quality)\
    session.commit()\
    \
    next_date = card.due_date.strftime("%d.%m.%Y")\
    await message.answer(\
        f"\uc0\u9989  \u1057 \u1086 \u1093 \u1088 \u1072 \u1085 \u1077 \u1085 \u1086 !\\n\u55357 \u56517  \u1057 \u1083 \u1077 \u1076 \u1091 \u1102 \u1097 \u1077 \u1077  \u1087 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 : *\{next_date\}*\\n\u55357 \u56520  \u1048 \u1085 \u1090 \u1077 \u1088 \u1074 \u1072 \u1083 : \{card.interval\} \u1076 \u1085 . | Ease: \{card.ease_factor:.2f\}",\
        parse_mode="Markdown",\
        reply_markup=main_menu()\
    )\
    del user_states[user_id]\
    session.close()\
\
async def daily_reminder():\
    while True:\
        now = datetime.utcnow()\
        target = now.replace(hour=9, minute=0, second=0)\
        if target < now:\
            target += timedelta(days=1)\
        await asyncio.sleep((target - now).total_seconds())\
        \
        session = Session()\
        users = session.query(User).all()\
        for user in users:\
            due_count = session.query(Card).filter(Card.user_id == user.id, Card.due_date <= datetime.utcnow(), Card.status == "review").count()\
            new_count = session.query(Card).filter(Card.user_id == user.id, Card.status == "new").count()\
            if due_count > 0:\
                try:\
                    await bot.send_message(\
                        user.telegram_id,\
                        f"\uc0\u9728 \u65039  \u1044 \u1086 \u1073 \u1088 \u1086 \u1077  \u1091 \u1090 \u1088 \u1086 !\\n\\n\u55357 \u56538  *\{due_count\}* \u1073 \u1080 \u1083 \u1077 \u1090 \u1086 \u1074  \u1085 \u1072  \u1087 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 .\\n\u55356 \u56725  *\{new_count\}* \u1085 \u1086 \u1074 \u1099 \u1093  \u1073 \u1080 \u1083 \u1077 \u1090 \u1086 \u1074 .\\n\\n\u1046 \u1084 \u1080  \u55357 \u56577  \u1055 \u1086 \u1074 \u1090 \u1086 \u1088 \u1077 \u1085 \u1080 \u1077 !",\
                        parse_mode="Markdown"\
                    )\
                except Exception:\
                    pass\
        session.close()\
        await asyncio.sleep(60)\
\
async def main():\
    asyncio.create_task(daily_reminder())\
    await dp.start_polling(bot)\
\
if __name__ == "__main__":\
    asyncio.run(main())}