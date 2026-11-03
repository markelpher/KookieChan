"""Formatos dos anúncios extraídos e persistidos na fila de publicação."""

from datetime import datetime
from typing import Literal, NotRequired, Required, TypedDict


class ParsedAnnouncement(TypedDict):
    title: str
    description: str
    date: datetime


class AnnouncementRecord(TypedDict):
    title: str
    description: str
    date: str
    id: NotRequired[int]
    delivery_status: NotRequired[Literal["pending", "sent"]]
    delivery_attempted_at: NotRequired[str | None]
    delivery_channel_id: NotRequired[int | None]
    delivery_message_id: NotRequired[int | None]
    delivered_at: NotRequired[str | None]


class DisplayAnnouncement(TypedDict):
    title: str
    description: str
    date: str


class NewAnnouncement(TypedDict):
    title: str
    description: str
    date: str


class PendingAnnouncement(AnnouncementRecord):
    id: Required[int]
    delivery_status: Required[Literal["pending"]]
    delivery_attempted_at: Required[str | None]
    delivery_channel_id: Required[int | None]


class DeliveryAnnouncement(TypedDict):
    id: int
