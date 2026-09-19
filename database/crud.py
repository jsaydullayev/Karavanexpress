"""
CRUD operations for Cargo Telegram Bot
"""
from typing import List, Optional, Any
from datetime import datetime

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from .models import Client, Shipment, Group, GroupCategory, CompanyInfo, CargoStatus


class ClientCRUD:
    """Client CRUD operations"""

    @staticmethod
    async def get_by_phone(session: AsyncSession, phone_number: str) -> Optional[Client]:
        """Telefon raqam bo'yicha clientni topish"""
        result = await session.execute(
            select(Client).where(Client.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_cargo_id(session: AsyncSession, cargo_id: str) -> Optional[Client]:
        """Cargo ID bo'yicha clientni topish"""
        result = await session.execute(
            select(Client).where(Client.cargo_id == cargo_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[Client]:
        """Telegram ID bo'yicha clientni topish"""
        result = await session.execute(
            select(Client).where(Client.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        phone_number: str,
        cargo_id: Optional[str] = None,
        created_by: int = 0,
        telegram_id: Optional[int] = None,
        full_name: Optional[str] = None,
        language: str = "uz",
        agent_id: Optional[int] = None,
    ) -> Client:
        """Yangi client yaratish"""
        client = Client(
            phone_number=phone_number,
            cargo_id=cargo_id,
            created_by=created_by,
            telegram_id=telegram_id,
            full_name=full_name,
            language=language,
            agent_id=agent_id,
        )
        session.add(client)
        await session.flush()
        return client

    @staticmethod
    async def get_or_create_agent(
        session: AsyncSession,
        phone_number: str,
        full_name: str,
        created_by: int,
    ) -> Client:
        """
        Agent (alohida klient) yozuvini telefon raqami bo'yicha topish,
        bo'lmasa yaratish. Qarang: bot/utils/agents.py
        """
        agent = await ClientCRUD.get_by_phone(session, phone_number)

        if agent is None:
            agent = Client(
                phone_number=phone_number,
                full_name=full_name,
                created_by=created_by,
            )
            session.add(agent)
            await session.flush()
        elif not agent.full_name:
            # Bazada raqam bor, lekin ism yo'q — to'ldirib qo'yamiz
            agent.full_name = full_name
            await session.flush()

        return agent

    @staticmethod
    async def set_agent(
        session: AsyncSession,
        client_id: int,
        agent_id: Optional[int],
    ) -> Optional[Client]:
        """Mijozni agentga biriktirish (o'zini o'ziga biriktirib bo'lmaydi)"""
        if client_id == agent_id:
            return None

        result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.agent_id = agent_id
            await session.flush()
        return client

    @staticmethod
    async def update_cargo_id(
        session: AsyncSession,
        client_id: int,
        new_cargo_id: str,
    ) -> Optional[Client]:
        """Clientning Cargo ID sini yangilash"""
        result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.cargo_id = new_cargo_id
            await session.flush()
        return client

    @staticmethod
    async def link_telegram(
        session: AsyncSession,
        phone_number: str,
        telegram_id: int,
        language: str = "uz",
    ) -> Optional[Client]:
        """Clientga Telegram ID biriktirish"""
        result = await session.execute(
            select(Client).where(Client.phone_number == phone_number)
        )
        client = result.scalar_one_or_none()
        if client:
            client.telegram_id = telegram_id
            client.language = language
            await session.flush()
        return client

    @staticmethod
    async def update_language(
        session: AsyncSession,
        telegram_id: int,
        language: str,
    ) -> Optional[Client]:
        """Client tilini yangilash"""
        result = await session.execute(
            select(Client).where(Client.telegram_id == telegram_id)
        )
        client = result.scalar_one_or_none()
        if client:
            client.language = language
            await session.flush()
        return client

    @staticmethod
    async def get_all(
        session: AsyncSession,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Client]:
        """Barcha clientlarni olish (pagination bilan)"""
        result = await session.execute(
            select(Client).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_all(
        session: AsyncSession,
        created_by: Optional[int] = None,
    ) -> int:
        """Mijozlar umumiy sonini hisoblash (created_by berilsa, faqat shu manager yaratganlari)"""
        query = select(func.count(Client.id))
        if created_by is not None:
            query = query.where(Client.created_by == created_by)
        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_all_for_export(
        session: AsyncSession,
        with_cargo_id_only: bool = False,
    ) -> List[tuple]:
        """
        Excel eksport uchun barcha mijozlarni yuklar soni bilan olish

        Returns:
            Tuple ro'yxati: (cargo_id, full_name, phone, telegram_id, language,
                             created_at, shipments_count, agent_name)
        """
        shipments_count_subq = (
            select(Shipment.client_id, func.count(Shipment.id).label("ship_count"))
            .group_by(Shipment.client_id)
            .subquery()
        )

        agent = aliased(Client)

        query = (
            select(
                Client.cargo_id,
                Client.full_name,
                Client.phone_number,
                Client.telegram_id,
                Client.language,
                Client.created_at,
                func.coalesce(shipments_count_subq.c.ship_count, 0),
                agent.full_name,
            )
            .outerjoin(shipments_count_subq, shipments_count_subq.c.client_id == Client.id)
            .outerjoin(agent, Client.agent_id == agent.id)
            .order_by(Client.created_at.desc())
        )

        if with_cargo_id_only:
            query = query.where(Client.cargo_id.is_not(None))

        result = await session.execute(query)
        return list(result.all())

    @staticmethod
    async def count_with_cargo_id(
        session: AsyncSession,
        created_by: Optional[int] = None,
    ) -> int:
        """Cargo ID berilgan mijozlar sonini hisoblash"""
        query = select(func.count(Client.id)).where(Client.cargo_id.is_not(None))
        if created_by is not None:
            query = query.where(Client.created_by == created_by)
        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def search(
        session: AsyncSession,
        query: str,
    ) -> List[Client]:
        """Clientlarni qidirish (telefon, cargo_id, ism bo'yicha)"""
        conditions = [
            Client.phone_number.contains(query),
            Client.full_name.ilike(f"%{query}%"),
        ]

        # Cargo_id bo'yicha qidirish (agar None bo'lmasa)
        conditions.append(Client.cargo_id == query)

        result = await session.execute(
            select(Client).where(or_(*conditions))
        )
        return list(result.scalars().all())


class ShipmentCRUD:
    """Shipment CRUD operations"""

    @staticmethod
    async def get_latest_by_cargo_id(
        session: AsyncSession,
        cargo_id: str
    ) -> Optional[Shipment]:
        """Cargo ID bo'yicha oxirgi yukni olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
            .where(Client.cargo_id == cargo_id)
            .order_by(Shipment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, shipment_id: int) -> Optional[Shipment]:
        """ID bo'yicha yukni topish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .where(Shipment.id == shipment_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_client(
        session: AsyncSession,
        client_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> List[Shipment]:
        """Clientning barcha yuklarini olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .where(Shipment.client_id == client_id)
            .order_by(Shipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_client(session: AsyncSession, client_id: int) -> int:
        """Clientga biriktirilgan yuklar sonini hisoblash"""
        result = await session.execute(
            select(func.count(Shipment.id)).where(Shipment.client_id == client_id)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_by_client_and_status(
        session: AsyncSession,
        client_id: int,
        status: CargoStatus,
    ) -> List[Shipment]:
        """Clientning ma'lum statusdagi yuklarini olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .where(
                and_(
                    Shipment.client_id == client_id,
                    Shipment.status == status
                )
            )
            .order_by(Shipment.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_cargo_id(
        session: AsyncSession,
        cargo_id: str,
    ) -> List[Shipment]:
        """Cargo ID bo'yicha barcha yuklarni olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
            .where(Client.cargo_id == cargo_id)
            .order_by(Shipment.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_cargo_id_and_verify(
        session: AsyncSession,
        cargo_id: str,
        phone_number: str,
    ) -> List[Shipment]:
        """Cargo ID va telefon raqam bo'yicha yuklarni olish (client tasdiqlash uchun)"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
            .where(
                and_(
                    Client.cargo_id == cargo_id,
                    Client.phone_number == phone_number,
                )
            )
            .order_by(Shipment.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_cargo_id_and_verify_telegram(
        session: AsyncSession,
        cargo_id: str,
        telegram_id: int,
    ) -> List[Shipment]:
        """Cargo ID va Telegram ID bo'yicha yuklarni olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
            .where(
                and_(
                    Client.cargo_id == cargo_id,
                    Client.telegram_id == telegram_id,
                )
            )
            .order_by(Shipment.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_status(
        session: AsyncSession,
        status: CargoStatus,
        skip: int = 0,
        limit: int = 10,
    ) -> List[Shipment]:
        """Status bo'yicha yuklarni olish"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .where(Shipment.status == status)
            .order_by(Shipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create(
        session: AsyncSession,
        client_id: int,
        description: str,
        created_by: int,
        weight_kg: Optional[float] = None,
        cargo_weight_kg: Optional[float] = None,
        price: Optional[float] = None,
        currency: Optional[str] = None,
        photo_file_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Shipment:
        """Yangi yuk yaratish"""
        shipment = Shipment(
            client_id=client_id,
            description=description,
            weight_kg=weight_kg,
            cargo_weight_kg=cargo_weight_kg,
            price=price,
            currency=currency,
            photo_file_id=photo_file_id,
            notes=notes,
            created_by=created_by,
        )
        session.add(shipment)
        await session.flush()
        return shipment

    @staticmethod
    async def update_status(
        session: AsyncSession,
        shipment_id: int,
        status: CargoStatus,
    ) -> Optional[Shipment]:
        """Yuk statusini yangilash (client eager-loaded)"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .where(Shipment.id == shipment_id)
        )
        shipment = result.scalar_one_or_none()
        if shipment:
            shipment.status = status
            shipment.updated_at = datetime.utcnow()
            await session.flush()
        return shipment

    @staticmethod
    async def update_status_by_cargo_id(
        session: AsyncSession,
        cargo_id: str,
        status: CargoStatus,
    ) -> Optional[Shipment]:
        """Cargo ID bo'yicha oxirgi yukning statusini yangilash"""
        result = await session.execute(
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
            .where(Client.cargo_id == cargo_id)
            .order_by(Shipment.created_at.desc())
            .limit(1)
        )
        shipment = result.scalar_one_or_none()
        if shipment:
            shipment.status = status
            shipment.updated_at = datetime.utcnow()
            await session.flush()
        return shipment

    @staticmethod
    async def get_all_for_export(
        session: AsyncSession,
        active_only: bool = False,
    ) -> List[tuple]:
        """
        Excel eksport uchun barcha yuklarni olish.

        Agent nomi OXIRIDA (index 10) turadi — oldingi indekslar o'zgarmasin
        (export.py status bo'yicha filtrda `row[8]` ni ishlatadi).
        """
        agent = aliased(Client)

        query = select(
            Client.cargo_id,
            Client.full_name,
            Client.phone_number,
            Shipment.description,
            Shipment.weight_kg,
            Shipment.cargo_weight_kg,
            Shipment.price,
            Shipment.currency,
            Shipment.status,
            Shipment.created_at,
            agent.full_name,
        ).select_from(Shipment).join(
            # Ikkita Client (mijoz + agent aliasi) bo'lgani uchun ON shart aniq
            # yozilgan — aks holda SQLAlchemy qaysi tomondan bog'lashni bilmaydi.
            Client, Shipment.client_id == Client.id,
        ).outerjoin(agent, Client.agent_id == agent.id)

        if active_only:
            query = query.where(Shipment.status != CargoStatus.DELIVERED)

        query = query.order_by(Shipment.created_at.desc())

        result = await session.execute(query)
        return list(result.all())

    @staticmethod
    async def get_all(
        session: AsyncSession,
        skip: int = 0,
        limit: int = 10,
        status_filter: Optional[CargoStatus] = None,
        phone_filter: Optional[str] = None,
        cargo_id_filter: Optional[str] = None,
    ) -> List[Shipment]:
        """Barcha yuklarni olish (filterlar bilan, client eager-loaded)"""
        query = (
            select(Shipment)
            .options(selectinload(Shipment.client))
            .join(Client)
        )

        if status_filter:
            query = query.where(Shipment.status == status_filter)

        if phone_filter:
            query = query.where(Client.phone_number.contains(phone_filter))

        if cargo_id_filter:
            query = query.where(Client.cargo_id == cargo_id_filter)

        query = query.order_by(Shipment.created_at.desc()).offset(skip).limit(limit)

        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def count_all(
        session: AsyncSession,
        status_filter: Optional[CargoStatus] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """Barcha yuklar sonini hisoblash"""
        query = select(func.count(Shipment.id)).join(Client)

        if status_filter:
            query = query.where(Shipment.status == status_filter)
        if created_by is not None:
            query = query.where(Shipment.created_by == created_by)

        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def count_distinct_clients(
        session: AsyncSession,
        created_by: Optional[int] = None,
    ) -> int:
        """Kamida 1 ta yuki bo'lgan mijozlar sonini hisoblash"""
        query = select(func.count(func.distinct(Shipment.client_id)))
        if created_by is not None:
            query = query.where(Shipment.created_by == created_by)
        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def count_by_status_all(
        session: AsyncSession,
        created_by: Optional[int] = None,
    ) -> dict:
        """Har bir status bo'yicha yuklar sonini qaytaradi"""
        query = select(Shipment.status, func.count(Shipment.id)).group_by(Shipment.status)
        if created_by is not None:
            query = query.where(Shipment.created_by == created_by)
        result = await session.execute(query)
        return {status: count for status, count in result.all()}


class GroupCategoryCRUD:
    """Guruh kategoriyalari CRUD"""

    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[GroupCategory]:
        """Faol kategoriyalarni olish"""
        result = await session.execute(
            select(GroupCategory)
            .where(GroupCategory.is_active == True)
            .order_by(GroupCategory.sort_order, GroupCategory.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(session: AsyncSession) -> List[GroupCategory]:
        """Barcha kategoriyalarni olish (aktiv + deaktiv)"""
        result = await session.execute(
            select(GroupCategory).order_by(GroupCategory.sort_order, GroupCategory.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(session: AsyncSession, category_id: int) -> Optional[GroupCategory]:
        result = await session.execute(
            select(GroupCategory).where(GroupCategory.id == category_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        name_uz: str,
        name_ru: str,
        name_tr: str,
        emoji: str = "📂",
        sort_order: int = 0,
    ) -> GroupCategory:
        category = GroupCategory(
            name_uz=name_uz,
            name_ru=name_ru,
            name_tr=name_tr,
            emoji=emoji,
            sort_order=sort_order,
        )
        session.add(category)
        await session.flush()
        return category


class GroupCRUD:
    """Group CRUD operations"""

    @staticmethod
    async def get_all_active(session: AsyncSession) -> List[Group]:
        """Faol guruhlarni olish"""
        result = await session.execute(
            select(Group)
            .where(Group.is_active == True)
            .order_by(Group.sort_order, Group.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(session: AsyncSession) -> List[Group]:
        """Barcha guruhlarni olish (aktiv va deaktiv)"""
        result = await session.execute(
            select(Group).order_by(Group.sort_order, Group.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_category(
        session: AsyncSession,
        category_id: int,
        active_only: bool = True,
    ) -> List[Group]:
        """Kategoriya bo'yicha guruhlarni olish"""
        query = select(Group).where(Group.category_id == category_id)
        if active_only:
            query = query.where(Group.is_active == True)
        query = query.order_by(Group.sort_order, Group.id)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_uncategorized_active(session: AsyncSession) -> List[Group]:
        """Kategoriyaga biriktirilmagan faol guruhlar (to'g'ridan-to'g'ri ko'rsatiladi)"""
        result = await session.execute(
            select(Group)
            .where(Group.category_id.is_(None), Group.is_active == True)
            .order_by(Group.sort_order, Group.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_category(
        session: AsyncSession,
        category_id: int,
        active_only: bool = True,
    ) -> int:
        """Kategoriyadagi guruhlar sonini hisoblash"""
        query = select(func.count(Group.id)).where(Group.category_id == category_id)
        if active_only:
            query = query.where(Group.is_active == True)
        result = await session.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_by_id(session: AsyncSession, group_id: int) -> Optional[Group]:
        """ID bo'yicha guruhni olish"""
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        name_uz: str,
        name_ru: str,
        name_tr: str,
        telegram_link: str,
        emoji: str,
        sort_order: int = 0,
        category_id: Optional[int] = None,
    ) -> Group:
        """Yangi guruh yaratish"""
        group = Group(
            name_uz=name_uz,
            name_ru=name_ru,
            name_tr=name_tr,
            telegram_link=telegram_link,
            emoji=emoji,
            sort_order=sort_order,
            category_id=category_id,
        )
        session.add(group)
        await session.flush()
        return group

    @staticmethod
    async def update(
        session: AsyncSession,
        group_id: int,
        **kwargs,
    ) -> Optional[Group]:
        """Guruhni yangilash"""
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()
        if group:
            for key, value in kwargs.items():
                if hasattr(group, key):
                    setattr(group, key, value)
            await session.flush()
        return group

    @staticmethod
    async def toggle_active(
        session: AsyncSession,
        group_id: int,
    ) -> Optional[Group]:
        """Guruhning faollik holatini o'zgartirish"""
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()
        if group:
            group.is_active = not group.is_active
            await session.flush()
        return group


class CompanyInfoCRUD:
    """CompanyInfo CRUD operations"""

    @staticmethod
    async def create(
        session: AsyncSession,
        address_uz: str,
        address_ru: str,
        address_tr: str,
        phone_numbers: list[str],
        telegram_account: str,
        working_hours: str,
        address_cn: str = "",
        phone_numbers_cn: list[str] = None,
    ) -> CompanyInfo:
        """Yangi kompaniya ma'lumotlarini yaratish"""
        if phone_numbers_cn is None:
            phone_numbers_cn = []
        info = CompanyInfo(
            address_uz=address_uz,
            address_ru=address_ru,
            address_tr=address_tr,
            address_cn=address_cn,
            phone_numbers=phone_numbers,
            phone_numbers_cn=phone_numbers_cn,
            telegram_account=telegram_account,
            working_hours=working_hours,
        )
        session.add(info)
        await session.flush()
        return info

    @staticmethod
    async def get(session: AsyncSession) -> Optional[CompanyInfo]:
        """Kompaniya ma'lumotlarini olish (yagona yozuv)"""
        result = await session.execute(
            select(CompanyInfo).order_by(CompanyInfo.id).limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(session: AsyncSession) -> CompanyInfo:
        """Kompaniya ma'lumotlarini olish yoki yangi yaratish"""
        info = await CompanyInfoCRUD.get(session)
        if not info:
            info = CompanyInfo(
                address_uz="",
                address_ru="",
                address_tr="",
                address_cn="",
                phone_numbers=[],
                phone_numbers_cn=[],
                telegram_account="",
                working_hours="",
            )
            session.add(info)
            await session.flush()
        return info

    @staticmethod
    async def update(
        session: AsyncSession,
        **kwargs,
    ) -> Optional[CompanyInfo]:
        """Kompaniya ma'lumotlarini yangilash"""
        info = await CompanyInfoCRUD.get(session)
        if info:
            for key, value in kwargs.items():
                if hasattr(info, key):
                    setattr(info, key, value)
            await session.flush()
        return info


# CRUD instance exports
client_crud = ClientCRUD()
shipment_crud = ShipmentCRUD()
group_crud = GroupCRUD()
group_category_crud = GroupCategoryCRUD()
company_info_crud = CompanyInfoCRUD()

# Helper function for shipment display
async def format_shipment_list(shipment_list, lang: str, i18n: Any) -> str:
    """
    Yuklar ro'yxatini formatlash (view uchun)

    Args:
        shipment_list: Yuklar ro'yxati
        lang: Til kodi
        i18n: i18n middleware obyekti

    Returns:
        Formatlang string
    """
    if not i18n:
        return ""

    # Status emoji map
    status_emoji_map = {
        "pending": "🕐",
        "in_transit": "🚚",
        "arrived": "📦",
        "ready": "✅",
        "delivered": "🎉",
    }

    # Yuklarni ro'yxati
    result_text = ""
    for idx, ship in enumerate(shipment_list, start=1):
        status_emoji = status_emoji_map.get(ship.status.value, "")
        client_name = ship.client.full_name if ship.client else "—"

        result_text += (
            f"{idx}. {status_emoji} <b>{client_name}</b>\n"
            f"📞 <b>{ship.client.phone_number if ship.client else '—'}</b>\n"
            f"📋 <b>{ship.description or '—'}</b>\n"
            f"⚖️ <b>{ship.weight_kg or '—'} kg</b> / 📦 <b>{ship.cargo_weight_kg or '—'} kg</b>\n"
            f"💰 <b>{ship.price or ''} {ship.currency or ''}</b>\n"
            f"📌 <b>{ship.status.value if ship.status else ''}</b>\n"
            f"📅 <b>{ship.created_at.strftime('%d.%m.%Y %H:%M') if ship.created_at else ''}</b>\n"
        )

    return result_text


# Helper functions
async def get_client_language(session: AsyncSession, telegram_id: int) -> Optional[str]:
    """Client tilini olish (i18n middleware uchun)"""
    client = await ClientCRUD.get_by_telegram_id(session, telegram_id)
    return client.language if client else None


async def update_client_language(telegram_id: int, language: str) -> None:
    """Client tilini yangilash (async session bilan)"""
    from database.database import get_session
    async with get_session() as session:
        await ClientCRUD.update_language(session, telegram_id, language)
        await session.commit()
