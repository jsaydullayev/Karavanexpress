"""
"Yangi Cargo ID yaratish" oqimining uchidan-uchiga testi.

Haqiqiy handlerlar, haqiqiy CRUD va haqiqiy FSM ishlatiladi — faqat baza
xotiradagi SQLite va Telegram obyektlari soxta. Ishlab turgan bazaga
UMUMAN tegmaydi.

Ishga tushirish:
    python tests/test_create_cargo_flow.py
"""
import asyncio
import io
import os
import sys
from contextlib import asynccontextmanager

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.middlewares.i18n_middleware import I18nMiddleware
from bot.utils.agents import AGENTS
from database.models import Client
import bot.handlers.manager.create_cargo as cc

AGENT = AGENTS[0]
MANAGER_ID = 777

# SQLite faqat "INTEGER PRIMARY KEY" ni avtomatik o'stiradi (PostgreSQL'da
# BIGINT sequence bilan ishlaydi), shuning uchun DDL qo'lda yozilgan —
# ustunlar, NOT NULL va UNIQUE cheklovlari haqiqiy sxemadagidek.
DDL_CLIENTS = """
CREATE TABLE clients (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   BIGINT UNIQUE,
    phone_number  VARCHAR(20)  NOT NULL UNIQUE,
    cargo_id      VARCHAR(10)  UNIQUE,
    full_name     VARCHAR(255),
    language      VARCHAR(5)   NOT NULL DEFAULT 'uz',
    agent_id      BIGINT REFERENCES clients(id) ON DELETE SET NULL,
    created_at    DATETIME     NOT NULL,
    created_by    BIGINT       NOT NULL
)
"""

engine = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def fake_get_session():
    async with Session() as session:
        yield session


# ============== Soxta Telegram obyektlari ==============

class User:
    def __init__(self, uid=MANAGER_ID):
        self.id = uid
        self.full_name = "Test Manager"


class Msg:
    """Message uchun ham, callback.message uchun ham"""

    def __init__(self, text_=None, uid=MANAGER_ID):
        self.text = text_
        self.from_user = User(uid)
        self.chat = type("Chat", (), {"id": uid})()
        self.sent = []

    async def answer(self, text_, reply_markup=None, **kw):
        self.sent.append(text_)
        return self

    async def edit_text(self, text_, reply_markup=None, **kw):
        self.sent.append(text_)
        return self

    async def edit_reply_markup(self, reply_markup=None):
        return self

    @property
    def last(self):
        return self.sent[-1] if self.sent else ""


class Cb:
    def __init__(self, data, msg, uid=MANAGER_ID):
        self.data = data
        self.message = msg
        self.from_user = User(uid)
        self.alerts = []

    async def answer(self, text_=None, show_alert=False):
        if text_:
            self.alerts.append(text_)


def new_state(uid=MANAGER_ID):
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=uid, user_id=uid),
    )


# ============== Yordamchilar ==============

i18n = I18nMiddleware()
FAILURES = []


def check(name, condition, detail=""):
    mark = "OK  " if condition else "XATO"
    if not condition:
        FAILURES.append(f"{name} — {detail}")
    print(f"   [{mark}] {name}" + (f"  ({detail})" if detail else ""))


async def db_client(phone):
    async with Session() as session:
        result = await session.execute(select(Client).where(Client.phone_number == phone))
        return result.scalar_one_or_none()


async def count_clients(phone):
    async with Session() as session:
        result = await session.execute(select(Client).where(Client.phone_number == phone))
        return len(list(result.scalars().all()))


async def run_flow(owner, phone, manual_id=None):
    """create_cargo oqimini boshidan oxirigacha o'tkazadi, oxirgi matnni qaytaradi"""
    state = new_state()
    msg = Msg()

    await cc.create_cargo_start(Cb("manager:create_cargo", msg), state, i18n)
    await cc.owner_selected(Cb(f"create_cargo:owner:{owner}", msg), state, i18n)

    phone_msg = Msg(text_=phone)
    await cc.phone_received(phone_msg, state, i18n)

    current = await state.get_state()
    if current == cc.CreateCargoStates.choosing_action.state:
        # Mijozda ID bor — "yangi ID" yo'lini tanlaymiz
        await cc.create_new_id_confirm(Cb("create_cargo:create_new", phone_msg), state, i18n)
        await cc.update_existing_id(Cb("create_cargo:update_yes", phone_msg), state, i18n)
    elif current == cc.CreateCargoStates.confirming_new.state:
        await cc.confirm_new_id(Cb("create_cargo:new_yes", phone_msg), state, i18n)
    else:
        raise AssertionError(f"kutilmagan holat: {current}")

    if manual_id is None:
        await cc.save_auto_id(Cb("create_cargo:confirm_auto", phone_msg), state, i18n, bot=None)
        return phone_msg.last

    await cc.manual_id_prompt(Cb("create_cargo:manual_input", phone_msg), state, i18n)
    manual_msg = Msg(text_=manual_id)
    await cc.process_manual_id(manual_msg, state, i18n, bot=None)
    return manual_msg.last


# ============== Testlar ==============

async def main():
    async with engine.begin() as conn:
        await conn.execute(text(DDL_CLIENTS))

    cc.get_session = fake_get_session
    # Handler `isinstance(target, CallbackQuery)` ishlatadi — soxta turimiz
    # shu tekshiruvdan o'tishi uchun modul ichidagi nomni almashtiramiz.
    cc.CallbackQuery = Cb

    print("=" * 70)
    print("1) ODDIY MIJOZ (agentsiz)")
    await run_flow("none", "+998901112233")
    client = await db_client("+998901112233")
    check("mijoz yaratildi", client is not None)
    check(
        "ID 5 xonali, prefikssiz",
        client and client.cargo_id.isdigit() and len(client.cargo_id) == 5,
        client.cargo_id if client else "-",
    )
    check("agentga biriktirilmagan", client and client.agent_id is None)

    print()
    print("2) AGENTNING O'ZIGA MS ID (bazada hali yo'q)")
    await run_flow("ms", AGENT.phone_number)
    agent = await db_client(AGENT.phone_number)
    check("agent yozuvi bitta", await count_clients(AGENT.phone_number) == 1)
    check("ID MS bilan boshlanadi", agent and agent.cargo_id.startswith("MS"), agent.cargo_id if agent else "-")
    check("ismi to'g'ri", agent and agent.full_name == AGENT.full_name)
    check("o'ziga biriktirilmagan", agent and agent.agent_id is None)

    print()
    print("3) AGENT ORQALI KELGAN MIJOZLAR")
    for phone in ("+998901112244", "+998901112255"):
        await run_flow("ms", phone)
        client = await db_client(phone)
        check(f"{phone} MS ID oldi", client and client.cargo_id.startswith("MS"), client.cargo_id if client else "-")
        check(f"{phone} agentga biriktirildi", client and client.agent_id == agent.id)

    print()
    print("4) QO'LDA ID KIRITISH")
    cases = [
        ("ms", "+998901112266", "12345", "MS12345", True),
        ("ms", "+998901112277", "MS54321", "MS54321", True),
        ("none", "+998901112288", "ms99999", "MS99999", True),   # prefiks => biriktirish
        ("ms", "+998901113311", "60002", "MS60002", True),
        ("none", "+998901113322", "60003", "60003", False),
    ]
    for owner, phone, typed, expected, should_link in cases:
        await run_flow(owner, phone, manual_id=typed)
        client = await db_client(phone)
        check(
            f"[{owner}] {typed!r} -> {expected}",
            client and client.cargo_id == expected,
            client.cargo_id if client else "-",
        )
        linked = bool(client and client.agent_id == agent.id)
        check(
            f"     biriktirish {'bor' if should_link else 'yo`q'} bo'lishi kerak",
            linked == should_link,
            f"agent_id={client.agent_id if client else '-'}",
        )

    print()
    print("5) UNIKALLIK — raqam qismi butun tizimda yagona")
    await run_flow("none", "+998901112299", manual_id="70001")
    client = await db_client("+998901112299")
    check("'70001' yaratildi", client and client.cargo_id == "70001")

    result_text = await run_flow("ms", "+998901113300", manual_id="MS70001")
    check("band 'MS70001' rad etildi", await db_client("+998901113300") is None)
    check("band xabari chiqdi", "band" in result_text.lower() or "занят" in result_text.lower())

    print()
    print("6) NOTO'G'RI KIRITISH")
    state = new_state()
    msg = Msg()
    await cc.create_cargo_start(Cb("manager:create_cargo", msg), state, i18n)
    await cc.owner_selected(Cb("create_cargo:owner:ms", msg), state, i18n)
    bad = Msg(text_="salom")
    await cc.phone_received(bad, state, i18n)
    check("noto'g'ri telefon rad etildi", "format" in bad.last.lower() or "⚠️" in bad.last)

    print()
    print("7) MAVJUD MIJOZGA YANGI ID")
    before = await db_client("+998901112233")
    await run_flow("ms", "+998901112233")
    after = await db_client("+998901112233")
    check("ID yangilandi", after.cargo_id != before.cargo_id, f"{before.cargo_id} -> {after.cargo_id}")
    check("yangi ID MS bilan", after.cargo_id.startswith("MS"))
    check("agentga biriktirildi", after.agent_id == agent.id)

    print()
    print("8) UMUMIY QOIDA: MS ID <=> agentga biriktirilgan")
    async with Session() as session:
        rows = list((await session.execute(select(Client).order_by(Client.id))).scalars().all())
    broken = [
        r for r in rows
        if r.id != agent.id and bool(str(r.cargo_id).startswith("MS")) != bool(r.agent_id == agent.id)
    ]
    check("zid yozuv yo'q", not broken, ", ".join(f"{r.cargo_id}/{r.agent_id}" for r in broken))

    print()
    print("=" * 70)
    print(f"BAZA HOLATI ({len(rows)} mijoz):")
    for row in rows:
        tag = "AGENT" if row.id == agent.id else ("-> agent" if row.agent_id == agent.id else "oddiy")
        print(f"   id={row.id:<3} cargo_id={str(row.cargo_id):<9} {row.phone_number:<16} {tag}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} TA XATO:")
        for failure in FAILURES:
            print("   -", failure)
        sys.exit(1)
    print("HAMMA TEST O'TDI")


if __name__ == "__main__":
    asyncio.run(main())
