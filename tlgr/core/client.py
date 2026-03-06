"""Telethon client wrapper with optimized configuration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from telethon import TelegramClient, utils
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import User, Chat, Channel

from tlgr.core.errors import (
    AuthenticationError,
    SessionError,
    ConfigurationError,
    ChatNotFoundError,
    TlgrError,
)


def create_client(
    session_path: Path,
    api_id: int,
    api_hash: str,
) -> TelegramClient:
    return TelegramClient(
        str(session_path),
        api_id,
        api_hash,
        flood_sleep_threshold=120,
        request_retries=5,
        connection_retries=5,
        retry_delay=1,
        auto_reconnect=True,
        sequential_updates=True,
    )


class ClientWrapper:
    def __init__(self, session_path: Path, api_id: int, api_hash: str):
        self.session_path = session_path
        self.api_id = api_id
        self.api_hash = api_hash
        self._client: TelegramClient | None = None
        self._me: User | None = None

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise SessionError("Client not initialised. Call connect() first.")
        return self._client

    @property
    def me(self) -> User:
        if self._me is None:
            raise SessionError("Not logged in.")
        return self._me

    async def connect(self) -> bool:
        """Connect. Returns True if already authorised."""
        self._client = create_client(self.session_path, self.api_id, self.api_hash)
        await self._client.connect()
        if await self._client.is_user_authorized():
            self._me = await self._client.get_me()
            return True
        return False

    async def login(
        self,
        phone: str | None = None,
        code_callback=None,
        password_callback=None,
    ) -> User:
        if self._client is None:
            await self.connect()
        try:
            if phone is None:
                phone = input("Phone number (with country code): ").strip()
            await self._client.send_code_request(phone)  # type: ignore[union-attr]
            code = code_callback() if code_callback else input("Verification code: ").strip()
            try:
                await self._client.sign_in(phone, code)  # type: ignore[union-attr]
            except SessionPasswordNeededError:
                import getpass
                password = password_callback() if password_callback else getpass.getpass("2FA password: ")
                await self._client.sign_in(password=password)  # type: ignore[union-attr]
            self._me = await self._client.get_me()  # type: ignore[union-attr]
            return self._me
        except Exception as e:
            raise AuthenticationError(f"Login failed: {e}")

    async def logout(self) -> None:
        if self._client:
            try:
                await self._client.log_out()
            except Exception:
                pass
            await self._client.disconnect()
        self._client = None
        self._me = None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()

    async def resolve_chat(self, chat_ref: str) -> int:
        """Resolve @username or numeric id to peer id."""
        try:
            return int(chat_ref)
        except ValueError:
            pass
        if not chat_ref.startswith("@"):
            chat_ref = f"@{chat_ref}"
        try:
            entity = await self.client.get_entity(chat_ref)
            return utils.get_peer_id(entity)
        except Exception as e:
            raise ChatNotFoundError(f"Cannot resolve '{chat_ref}': {e}")

    async def list_chats(
        self,
        limit: int | None = None,
        chat_type: str | None = None,
        search: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        count = 0
        async for dialog in self.client.iter_dialogs():
            entity = dialog.entity
            info = self._entity_to_dict(entity, dialog)

            if chat_type:
                if info["type"].lower() != chat_type.lower():
                    continue
            if search:
                if search.lower() not in info["name"].lower():
                    continue

            yield info
            count += 1
            if limit and count >= limit:
                break

    def _entity_to_dict(self, entity: Any, dialog: Any = None) -> dict[str, Any]:
        if isinstance(entity, User):
            if entity.is_self:
                t, name = "saved", "Saved Messages"
            else:
                t = "bot" if entity.bot else "user"
                name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
            return {
                "id": dialog.id if dialog else entity.id,
                "name": name,
                "type": t,
                "username": entity.username,
            }
        elif isinstance(entity, Chat):
            return {
                "id": dialog.id if dialog else entity.id,
                "name": entity.title,
                "type": "group",
                "username": None,
            }
        elif isinstance(entity, Channel):
            t = "channel" if not entity.megagroup else "supergroup"
            return {
                "id": dialog.id if dialog else entity.id,
                "name": entity.title,
                "type": t,
                "username": entity.username,
            }
        return {
            "id": dialog.id if dialog else getattr(entity, "id", 0),
            "name": str(dialog.name) if dialog else str(entity),
            "type": "unknown",
            "username": None,
        }

    async def get_chat_info(self, chat_id: int | str) -> dict[str, Any]:
        entity = await self.client.get_entity(chat_id)
        return self._entity_to_dict(entity)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        silent: bool = False,
        file: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        if file:
            msg = await self.client.send_file(
                chat_id,
                file,
                caption=caption or text,
                reply_to=reply_to,
                silent=silent,
            )
        else:
            msg = await self.client.send_message(
                chat_id,
                text,
                reply_to=reply_to,
                silent=silent,
            )
        return {"id": msg.id, "chat_id": chat_id, "date": str(msg.date)}

    async def get_messages(
        self,
        chat_id: int | str,
        *,
        limit: int = 20,
        offset_id: int = 0,
        include_sender: bool = False,
        include_media: bool = False,
        include_reactions: bool = False,
        include_entities: bool = False,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        async for msg in self.client.iter_messages(chat_id, limit=limit, offset_id=offset_id):
            d: dict[str, Any] = {
                "id": msg.id,
                "date": str(msg.date),
                "text": msg.text or "",
            }
            if include_sender and msg.sender:
                d["sender"] = {
                    "id": msg.sender_id,
                    "name": getattr(msg.sender, "first_name", None) or getattr(msg.sender, "title", ""),
                    "username": getattr(msg.sender, "username", None),
                }
            if include_media and msg.media:
                d["media"] = {
                    "type": type(msg.media).__name__,
                    "has_file": hasattr(msg.media, "document") or hasattr(msg.media, "photo"),
                }
            if include_reactions and hasattr(msg, "reactions") and msg.reactions:
                d["reactions"] = str(msg.reactions)
            if include_entities and msg.entities:
                d["entities"] = [
                    {"type": type(e).__name__, "offset": e.offset, "length": e.length}
                    for e in msg.entities
                ]
            result.append(d)
        return result

    async def get_message(self, chat_id: int | str, msg_id: int) -> dict[str, Any]:
        msgs = await self.client.get_messages(chat_id, ids=[msg_id])
        if not msgs or msgs[0] is None:
            raise ChatNotFoundError(f"Message {msg_id} not found")
        msg = msgs[0]
        d: dict[str, Any] = {
            "id": msg.id,
            "date": str(msg.date),
            "text": msg.text or "",
        }
        if msg.sender:
            d["sender"] = {
                "id": msg.sender_id,
                "name": getattr(msg.sender, "first_name", None) or getattr(msg.sender, "title", ""),
                "username": getattr(msg.sender, "username", None),
            }
        if msg.media:
            d["media"] = {
                "type": type(msg.media).__name__,
            }
        if msg.entities:
            d["entities"] = [
                {"type": type(e).__name__, "offset": e.offset, "length": e.length}
                for e in msg.entities
            ]
        if hasattr(msg, "reactions") and msg.reactions:
            d["reactions"] = str(msg.reactions)
        if msg.reply_to:
            d["reply_to_msg_id"] = msg.reply_to.reply_to_msg_id
        if msg.forward:
            d["forward"] = True
        return d

    async def delete_messages(self, chat_id: int | str, msg_ids: list[int]) -> int:
        result = await self.client.delete_messages(chat_id, msg_ids, revoke=True)
        return getattr(result, "pts_count", len(msg_ids))

    async def search_messages(
        self,
        chat_id: int | str,
        query: str,
        *,
        limit: int = 20,
        local: bool = False,
        regex: str | None = None,
    ) -> list[dict[str, Any]]:
        import re as re_mod

        result: list[dict[str, Any]] = []
        if local:
            compiled = re_mod.compile(regex or query, re_mod.IGNORECASE) if (regex or query) else None
            async for msg in self.client.iter_messages(chat_id, limit=limit * 10):
                text = msg.text or ""
                if compiled and not compiled.search(text):
                    continue
                result.append({"id": msg.id, "date": str(msg.date), "text": text})
                if len(result) >= limit:
                    break
        else:
            async for msg in self.client.iter_messages(chat_id, search=query, limit=limit):
                result.append({"id": msg.id, "date": str(msg.date), "text": msg.text or ""})
        return result

    async def pin_message(self, chat_id: int | str, msg_id: int) -> dict[str, Any]:
        await self.client.pin_message(chat_id, msg_id)
        return {"pinned": True, "msg_id": msg_id}

    async def react_to_message(self, chat_id: int | str, msg_id: int, emoji: str) -> dict[str, Any]:
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        await self.client(SendReactionRequest(
            peer=chat_id,
            msg_id=msg_id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
        return {"reacted": True, "msg_id": msg_id, "emoji": emoji}

    async def create_chat(
        self,
        name: str,
        *,
        chat_type: str = "group",
        members: list[str] | None = None,
    ) -> dict[str, Any]:
        if chat_type == "channel":
            from telethon.tl.functions.channels import CreateChannelRequest
            result = await self.client(CreateChannelRequest(
                title=name,
                about="",
                megagroup=False,
            ))
            ch = result.chats[0]
            return {"id": utils.get_peer_id(ch), "name": name, "type": "channel"}
        else:
            users = members or []
            result = await self.client.create_group(name, users)
            return {"id": result.id if hasattr(result, "id") else 0, "name": name, "type": "group"}

    async def archive_chat(self, chat_id: int | str) -> dict[str, Any]:
        from telethon.tl.functions.folders import EditPeerFoldersRequest
        from telethon.tl.types import InputFolderPeer

        entity = await self.client.get_input_entity(chat_id)
        await self.client(EditPeerFoldersRequest([
            InputFolderPeer(peer=entity, folder_id=1)
        ]))
        return {"archived": True, "chat_id": chat_id}

    async def mute_chat(self, chat_id: int | str, duration: int | None = None) -> dict[str, Any]:
        from telethon.tl.functions.account import UpdateNotifySettingsRequest
        from telethon.tl.types import InputPeerNotifySettings, InputNotifyPeer

        entity = await self.client.get_input_entity(chat_id)
        mute_until = 2**31 - 1 if duration is None else int(asyncio.get_event_loop().time()) + duration
        await self.client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(peer=entity),
            settings=InputPeerNotifySettings(mute_until=mute_until),
        ))
        return {"muted": True, "chat_id": chat_id}

    async def leave_chat(self, chat_id: int | str) -> dict[str, Any]:
        entity = await self.client.get_entity(chat_id)
        if isinstance(entity, Channel):
            from telethon.tl.functions.channels import LeaveChannelRequest
            await self.client(LeaveChannelRequest(entity))
        elif isinstance(entity, Chat):
            from telethon.tl.functions.messages import DeleteChatUserRequest
            await self.client(DeleteChatUserRequest(entity.id, self.me.id))
        return {"left": True, "chat_id": chat_id}

    async def list_contacts(self) -> list[dict[str, Any]]:
        from telethon.tl.functions.contacts import GetContactsRequest
        result = await self.client(GetContactsRequest(hash=0))
        contacts: list[dict[str, Any]] = []
        for u in result.users:
            contacts.append({
                "id": u.id,
                "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
                "username": u.username,
                "phone": u.phone,
            })
        return contacts

    async def add_contact(self, phone: str, name: str = "") -> dict[str, Any]:
        from telethon.tl.functions.contacts import ImportContactsRequest
        from telethon.tl.types import InputPhoneContact

        parts = name.split(maxsplit=1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
        result = await self.client(ImportContactsRequest([
            InputPhoneContact(client_id=0, phone=phone, first_name=first, last_name=last)
        ]))
        imported = result.imported
        if imported:
            return {"added": True, "user_id": imported[0].user_id}
        return {"added": False, "error": "Could not import contact"}

    async def remove_contact(self, user_ref: str) -> dict[str, Any]:
        from telethon.tl.functions.contacts import DeleteContactsRequest
        entity = await self.client.get_entity(user_ref)
        await self.client(DeleteContactsRequest(id=[entity]))
        return {"removed": True}

    async def search_contacts(self, query: str) -> list[dict[str, Any]]:
        from telethon.tl.functions.contacts import SearchRequest
        result = await self.client(SearchRequest(q=query, limit=50))
        return [
            {
                "id": u.id,
                "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
                "username": u.username,
            }
            for u in result.users
        ]

    async def get_profile(self) -> dict[str, Any]:
        me = await self.client.get_me()
        return {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "username": me.username,
            "phone": me.phone,
            "bio": "",
        }

    async def update_profile(
        self,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        bio: str | None = None,
        photo: str | None = None,
    ) -> dict[str, Any]:
        from telethon.tl.functions.account import UpdateProfileRequest

        kwargs: dict[str, Any] = {}
        if first_name is not None:
            kwargs["first_name"] = first_name
        if last_name is not None:
            kwargs["last_name"] = last_name
        if bio is not None:
            kwargs["about"] = bio
        if kwargs:
            await self.client(UpdateProfileRequest(**kwargs))
        if photo:
            await self.client.upload_profile_photo(file=photo)
        return {"updated": True}

    async def download_media(
        self,
        chat_id: int | str,
        msg_id: int,
        *,
        out_dir: str | None = None,
    ) -> dict[str, Any]:
        from tlgr.core.config import get_downloads_dir

        msgs = await self.client.get_messages(chat_id, ids=[msg_id])
        if not msgs or msgs[0] is None:
            raise ChatNotFoundError(f"Message {msg_id} not found")
        msg = msgs[0]
        if not msg.media:
            raise TlgrError("Message has no media")
        dl_dir = Path(out_dir) if out_dir else get_downloads_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        path = await self.client.download_media(msg, file=str(dl_dir))
        return {"path": str(path), "msg_id": msg_id}

    async def upload_file(
        self,
        chat_id: int | str,
        file_path: str,
        *,
        caption: str = "",
    ) -> dict[str, Any]:
        msg = await self.client.send_file(chat_id, file_path, caption=caption)
        return {"id": msg.id, "chat_id": chat_id}
