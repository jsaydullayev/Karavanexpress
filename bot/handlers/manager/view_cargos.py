"""
Manager: Yuklarni ko'rish handleri (TZ §5.5)
- Barcha yuklar (sahifalab — 10 tadan)
- Status bo'yicha filtr
- Telefon bo'yicha qidirish
- Cargo ID bo'yicha qidirish
"""
import logging
from typing import Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from bot.keyboards.inline_kb import navigation_keyboard
from bot.middlewares.i18n_middleware import I18nMiddleware
from bot.utils.cargo_id_gen import normalize_cargo_id
from bot.utils.notifications import STATUS_KEY_MAP
from database.crud import client_crud, shipment_crud
from database.database import get_session
from database.models import CargoStatus

logger = logging.getLogger(__name__)
view_cargos_router = Router()

PAGE_SIZE = 10


class ViewCargosStates(StatesGroup):
    select_filter = State()
    waiting_phone = State()
    waiting_cargo_id = State()


def _filter_keyboard(i18n: I18nMiddleware, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=i18n.get_text(lang, "view_cargos.all_cargos"),
                callback_data="vc:all:1",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📞 {i18n.get_text(lang, 'view_cargos.by_phone')}",
                callback_data="vc:by_phone",
            ),
            InlineKeyboardButton(
                text=f"🆔 {i18n.get_text(lang, 'view_cargos.by_cargo_id')}",
                callback_data="vc:by_cargo_id",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"📋 {i18n.get_text(lang, 'view_cargos.by_status')}",
                callback_data="vc:by_status",
            ),
        ],
        [
            InlineKeyboardButton(
                text=i18n.get_text(lang, "buttons.back"),
                callback_data="manager:menu",
            ),
        ],
    ])


def _status_filter_keyboard(i18n: I18nMiddleware, lang: str) -> InlineKeyboardMarkup:
    statuses = [
        CargoStatus.PENDING,
        CargoStatus.IN_TRANSIT,
        CargoStatus.ARRIVED,
        CargoStatus.READY,
        CargoStatus.DELIVERED,
    ]
    rows = []
    pair = []
    for s in statuses:
        pair.append(InlineKeyboardButton(
            text=i18n.get_text(lang, STATUS_KEY_MAP[s]),
            callback_data=f"vc:status:{s.value}:1",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data="manager:view_cargos",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pagination_keyboard(
    i18n: I18nMiddleware,
    lang: str,
    base_callback: str,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows = []
    nav_row = []

    if current_page > 1:
        nav_row.append(InlineKeyboardButton(
            text="◀️",
            callback_data=f"{base_callback}:{current_page - 1}",
        ))
    nav_row.append(InlineKeyboardButton(
        text=i18n.get_text(lang, "view_cargos.page", page=current_page, total=total_pages),
        callback_data="noop",
    ))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(
            text="▶️",
            callback_data=f"{base_callback}:{current_page + 1}",
        ))

    if nav_row:
        rows.append(nav_row)

    rows.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data="manager:view_cargos",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_shipments_list(
    shipments: list,
    i18n: I18nMiddleware,
    lang: str,
    page: int = 1,
) -> str:
    if not shipments:
        return i18n.get_text(lang, "view_cargos.no_cargos")

    lines = []
    start_idx = (page - 1) * PAGE_SIZE
    for i, ship in enumerate(shipments, start=start_idx + 1):
        status_text = i18n.get_text(lang, STATUS_KEY_MAP.get(ship.status, ""))
        client = ship.client
        lines.append(
            f"{i}. 🆔 <b>{client.cargo_id}</b> | {status_text}\n"
            f"   👤 {client.full_name or '—'} | 📞 {client.phone_number}\n"
            f"   📋 {ship.description or '—'}\n"
            f"   📅 {ship.created_at.strftime('%d.%m.%Y') if ship.created_at else '—'}"
        )
    return "\n\n".join(lines)


@view_cargos_router.callback_query(F.data == "manager:view_cargos")
async def view_cargos_menu(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Filter tanlash menyusi"""
    lang = i18n.get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(ViewCargosStates.select_filter)

    await callback.message.edit_text(
        i18n.get_text(lang, "view_cargos.select_filter"),
        reply_markup=_filter_keyboard(i18n, lang),
    )
    await callback.answer()


# ============== "Hammasi" filter ==============

@view_cargos_router.callback_query(F.data.startswith("vc:all:"))
async def show_all(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    try:
        page = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        page = 1

    async with get_session() as session:
        total = await shipment_crud.count_all(session)
        shipments = await shipment_crud.get_all(
            session,
            skip=(page - 1) * PAGE_SIZE,
            limit=PAGE_SIZE,
        )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    text = (
        f"📦 <b>{i18n.get_text(lang, 'view_cargos.all_cargos')}</b>\n\n"
        f"{_format_shipments_list(shipments, i18n, lang, page)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=_pagination_keyboard(i18n, lang, "vc:all", page, total_pages),
    )
    await callback.answer()


# ============== Status filter ==============

@view_cargos_router.callback_query(F.data == "vc:by_status")
async def by_status(
    callback: CallbackQuery,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        i18n.get_text(lang, "view_cargos.select_status"),
        reply_markup=_status_filter_keyboard(i18n, lang),
    )
    await callback.answer()


@view_cargos_router.callback_query(F.data.startswith("vc:status:"))
async def show_by_status(
    callback: CallbackQuery,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("⚠️", show_alert=True)
        return

    try:
        status = CargoStatus(parts[2])
        page = int(parts[3])
    except ValueError:
        await callback.answer("⚠️", show_alert=True)
        return

    async with get_session() as session:
        total = await shipment_crud.count_all(session, status_filter=status)
        shipments = await shipment_crud.get_all(
            session,
            skip=(page - 1) * PAGE_SIZE,
            limit=PAGE_SIZE,
            status_filter=status,
        )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    status_text = i18n.get_text(lang, STATUS_KEY_MAP[status])
    text = (
        f"📋 <b>{status_text}</b>\n\n"
        f"{_format_shipments_list(shipments, i18n, lang, page)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=_pagination_keyboard(i18n, lang, f"vc:status:{status.value}", page, total_pages),
    )
    await callback.answer()


# ============== Phone search ==============

@view_cargos_router.callback_query(F.data == "vc:by_phone")
async def by_phone_start(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    await state.set_state(ViewCargosStates.waiting_phone)
    await callback.message.edit_text(
        i18n.get_text(lang, "view_cargos.search_by_phone"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
    )
    await callback.answer()


@view_cargos_router.message(ViewCargosStates.waiting_phone)
async def by_phone_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    phone = (message.text or "").strip()

    if not phone:
        await message.answer(i18n.get_text(lang, "errors.invalid_phone"))
        return

    async with get_session() as session:
        clients = await client_crud.search(session, phone)
        if not clients:
            await message.answer(
                i18n.get_text(lang, "view_cargos.no_cargos"),
                reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
            )
            await state.clear()
            return

        all_shipments = []
        for c in clients:
            ships = await shipment_crud.get_by_client(session, c.id, limit=100)
            all_shipments.extend(ships)

    if not all_shipments:
        await message.answer(
            i18n.get_text(lang, "view_cargos.no_cargos"),
            reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
        )
        await state.clear()
        return

    text = (
        f"📞 <b>{phone}</b>\n\n"
        f"{_format_shipments_list(all_shipments[:PAGE_SIZE], i18n, lang)}"
    )
    await message.answer(
        text,
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
    )
    await state.clear()


# ============== Cargo ID search ==============

@view_cargos_router.callback_query(F.data == "vc:by_cargo_id")
async def by_cargo_id_start(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    await state.set_state(ViewCargosStates.waiting_cargo_id)
    await callback.message.edit_text(
        i18n.get_text(lang, "view_cargos.search_by_cargo"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
    )
    await callback.answer()


@view_cargos_router.message(ViewCargosStates.waiting_cargo_id)
async def by_cargo_id_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)

    is_valid, cargo_id = normalize_cargo_id(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_cargo_id"))
        return

    async with get_session() as session:
        shipments = await shipment_crud.get_by_cargo_id(session, cargo_id)

    if not shipments:
        await message.answer(
            i18n.get_text(lang, "view_cargos.no_cargos"),
            reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
        )
        await state.clear()
        return

    text = (
        f"🆔 <b>{cargo_id}</b>\n\n"
        f"{_format_shipments_list(shipments[:PAGE_SIZE], i18n, lang)}"
    )
    await message.answer(
        text,
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:view_cargos"),
    )
    await state.clear()


# ============== noop (sahifa raqami uchun) ==============

@view_cargos_router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()
