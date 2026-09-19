"""
Cargo ID generator utility
TZ §5.2 — 5 xonali unikal Cargo ID generatsiyasi (00000-99999)

Ikki xil ID formati:
  - oddiy mijoz  : "48392"    — 5 raqam
  - alohida klient: "MS48392" — MS + 5 raqam

`MS` prefiksi ID ning aynan shu alohida klientga tegishliligini bildiradi.

Unikallik RAQAM QISMI bo'yicha tekshiriladi — raqamlar bittagina umumiy
hovuzdan beriladi. Ya'ni "48392" band bo'lsa, "MS48392" ham berilmaydi.
Har bir 5 xonali raqam butun tizimda faqat bir marta ishlatiladi.
"""
import logging
import random
import re

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Client

logger = logging.getLogger(__name__)

ID_MIN = 0
ID_MAX = 99999
ID_DIGITS = 5
MAX_RETRIES = 50

# Alohida klient prefiksi
PREFIX_MS = "MS"
# Bo'sh prefiks — oddiy mijoz
PREFIX_NONE = ""
ALLOWED_PREFIXES = (PREFIX_NONE, PREFIX_MS)

_CARGO_ID_RE = re.compile(rf"^([A-Z]*)(\d{{{ID_DIGITS}}})$")

# Kirill klaviaturasida terilgan "МС" lotin "MS" dan ko'rinishda farq qilmaydi —
# menejer rus tilida yozsa ID topilmay qolmasligi uchun almashtiramiz.
_LOOKALIKE = str.maketrans({
    "М": "M", "м": "M",
    "С": "S", "с": "S",
})


def normalize_cargo_id(raw: str) -> tuple[bool, str]:
    """
    Kiritilgan Cargo ID ni tekshirish va saqlanadigan ko'rinishga keltirish.

    Qabul qiladi: "48392", "ms48392", " MS 48392 ", "ms-48392", kirill "МС48392"
    Qaytaradi: (True, "48392") yoki (True, "MS48392"), aks holda (False, "")
    """
    if not raw:
        return False, ""

    cleaned = re.sub(r"[\s\-_]", "", raw.strip()).translate(_LOOKALIKE).upper()
    match = _CARGO_ID_RE.match(cleaned)
    if not match:
        return False, ""

    prefix, digits = match.groups()
    if prefix not in ALLOWED_PREFIXES:
        return False, ""

    return True, f"{prefix}{digits}"


def split_cargo_id(cargo_id: str) -> tuple[str, str]:
    """Cargo ID ni (prefiks, raqamlar) ga ajratish. Noto'g'ri bo'lsa ("", asl qiymat)."""
    is_valid, normalized = normalize_cargo_id(cargo_id or "")
    if not is_valid:
        return PREFIX_NONE, cargo_id or ""
    return normalized[:-ID_DIGITS], normalized[-ID_DIGITS:]


def is_ms_cargo_id(cargo_id: str) -> bool:
    """Cargo ID alohida klientga (MS) tegishlimi"""
    return split_cargo_id(cargo_id)[0] == PREFIX_MS


class CargoIDGenerator:
    """Unikal Cargo ID generatori (ixtiyoriy prefiks bilan)"""

    @staticmethod
    async def generate_unique_id(session: AsyncSession, prefix: str = PREFIX_NONE) -> str:
        """
        Random Cargo ID generatsiya qiladi va DB orqali unikalligi tekshiriladi.
        Random + retry pattern — barcha mavjud ID'larni xotiraga yuklamaydi.

        Args:
            session: AsyncSession
            prefix: "" (oddiy mijoz) yoki "MS" (alohida klient)

        Returns:
            Cargo ID, masalan: "48392", "00007", "MS48392"

        Raises:
            ValueError: Ruxsat etilmagan prefiks berilsa
            RuntimeError: Agar shu prefiks uchun barcha ID lar band bo'lib qolgan bo'lsa
        """
        if prefix not in ALLOWED_PREFIXES:
            raise ValueError(f"Ruxsat etilmagan Cargo ID prefiksi: {prefix!r}")

        for _ in range(MAX_RETRIES):
            candidate = f"{prefix}{random.randint(ID_MIN, ID_MAX):0{ID_DIGITS}d}"

            if await CargoIDGenerator.is_id_available(session, candidate):
                return candidate

        # Retry tugadi — DB juda to'lib qolgan, sequential search
        logger.warning(
            f"{MAX_RETRIES} ta random urinish muvaffaqiyatsiz "
            f"(prefiks: {prefix!r}), sequential search'ga o'tildi"
        )

        result = await session.execute(
            select(Client.cargo_id).where(Client.cargo_id.is_not(None))
        )
        # Faqat raqam qismini solishtiramiz — prefiksdan qat'i nazar band hisoblanadi
        used_digits = {split_cargo_id(cid)[1] for cid in result.scalars().all()}

        for candidate_int in range(ID_MIN, ID_MAX + 1):
            digits = f"{candidate_int:0{ID_DIGITS}d}"
            if digits not in used_digits:
                return f"{prefix}{digits}"

        raise RuntimeError(
            f"Barcha Cargo ID lar band bo'lib qolgan (prefiks: {prefix!r}, 00000-99999 to'lgan)"
        )

    @staticmethod
    async def is_id_available(session: AsyncSession, cargo_id: str) -> bool:
        """
        Cargo ID bo'sh yoki yo'qligini tekshirish.

        Tekshiruv RAQAM QISMI bo'yicha: "48392" band bo'lsa, "MS48392" ham
        band hisoblanadi — bitta raqam butun tizimda bir marta ishlatiladi.

        Args:
            session: AsyncSession
            cargo_id: Tekshirilayotgan Cargo ID ("48392" yoki "MS48392")

        Returns:
            True — band emas, False — band
        """
        _, digits = split_cargo_id(cargo_id)
        variants = [f"{prefix}{digits}" for prefix in ALLOWED_PREFIXES]

        result = await session.execute(
            select(func.count(Client.id)).where(Client.cargo_id.in_(variants))
        )
        count = result.scalar() or 0
        return count == 0


cargo_id_generator = CargoIDGenerator()
