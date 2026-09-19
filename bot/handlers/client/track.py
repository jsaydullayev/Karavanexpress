"""
Client: Yukni kuzatish handleri (TZ §6.4)
Cargo ID + clientga tegishli bo'lishi shart
Cargo ID
"""
import logging

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command

from bot.keyboards.inline_kb import navigation_keyboard
from bot.middlewares.i18n_middleware import I18nMiddleware
from bot.utils.cargo_id_gen import normalize_cargo_id
from bot.utils.notifications import STATUS_KEY_MAP
from database.crud import client_crud, shipment_crud
from database.database import get_session

logger = logging.getLogger(__name__)
track_router = Router()


class TrackStates(StatesGroup):
    waiting_cargo_id = State()


DESCRIPTION_PREVIEW_LEN = 25


def _format_cargo_info(shipment, i18n: I18nMiddleware, lang: str) -> str:
    """Bitta yuk haqidagi to'liq ma'lumot matni"""
    client = shipment.client
    status_text = i18n.get_text(lang, STATUS_KEY_MAP.get(shipment.status, ""))

    # Price + currency birga shakllantirish — bo'sh valyutada trailing space bo'lmaydi
    if shipment.price:
        price_display = f"{shipment.price} {shipment.currency or ''}".strip()
    else:
        price_display = "—"

    return i18n.get_text(
        lang,
        "track_cargo.cargo_info",
        cargo_id=client.cargo_id if client else "—",
        description=shipment.description or "—",
        weight=f"{shipment.weight_kg} kg" if shipment.weight_kg else "—",
        cargo_weight=f"{shipment.cargo_weight_kg} kg" if shipment.cargo_weight_kg else "—",
        price=price_display,
        status=status_text,
        notes=shipment.notes or "—",
        created_at=shipment.created_at.strftime("%d.%m.%Y %H:%M") if shipment.created_at else "—",
    )


def _cargo_info_keyboard(
    i18n: I18nMiddleware,
    lang: str,
    shipment,
    back_callback: str,
) -> InlineKeyboardMarkup:
    """Rasm ko'rish (bo'lsa) + orqaga tugmalari"""
    buttons = []
    if shipment.photo_file_id:
        buttons.append([
            InlineKeyboardButton(
                text=i18n.get_text(lang, "track_cargo.view_photo"),
                callback_data=f"track:photo:{shipment.id}",
            ),
        ])
    buttons.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data=back_callback,
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _shipment_picker_keyboard(
    i18n: I18nMiddleware,
    lang: str,
    shipments: list,
) -> InlineKeyboardMarkup:
    """Bir Cargo IDga bir nechta yuk biriktirilgan bo'lsa — tanlash tugmalari"""
    rows = []
    for idx, ship in enumerate(shipments, start=1):
        status_text = i18n.get_text(lang, STATUS_KEY_MAP.get(ship.status, ""))
        description = ship.description or "—"
        if len(description) > DESCRIPTION_PREVIEW_LEN:
            description = f"{description[:DESCRIPTION_PREVIEW_LEN]}…"
        rows.append([
            InlineKeyboardButton(
                text=f"{idx}. {description} — {status_text}",
                callback_data=f"track:show:{ship.id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data="client:menu",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@track_router.callback_query(F.data == "client:track_cargo")
async def track_cargo_start(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Yuk kuzatishni boshlash — Cargo ID so'rash"""
    lang = i18n.get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(TrackStates.waiting_cargo_id)

    await callback.message.edit_text(
        i18n.get_text(lang, "track_cargo.request_cargo_id"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="client:menu"),
    )
    await callback.answer()


@track_router.message(TrackStates.waiting_cargo_id)
async def cargo_id_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Cargo ID qabul qilindi — clientga tegishli ekanini tekshirish"""
    lang = i18n.get_user_language(message.from_user.id)

    is_valid, cargo_id = normalize_cargo_id(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_cargo_id"))
        return

    back_kb = navigation_keyboard(lang=lang, i18n=i18n, back_callback="client:menu")

    async with get_session() as session:
        client = await client_crud.get_by_cargo_id(session, cargo_id)
        shipments = await shipment_crud.get_by_cargo_id(session, cargo_id) if client else []

    if not client or not shipments:
        await message.answer(i18n.get_text(lang, "my_cargo.no_shipments"), reply_markup=back_kb)
        await state.clear()
        return

    await state.clear()

    # Yagona yuk bo'lsa — to'g'ridan batafsil ma'lumot
    if len(shipments) == 1:
        shipment = shipments[0]
        await message.answer(
            _format_cargo_info(shipment, i18n, lang),
            reply_markup=_cargo_info_keyboard(i18n, lang, shipment, "client:menu"),
        )
        return

    await message.answer(
        i18n.get_text(
            lang,
            "track_cargo.select_shipment",
            cargo_id=cargo_id,
            count=len(shipments),
        ),
        reply_markup=_shipment_picker_keyboard(i18n, lang, shipments),
    )


@track_router.callback_query(F.data.startswith("track:show:"))
async def show_shipment(
    callback: CallbackQuery,
    i18n: I18nMiddleware,
) -> None:
    """Ro'yxatdan tanlangan yukning batafsil ma'lumoti"""
    lang = i18n.get_user_language(callback.from_user.id)

    try:
        shipment_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("⚠️", show_alert=True)
        return

    async with get_session() as session:
        shipment = await shipment_crud.get_by_id(session, shipment_id)

    if not shipment:
        await callback.answer(i18n.get_text(lang, "track_cargo.cargo_not_found"), show_alert=True)
        return

    cargo_id = shipment.client.cargo_id if shipment.client else None
    back_callback = f"track:list:{cargo_id}" if cargo_id else "client:menu"

    await callback.message.edit_text(
        _format_cargo_info(shipment, i18n, lang),
        reply_markup=_cargo_info_keyboard(i18n, lang, shipment, back_callback),
    )
    await callback.answer()


@track_router.callback_query(F.data.startswith("track:list:"))
async def show_shipment_list(
    callback: CallbackQuery,
    i18n: I18nMiddleware,
) -> None:
    """Yuklar ro'yxatiga qaytish"""
    lang = i18n.get_user_language(callback.from_user.id)
    cargo_id = callback.data.split(":", 2)[2]

    async with get_session() as session:
        shipments = await shipment_crud.get_by_cargo_id(session, cargo_id)

    if not shipments:
        await callback.answer(i18n.get_text(lang, "track_cargo.cargo_not_found"), show_alert=True)
        return

    await callback.message.edit_text(
        i18n.get_text(
            lang,
            "track_cargo.select_shipment",
            cargo_id=cargo_id,
            count=len(shipments),
        ),
        reply_markup=_shipment_picker_keyboard(i18n, lang, shipments),
    )
    await callback.answer()


@track_router.callback_query(F.data.startswith("track:photo:"))
async def view_photo(
    callback: CallbackQuery,
    i18n: I18nMiddleware,
    bot: Bot,
) -> None:
    """Yuk rasmini ko'rsatish"""
    lang = i18n.get_user_language(callback.from_user.id)

    try:
        shipment_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("⚠️", show_alert=True)
        return

    async with get_session() as session:
        shipment = await shipment_crud.get_by_id(session, shipment_id)

    if not shipment or not shipment.photo_file_id:
        await callback.answer(i18n.get_text(lang, "track_cargo.cargo_not_found"))
        return

    # Telegram_id tegishlilik tekshiruvi (xavfsizlik)
    if shipment.client.telegram_id != callback.from_user.id:
        await callback.answer(i18n.get_text(lang, "track_cargo.no_access"), show_alert=True)
        return

    try:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=shipment.photo_file_id,
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Rasm yuborib bo'lmadi (shipment {shipment_id}): {e}")
        await callback.answer(i18n.get_text(lang, "errors.unknown_error"), show_alert=True)


@track_router.message(Command("cancel"))
async def cancel_track(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    current = await state.get_state()
    if current is None or not current.startswith("TrackStates:"):
        return
    lang = i18n.get_user_language(message.from_user.id)
    await state.clear()
    await message.answer(i18n.get_text(lang, "manage_cargo.cancelled"))
