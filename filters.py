from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


DISTANCE_RE = re.compile(r"(#\w+USDT):\s*([+-]?[0-9]+(?:[.,][0-9]+)?)%")


@dataclass(frozen=True)
class ParsedSignal:
    coin: str
    distance: float


def parse_distance(text: str) -> ParsedSignal | None:
    match = DISTANCE_RE.search(text)
    if not match:
        return None
    coin = match.group(1)
    distance_raw = match.group(2).replace(",", ".")
    try:
        distance = float(distance_raw)
    except ValueError:
        return None
    return ParsedSignal(coin=coin, distance=distance)


def format_notification(
    *,
    min_distance: float,
    coin: str,
    distance: float,
    source_title: str,
    chat_id: int | str,
    timestamp: datetime,
    link: str | None,
    original_text: str,
    msg_id: int,
) -> str:
    local_time = timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    link_part = link or f"chat_id={chat_id} msg_id={msg_id}"
    abs_distance = abs(distance)
    return "\n".join(
        [
            f"⚡️ FILTERED SIGNAL (>= {min_distance}%)",
            f"Coin: {coin}",
            f"Distance: {distance:.3f}%",
            f"AbsDistance: {abs_distance:.3f}%",
            f"Source: {source_title} (chat_id={chat_id})",
            f"Local time: {local_time}",
            f"Link: {link_part}",
            "",
            original_text.strip(),
        ]
    )
