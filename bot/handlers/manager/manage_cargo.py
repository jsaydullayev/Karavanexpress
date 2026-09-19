"""
Yuk biriktirish handleri (TZ §5.3)
FSM bilan: Cargo ID → Description (majburiy) → Weight → Cargo weight →
Price → Currency → Photo → Notes → Preview → Confirm
"""
import logging
from typing import Any

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from bot.keyboards.inline_kb import (
    confirm_keyboard,
    currency_selection_keyboard,
    navigation_keyboard,
)
from bot.middlewares.i18n_middleware import I18nMiddleware
from bot.utils.cargo_id_gen import normalize_cargo_id
from database.crud import client_crud, shipment_crud
from database.database import get_session

logger = logging.getLogger(__name__)
manage_cargo_router = Router()


class ShipmentForm(StatesGroup):
    """Yuk biriktirish FSM state lari"""
    waiting_cargo_id = State()
    input_description = State()
    input_weight = State()
    input_cargo_weight = State()
    input_price = State()
    input_currency = State()
    input_photo = State()
    input_notes = State()
    confirming = State()


def _skip_keyboard(i18n: I18nMiddleware, lang: str) -> InlineKeyboardMarkup:
    """⏭ Skip + ❌ Cancel tugmalari"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=i18n.get_text(lang, "buttons.skip"),
                callback_data="shipment:skip",
            ),
        ],
        [
            InlineKeyboardButton(
                text=i18n.get_text(lang, "buttons.cancel"),
                callback_data="shipment:cancel",
            ),
        ],
    ])


def _cancel_keyboard(i18n: I18nMiddleware, lang: str) -> InlineKeyboardMarkup:
    """❌ Cancel tugmasi (description uchun — skip yo'q)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=i18n.get_text(lang, "buttons.cancel"),
                callback_data="shipment:cancel",
            ),
        ],
    ])


def _validate_positive_number(value: str) -> tuple[bool, float]:
    """Musbat son validatsiyasi"""
    try:
        num = float(value.replace(",", ".").strip())
        return num > 0, num
    except (ValueError, TypeError, AttributeError):
        return False, 0.0


# ============== Cargo ID kiritish ==============

@manage_cargo_router.callback_query(F.data == "manager:manage_cargo")
async def manage_cargo_start(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Yuk biriktirishni boshlash — Cargo ID so'rash"""
    lang = i18n.get_user_language(callback.from_user.id)
    await state.clear()
    await state.set_state(ShipmentForm.waiting_cargo_id)

    await callback.message.edit_text(
        i18n.get_text(lang, "manage_cargo.request_cargo_id"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:menu"),
    )
    await callback.answer()


@manage_cargo_router.message(ShipmentForm.waiting_cargo_id)
async def cargo_id_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Cargo ID qabul qilindi — clientni topib description so'rash"""
    lang = i18n.get_user_language(message.from_user.id)

    is_valid, cargo_id = normalize_cargo_id(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_cargo_id"))
        return

    async with get_session() as session:
        client = await client_crud.get_by_cargo_id(session, cargo_id)
        existing_count = (
            await shipment_crud.count_by_client(session, client.id) if client else 0
        )

    if not client:
        await message.answer(i18n.get_text(lang, "manage_cargo.cargo_not_found"))
        return

    await state.update_data(
        client_id=client.id,
        cargo_id=cargo_id,
        client_name=client.full_name or "—",
        client_phone=client.phone_number,
    )

    info_text = i18n.get_text(
        lang,
        "manage_cargo.client_found",
        name=client.full_name or "—",
        phone=client.phone_number,
        cargo_id=cargo_id,
    )

    # Bir Cargo IDga bir nechta yuk biriktirilishi mumkin — mavjudlari haqida eslatma
    if existing_count:
        info_text += (
            f"\n\n{i18n.get_text(lang, 'manage_cargo.existing_shipments', count=existing_count)}"
        )

    await message.answer(info_text)
    await _ask_description(message, state, i18n, lang)


async def _ask_description(
    target: Message | CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
    lang: str,
) -> None:
    """Yuk nimaligini so'rash (majburiy)"""
    await state.set_state(ShipmentForm.input_description)
    text = i18n.get_text(lang, "manage_cargo.fields.description")
    keyboard = _cancel_keyboard(i18n, lang)

    if isinstance(target, CallbackQuery):
        await target.message.answer(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


# ============== Description (majburiy) ==============

@manage_cargo_router.message(ShipmentForm.input_description)
async def description_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Yuk nimaligi — majburiy maydon (TZ §5.3 AC-02)"""
    lang = i18n.get_user_language(message.from_user.id)
    text = (message.text or "").strip()

    if not text:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.description_required"))
        return

    await state.update_data(description=text)
    await _ask_weight(message, state, i18n, lang)


async def _ask_weight(target: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    await state.set_state(ShipmentForm.input_weight)
    await target.answer(
        i18n.get_text(lang, "manage_cargo.fields.weight"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


# ============== Weight (ixtiyoriy) ==============

@manage_cargo_router.message(ShipmentForm.input_weight)
async def weight_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    is_valid, value = _validate_positive_number(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_number"))
        return

    await state.update_data(weight=value)
    await _ask_cargo_weight(message, state, i18n, lang)


async def _ask_cargo_weight(target: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    await state.set_state(ShipmentForm.input_cargo_weight)
    await target.answer(
        i18n.get_text(lang, "manage_cargo.fields.cargo_weight"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


# ============== Cargo weight (ixtiyoriy) ==============

@manage_cargo_router.message(ShipmentForm.input_cargo_weight)
async def cargo_weight_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    is_valid, value = _validate_positive_number(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_number"))
        return

    await state.update_data(cargo_weight=value)
    await _ask_price(message, state, i18n, lang)


async def _ask_price(target: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    await state.set_state(ShipmentForm.input_price)
    await target.answer(
        i18n.get_text(lang, "manage_cargo.fields.price"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


# ============== Price (ixtiyoriy) ==============

@manage_cargo_router.message(ShipmentForm.input_price)
async def price_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    is_valid, value = _validate_positive_number(message.text or "")

    if not is_valid:
        await message.answer(i18n.get_text(lang, "manage_cargo.errors.invalid_number"))
        return

    await state.update_data(price=value)
    await _ask_currency(message, state, i18n, lang)


async def _ask_currency(target: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    """Valyuta — faqat narx kiritilgan bo'lsa (TZ §5.3 AC-02 №4)"""
    await state.set_state(ShipmentForm.input_currency)
    await target.answer(
        i18n.get_text(lang, "manage_cargo.fields.currency"),
        reply_markup=currency_selection_keyboard(lang=lang, i18n=i18n),
    )


# ============== Currency (callback) ==============

@manage_cargo_router.callback_query(ShipmentForm.input_currency, F.data.startswith("currency:"))
async def currency_selected(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    currency = callback.data.split(":")[1]

    if currency == "skip":
        await state.update_data(currency=None)
    elif currency in ("USD", "UZS"):
        await state.update_data(currency=currency)
    else:
        await callback.answer("⚠️", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_photo(callback.message, state, i18n, lang)
    await callback.answer()


# ============== Photo (ixtiyoriy) ==============

async def _ask_photo(message: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    await state.set_state(ShipmentForm.input_photo)
    await message.answer(
        i18n.get_text(lang, "manage_cargo.fields.photo"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


@manage_cargo_router.message(ShipmentForm.input_photo, F.photo)
async def photo_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await _ask_notes(message, state, i18n, lang)


@manage_cargo_router.message(ShipmentForm.input_photo)
async def photo_invalid(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """Rasm o'rniga matn yuborilsa — qayta so'rash"""
    lang = i18n.get_user_language(message.from_user.id)
    await message.answer(
        i18n.get_text(lang, "manage_cargo.fields.photo"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


async def _ask_notes(message: Message, state: FSMContext, i18n: I18nMiddleware, lang: str) -> None:
    await state.set_state(ShipmentForm.input_notes)
    await message.answer(
        i18n.get_text(lang, "manage_cargo.fields.notes"),
        reply_markup=_skip_keyboard(i18n, lang),
    )


# ============== Notes (ixtiyoriy) ==============

@manage_cargo_router.message(ShipmentForm.input_notes)
async def notes_input(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(message.from_user.id)
    notes = (message.text or "").strip() or None
    await state.update_data(notes=notes)
    await _show_preview(message, state, i18n, lang)


# ============== Skip callback ==============

@manage_cargo_router.callback_query(F.data == "shipment:skip")
async def skip_field(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    """⏭ tugma har bir ixtiyoriy maydon uchun"""
    lang = i18n.get_user_language(callback.from_user.id)
    current_state = await state.get_state()

    await callback.message.edit_reply_markup(reply_markup=None)

    if current_state == ShipmentForm.input_weight.state:
        await state.update_data(weight=None)
        await _ask_cargo_weight(callback.message, state, i18n, lang)
    elif current_state == ShipmentForm.input_cargo_weight.state:
        await state.update_data(cargo_weight=None)
        await _ask_price(callback.message, state, i18n, lang)
    elif current_state == ShipmentForm.input_price.state:
        # Narx skip → valyuta ham skip (TZ §5.3 AC-02 №4)
        await state.update_data(price=None, currency=None)
        await _ask_photo(callback.message, state, i18n, lang)
    elif current_state == ShipmentForm.input_photo.state:
        await state.update_data(photo_id=None)
        await _ask_notes(callback.message, state, i18n, lang)
    elif current_state == ShipmentForm.input_notes.state:
        await state.update_data(notes=None)
        await _show_preview(callback.message, state, i18n, lang)
    else:
        await callback.answer("⚠️", show_alert=True)
        return

    await callback.answer()


# ============== Cancel callback ==============

@manage_cargo_router.callback_query(F.data == "shipment:cancel")
async def cancel_shipment_cb(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(
        i18n.get_text(lang, "manage_cargo.cancelled"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:menu"),
    )
    await callback.answer()


# ============== Preview ==============

def _format_preview(data: dict, i18n: I18nMiddleware, lang: str) -> str:
    # Price + currency birga shakllantirish — bo'sh valyutada trailing space bo'lmaydi
    if data.get("price"):
        price_display = f"{data['price']} {data.get('currency') or ''}".strip()
    else:
        price_display = "—"

    return i18n.get_text(
        lang,
        "manage_cargo.preview",
        cargo_id=data.get("cargo_id", "—"),
        client_name=data.get("client_name", "—"),
        description=data.get("description", "—"),
        weight=f"{data['weight']} kg" if data.get("weight") else "—",
        cargo_weight=f"{data['cargo_weight']} kg" if data.get("cargo_weight") else "—",
        price=price_display,
        notes=data.get("notes") or "—",
    )


async def _show_preview(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
    lang: str,
) -> None:
    await state.set_state(ShipmentForm.confirming)
    data = await state.get_data()
    preview = _format_preview(data, i18n, lang)

    await message.answer(
        preview,
        reply_markup=confirm_keyboard(
            lang=lang,
            i18n=i18n,
            confirm_callback="shipment:confirm",
            cancel_callback="shipment:cancel",
        ),
    )


# ============== Confirm — DBga yozish ==============

@manage_cargo_router.callback_query(F.data == "shipment:confirm")
async def confirm_shipment(
    callback: CallbackQuery,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    lang = i18n.get_user_language(callback.from_user.id)
    data = await state.get_data()

    client_id = data.get("client_id")
    description = data.get("description")

    if not client_id or not description:
        await callback.answer(i18n.get_text(lang, "errors.session_expired"), show_alert=True)
        await state.clear()
        return

    async with get_session() as session:
        await shipment_crud.create(
            session=session,
            client_id=client_id,
            description=description,
            weight_kg=data.get("weight"),
            cargo_weight_kg=data.get("cargo_weight"),
            price=data.get("price"),
            currency=data.get("currency"),
            photo_file_id=data.get("photo_id"),
            notes=data.get("notes"),
            created_by=callback.from_user.id,
        )
        await session.commit()

    logger.info(
        f"Shipment yaratildi — Manager: {callback.from_user.id}, "
        f"Cargo: {data.get('cargo_id')}, Client: {client_id}"
    )

    await callback.message.edit_text(
        i18n.get_text(lang, "manage_cargo.saved"),
        reply_markup=navigation_keyboard(lang=lang, i18n=i18n, back_callback="manager:menu"),
    )
    await callback.answer()
    await state.clear()


# ============== /cancel komandasi ==============

@manage_cargo_router.message(Command("cancel"))
async def cancel_shipment_cmd(
    message: Message,
    state: FSMContext,
    i18n: I18nMiddleware,
) -> None:
    current = await state.get_state()
    if current is None or not current.startswith("ShipmentForm:"):
        return
    lang = i18n.get_user_language(message.from_user.id)
    await state.clear()
    await message.answer(i18n.get_text(lang, "manage_cargo.cancelled"))
