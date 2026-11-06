# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026-10-22 12:00:00
# File:notice.py
import datetime

from typing import Union

from module.enums import NoticeType


class NoticeHub:
    """Collect download, upload, and forwarding completion notices for the web panel's Notices section."""

    NOTICES: list = []  # All notices; new ones are prepended so the web panel can display them in reverse chronological order.
    MAX_NOTICES_PER_TYPE: int = 500  # Retain up to 500 notices per type (1,500 total); discard the oldest of that type to prevent unbounded memory growth.
    OWNER_NAMES: dict = {}  # Creator ID -> display name, registered when a task is created for lookup without reparsing user details for each notice.

    @staticmethod
    def add_owner(owner: Union[int, str, None], user) -> None:
        """Register a task creator's display name for notice attribution."""
        if owner is None or user is None:
            return
        first_name: str = str(getattr(user, 'first_name', '') or '')
        last_name: str = str(getattr(user, 'last_name', '') or '')
        name: str = f'{first_name} {last_name}'.strip() or str(getattr(user, 'username', '') or '')
        if name:
            NoticeHub.OWNER_NAMES[str(owner)] = name

    @staticmethod
    def get_owner_name(owner: Union[int, str, None]) -> str:
        """Get a creator's display name, falling back to their ID if no name is registered."""
        if owner is None:
            return ''
        return NoticeHub.OWNER_NAMES.get(str(owner), str(owner))

    @staticmethod
    def trim() -> None:
        """Trim notices by type, retaining the latest MAX_NOTICES_PER_TYPE entries of each type independently."""
        counts: dict = {}
        kept: list = []
        for notice in NoticeHub.NOTICES:  # Newest notices are first, so later entries of an over-limit type are older and can be discarded.
            notice_type = notice.get('type')
            counts[notice_type] = counts.get(notice_type, 0) + 1
            if counts[notice_type] <= NoticeHub.MAX_NOTICES_PER_TYPE:
                kept.append(notice)
        NoticeHub.NOTICES[:] = kept

    @staticmethod
    def push(notice_type: str, text: str, owner: Union[int, None] = None) -> None:
        """Register a notice with its type, text, and task creator."""
        if not text:
            return
        NoticeHub.NOTICES.insert(0, {
            'type': notice_type,
            'text': str(text),
            'owner': owner,
            'owner_name': NoticeHub.get_owner_name(owner),
            'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        NoticeHub.trim()

    @staticmethod
    def snapshot() -> dict:
        """Return a copy of notices grouped by type for the web panel's Notices section."""
        result: dict = {notice_type: [] for notice_type in NoticeType()}
        for notice in list(NoticeHub.NOTICES):
            notice_type = notice.get('type')
            if notice_type in result:
                result[notice_type].append(notice)
        return result
