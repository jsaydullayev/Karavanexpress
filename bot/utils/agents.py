"""
Alohida klientlar (agentlar).

Agent nomidan yaratilgan Cargo ID lar:
  1. prefiks oladi — "MS48392" ko'rinishida darhol ko'rinib turadi;
  2. bazada `clients.agent_id` orqali aynan shu agentga biriktiriladi.

Yangi agent qo'shish uchun AGENTS ga bitta yozuv qo'shish kifoya —
qolgan hammasi (tugma, prefiks, biriktirish) avtomatik ishlaydi.
"""
from dataclasses import dataclass

from bot.utils.cargo_id_gen import PREFIX_MS


@dataclass(frozen=True)
class Agent:
    """Alohida klient — uning nomidan ID yaratish mumkin"""

    key: str  # callback_data uchun qisqa kalit
    full_name: str
    phone_number: str
    cargo_id_prefix: str


AGENTS: tuple[Agent, ...] = (
    Agent(
        key="ms",
        full_name="Ernazarov Ruslan",
        phone_number="+998941433344",
        cargo_id_prefix=PREFIX_MS,
    ),
)

AGENTS_BY_KEY: dict[str, Agent] = {agent.key: agent for agent in AGENTS}
AGENTS_BY_PREFIX: dict[str, Agent] = {agent.cargo_id_prefix: agent for agent in AGENTS}


def get_agent(key: str) -> Agent | None:
    """Kalit bo'yicha agentni olish"""
    return AGENTS_BY_KEY.get(key)


def get_agent_by_prefix(prefix: str) -> Agent | None:
    """Cargo ID prefiksi bo'yicha agentni olish ("MS" → Ernazarov Ruslan)"""
    if not prefix:
        return None
    return AGENTS_BY_PREFIX.get(prefix)
