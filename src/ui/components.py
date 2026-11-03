"""Construção de interfaces nativas Discord Components V2."""

from dataclasses import dataclass, field
from typing import Any

import discord


@dataclass(frozen=True)
class PanelContent:
    # Dados semânticos usados diretamente para compor um painel nativo V2.

    title: str
    description: str = ""
    sections: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    accent_color: int | None = None
    footer: str | None = None
    url: str | None = None
    thumbnail: str | None = None


def _text_chunks(text, *, limit=12000, chunk_size=4000):
    text = text[:limit] or "\u200b"
    return [
        text[index : index + chunk_size] for index in range(0, len(text), chunk_size)
    ]


class Panel(discord.ui.LayoutView):
    # Layout V2 com conteúdo declarativo e controles interativos.

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Coleta os controles declarados com os decoradores do discord.py.
        for base in reversed(cls.__mro__):
            for name, member in base.__dict__.items():
                if hasattr(member, "__discord_ui_model_type__"):
                    cls.__view_children_items__[name] = member

    def __init__(self, *, timeout=180):
        super().__init__(timeout=timeout)
        # Controles devem ficar em ActionRows no layout Components V2.
        controls = list(self.children)
        for control in controls:
            self.remove_item(control)
            self.add_item(control)

    def add_item(self, item):
        if isinstance(item, (discord.ui.Button, discord.ui.Select)):
            return super().add_item(discord.ui.ActionRow(item))
        return super().add_item(item)

    def set_content(self, content: PanelContent, mention=None):
        if not isinstance(content, PanelContent):
            raise TypeError("set_content espera PanelContent.")
        if hasattr(self, "_content_container"):
            self.remove_item(self._content_container)

        title = f"[{content.title}]({content.url})" if content.url else content.title
        header = discord.ui.TextDisplay(f"# {title}")
        children: list[discord.ui.Item[Any]] = [header]
        body_parts = []
        if mention:
            body_parts.append(mention)
        if content.description:
            body_parts.append(content.description)
        for heading, value in content.sections:
            body_parts.append(f"**{heading}**\n{value}")
        if content.footer:
            body_parts.append(f"-# {content.footer}")

        body = "\n\n".join(body_parts)
        if body:
            children.append(
                discord.ui.Separator(spacing=discord.SeparatorSpacing.small)
            )
            if content.thumbnail and content.description:
                children.append(
                    discord.ui.Section(
                        discord.ui.TextDisplay(content.description),
                        accessory=discord.ui.Thumbnail(
                            content.thumbnail, description=content.title
                        ),
                    )
                )
                body = "\n\n".join(
                    [f"**{heading}**\n{value}" for heading, value in content.sections]
                    + ([f"-# {content.footer}"] if content.footer else [])
                )
            if body:
                children.extend(
                    discord.ui.TextDisplay(chunk) for chunk in _text_chunks(body)
                )

        self._content_container = discord.ui.Container(
            *children, accent_color=content.accent_color
        )
        controls = list(self.children)
        for control in controls:
            self.remove_item(control)
        self.add_item(self._content_container)
        for control in controls:
            self.add_item(control)
        return self


def panel(content: PanelContent, mention=None):
    return Panel(timeout=None).set_content(content, mention)


def message_contains_title(message, title):
    def contains(component):
        if title in getattr(component, "content", ""):
            return True
        return any(contains(child) for child in getattr(component, "children", ()))

    return any(contains(component) for component in message.components)


async def edit_panel(message, view):
    # Atualiza uma mensagem Components V2 sem disparar menções.
    return await message.edit(
        view=view, allowed_mentions=discord.AllowedMentions.none()
    )
