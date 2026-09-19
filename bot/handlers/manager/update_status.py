"""
Status yangilash handleri (TZ §5.4)
Cargo ID → joriy status ko'rsatish → yangi status tanlash → notification
"""
import logging

from aiogram import Bot, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.keyboards.inline_kb import navigation_keyboard
from bot.middlewares.i18n_middleware import I18nMiddleware
from bot.utils.cargo_id_gen import normalize_cargo_id
from bot.utils.notifications import send_status_notification, STATUS_KEY_MAP
from database.crud import client_crud, shipment_crud
from database.database import get_session
from database.models import CargoStatus

logger = logging.getLogger(__name__)
update_status_router = Router()


class UpdateStatusStates(StatesGroup):
    """Status yangilash FSM"""
    waiting_cargo_id = State()
    selecting_shipment = State()
    selecting_status = State()


DESCRIPTION_PREVIEW_LEN = 25


def _status_keyboard(i18n: I18nMiddleware, lang: str, current: CargoStatus) -> InlineKeyboardMarkup:
    """5 ta status tugma + back"""
    rows = []
    statuses = [
        CargoStatus.PENDING,
        CargoStatus.IN_TRANSIT,
        CargoStatus.ARRIVED,
        CargoStatus.READY,
        CargoStatus.DELIVERED,
    ]

    pair = []
    for status in statuses:
        is_current = status == current
        prefix = "🔵 " if is_current else ""
        text = i18n.get_text(lang, STATUS_KEY_MAP[status])
        pair.append(InlineKeyboardButton(
            text=f"{prefix}{text}",
            callback_data=f"set_status:{status.value}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data="manager:menu",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                callback_data=f"us:pick:{ship.id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text=i18n.get_text(lang, "buttons.back"),
            callback_data="manager:menu",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_status_selector(
    target: Message | CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
    lang: str,
    shipment,
) -> None:
    """Tanlangan yuk uchun joriy status + yangi status tugmalarini ko'rsatish"""
    client = shipment.client
    current_status_text = i18n.get_text(lang, STATUS_KEY_MAP.get(shipment.status, ""))

    info_text = i18n.get_text(
        lang,
        "update_status.shipment_info",
        name=(client.full_name if client else None) or "—",
        cargo_id=(client.cargo_id if client else None) or "—",
        description=shipment.description or "—",
        status=current_status_text,
    )

    await state.update_data(
        shipment_id=shipment.id,
        cargo_id=client.cargo_id if client else None,
        current_status=shipment.status.value,
    )
    await state.set_state(UpdateStatusStates.selecting_status)

    text = f"{info_text}\n\n{i18n.get_text(lang, 'update_status.select_new_status')}"
    keyboard = _status_keyboard(i18n, lang, shipment.status)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
        await target.answer()
    else:
        await target.answer(text, reply_markup=keyboard)


@update_status_router.callback_query(F.data == "manager:update_status")
async def update_status_start(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Status yangilashni boshlash"""
    lang = i18n.get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(UpdateStatusStates.waiting_cargo_id)

    await callback.message.edit_text(
        i18n.get_text(lang, "update_status.request_cargo_id"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:menu"),
    )
    await callback.answer()


@update_status_router.message(UpdateStatusStates.waiting_cargo_id)
async def cargo_id_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Cargo ID qabul qilindi"""
    lang = i18n.get_user_language(message.from_user.id)

    is_valid, cargo_id = normalize_cargo_id(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_cargo_id"))
        return

    async with get_session() as session:
        client = await client_crud.get_by_cargo_id(session, cargo_id)
        shipments = await shipment_crud.get_by_cargo_id(session, cargo_id)

    if not client:
        await message.answer(i18n.get_text(lang, "manage_cargo.cargo_not_found"))
        return

    if not shipments:
        await message.answer(i18n.get_text(lang, "view_cargos.no_cargos"))
        return

    # Yagona yuk bo'lsa — to'g'ridan status tanlashga o'tamiz
    if len(shipments) == 1:
        await _show_status_selector(message, state, i18n, lang, shipments[0])
        return

    await state.update_data(cargo_id=cargo_id)
    await state.set_state(UpdateStatusStates.selecting_shipment)

    await message.answer(
        i18n.get_text(
            lang,
            "update_status.select_shipment",
            name=client.full_name or "—",
            cargo_id=cargo_id,
            count=len(shipments),
        ),
        reply_markup=_shipment_picker_keyboard(i18n, lang, shipments),
    )


@update_status_router.callback_query(
    UpdateStatusStates.selecting_shipment,
    F.data.startswith("us:pick:"),
)
async def shipment_selected(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Ro'yxatdan yuk tanlandi — status tugmalarini ko'rsatish"""
    lang = i18n.get_user_language(callback.from_user.id)

    try:
        shipment_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("⚠️", show_alert=True)
        return

    async with get_session() as session:
        shipment = await shipment_crud.get_by_id(session, shipment_id)

    if not shipment:
        await callback.answer(
            i18n.get_text(lang, "manage_cargo.cargo_not_found"),
            show_alert=True,
        )
        return

    await _show_status_selector(callback, state, i18n, lang, shipment)


@update_status_router.callback_query(
    UpdateStatusStates.selecting_status,
    F.data.startswith("set_status:"),
)
async def status_selected(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
    bot: Bot,
) -> None:
    """Yangi status tanlandi"""
    lang = i18n.get_user_language(callback.from_user.id)
    data = await state.get_data()

    new_status_str = callback.data.split(":")[1]
    current_status_str = data.get("current_status")
    shipment_id = data.get("shipment_id")

    try:
        new_status = CargoStatus(new_status_str)
    except ValueError:
        await callback.answer("⚠️", show_alert=True)
        return

    if new_status_str == current_status_str:
        await callback.answer(i18n.get_text(lang, "update_status.same_status"), show_alert=True)
        return

    if not shipment_id:
        await callback.answer(i18n.get_text(lang, "errors.session_expired"), show_alert=True)
        await state.clear()
        return

    client = None
    async with get_session() as session:
        updated = await shipment_crud.update_status(session, shipment_id, new_status)
        await session.commit()
        if updated:
            client = updated.client  # eager-loaded by update_status

    notification_sent = False
    if updated and client:
        notification_sent = await send_status_notification(
            bot=bot,
            client=client,
            shipment=updated,
            i18n=i18n,
        )

    new_status_text = i18n.get_text(lang, STATUS_KEY_MAP[new_status])
    result_text = i18n.get_text(lang, "update_status.updated", status=new_status_text)
    if notification_sent:
        result_text += f"\n\n{i18n.get_text(lang, 'create_cargo.notification_sent')}"

    logger.info(
        f"Status yangilandi — Manager: {callback.from_user.id}, "
        f"Shipment: {shipment_id}, Status: {new_status.value}"
    )

    await callback.message.edit_text(
        result_text,
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:menu"),
    )
    await callback.answer()
    await state.clear()
