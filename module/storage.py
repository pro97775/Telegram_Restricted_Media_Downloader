# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026-10-13 12:05:00
# File:storage.py
import os
import time
import sqlite3
import asyncio

from abc import (
    ABC,
    abstractmethod
)
from dataclasses import dataclass
from typing import (
    Union,
    List,
    Dict,
    Tuple
)

from module import log
from module.language import _t
from module.path_tool import safe_delete
from module.enums import (
    DownloadStatus,
    KeyWord
)


class StorageType:
    """Types of database records."""
    DOWNLOAD: str = 'download'  # Download record.
    UPLOAD: str = 'upload'  # Upload record.


@dataclass
class TRMDStorage:
    """Web panel download/upload record; each field maps to a database column."""
    storage_type: str = StorageType.DOWNLOAD  # Record type: download or upload.
    chat_id: Union[str, int, None] = None  # Channel ID: source for downloads, destination for uploads.
    chat_name: str = ''  # Channel title; the display falls back to the channel ID when empty.
    message_id: Union[int, None] = None  # Message ID; may be empty for upload records.
    file_name: str = ''  # File name.
    file_path: str = ''  # File save path; checked in real time when reading records.
    file_size: int = 0  # File size in bytes.
    file_type: str = ''  # Media type, e.g. video or photo.
    status: str = ''  # Final status: success, skip, or failure.
    error_msg: str = ''  # Failure reason; empty for non-failure records.
    link: str = ''  # Download link; may be empty for upload records.
    create_time: int = 0  # Creation time, Unix timestamp in seconds.
    finish_time: int = 0  # Completion time, Unix timestamp in seconds.
    storage_id: Union[int, None] = None  # Database auto-increment ID, populated after a successful write.


class StorageDatabase(ABC):
    """Abstract database class for web download/upload records.

    To switch databases later, add an implementation and adjust the return value of
    build_storage_database; the downloader, uploader, and web panel need no changes.
    """

    @abstractmethod
    async def open(self) -> bool:
        """Open the database and create its tables.

        Returns:
            bool: True on success. On failure, only log the error; record storage
                becomes unavailable but downloads and uploads are unaffected.
        """
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Close the database."""
        raise NotImplementedError

    @abstractmethod
    async def add_storage(self, storage: TRMDStorage) -> bool:
        """Write one record.

        Args:
            storage: Record to write; storage_id is populated after a successful write.

        Returns:
            bool: True on success. On failure, only log the error; the main workflow is unaffected.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_storages(
            self,
            storage_type: Union[str, None] = None
    ) -> List[TRMDStorage]:
        """Read records, optionally checking that their files still exist first.

        Validation is handled by the implementation: only stat each parent directory;
        when its mtime is unchanged, do not stat its files individually. Run all blocking
        stat calls in a thread pool so the event loop remains responsive; throttle through
        an internal gate when directories are highly dispersed. This keeps read cost from
        growing linearly with the number of records and minimizes disk I/O.
        Return all records whose files still exist. The frontend handles pagination by
        channel, so this method does not limit the number of records.

        Args:
            storage_type: Record type; when empty, return all records.

        Returns:
            List[TRMDStorage]: Records whose files still exist, ordered from newest to oldest by write time.
        """
        raise NotImplementedError

    @abstractmethod
    async def update_chat_names(self, chat_names: Dict[str, str]) -> bool:
        """Fill in channel titles in batches by channel ID and return whether it succeeded.

        If another process has populated the ChatInfo cache while records are being read,
        write those titles back to the database so historical records that missed the
        cache when written do not keep displaying only the channel ID.

        Args:
            chat_names: Channel ID -> channel title; only fill records whose database title is empty.
        """
        raise NotImplementedError


class SqliteStorageDatabase(StorageDatabase):
    """sqlite3-based database implementation, organized similarly to pyrogram's SQLiteStorage."""

    STORAGE_NAME: str = 'TRMDStorage'  # Storage database filename without the extension; kept in the session directory.
    FILE_EXTENSION: str = '.db'  # Record database extension, distinct from Telegram's .session files.
    TABLE_NAME: str = 'web_storages'  # Record table name.
    COLUMNS: tuple = (
        'storage_id',
        'storage_type',
        'chat_id',
        'chat_name',
        'message_id',
        'file_name',
        'file_path',
        'file_size',
        'file_type',
        'status',
        'error_msg',
        'link',
        'create_time',
        'finish_time'
    )  # All record table columns; queries read them in this order to match the schema.
    # language=SQLite
    STORAGE_SCHEMA: str = '''
        CREATE TABLE IF NOT EXISTS web_storages
        (
            storage_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            storage_type TEXT    NOT NULL,
            chat_id     TEXT,
            chat_name   TEXT,
            message_id  INTEGER,
            file_name   TEXT,
            file_path   TEXT    NOT NULL,
            file_size   INTEGER NOT NULL DEFAULT 0,
            file_type   TEXT,
            status      TEXT,
            error_msg   TEXT,
            link        TEXT,
            create_time INTEGER NOT NULL DEFAULT 0,
            finish_time INTEGER NOT NULL DEFAULT 0
        );
    '''
    SWEEP_BATCH_SIZE: int = 500  # Files checked per existence-validation batch; yield to the event loop between batches.
    SWEEP_TTL: float = 15.0  # Minimum interval between checks when directories are highly dispersed, in seconds.
    SWEEP_TTL_THRESHOLD: int = 200  # Enable SWEEP_TTL throttling when the number of parent directories exceeds this value.
    DIR_CONFIRM_TIMES: int = 2  # Consecutive confirmations required before discarding a missing directory, preventing false deletion during brief network-drive outages.
    FULL_CHECK_INTERVAL: float = 1800.0  # Force a full check at least this often even if directory mtimes are unchanged, to account for timestamp granularity.
    DELETE_CHUNK_SIZE: int = 900  # Record IDs per DELETE statement, staying below SQLite's variable limit.

    def __init__(self, work_directory: str):
        self.name: str = SqliteStorageDatabase.STORAGE_NAME
        self.work_directory: str = work_directory
        self.storage_path: str = os.path.join(
            self.work_directory,
            self.name + self.FILE_EXTENSION
        )
        self._conn: Union[sqlite3.Connection, None] = None
        self._dir_mtime: Dict[str, float] = {}  # Parent directory -> last observed mtime; skip its files if unchanged.
        self._dir_checked_at: Dict[str, float] = {}  # Parent directory -> monotonic time of its last full file check.
        self._dir_missing: Dict[str, int] = {}  # Parent directory -> consecutive missing confirmations.
        self._last_sweep_at: float = 0.0  # Monotonic time of the last check, used for adaptive throttling.

    @property
    def conn(self) -> sqlite3.Connection:
        # As in pyrogram, accessing the connection before open() raises immediately,
        # avoiding repeated null checks in every method.
        if self._conn is None:
            msg = '`SqliteStorageDatabase.conn` accessed before `open()`'
            raise RuntimeError(msg)

        return self._conn

    @conn.setter
    def conn(self, value: Union[sqlite3.Connection, None]) -> None:
        self._conn = value

    async def open(self) -> bool:
        """Open the record database and create its tables; delete and recreate a corrupted file to keep the database feature available."""
        try:
            os.makedirs(self.work_directory, exist_ok=True)
        except Exception as e:
            log.error(f'Failed to create the session directory "{self.work_directory}", {_t(KeyWord.REASON)}: "{e}"')
            return False
        recreated: bool = False
        while True:
            try:
                self.conn = sqlite3.connect(self.storage_path, timeout=1, check_same_thread=False)
                self.conn.execute('PRAGMA journal_mode=DELETE')
                await self.create()
                break
            except sqlite3.DatabaseError as e:
                await self.close()
                if recreated:
                    log.error(f'Failed to open database "{self.storage_path}", {_t(KeyWord.REASON)}: "{e}"')
                    return False
                # If the record database is corrupted (for example, modified by another tool),
                # delete and recreate it; give up on record storage if recreation also fails.
                recreated = True
                log.warning(f'Database "{self.storage_path}" is corrupted and will be deleted and recreated. {_t(KeyWord.REASON)}: "{e}"')
                safe_delete(self.storage_path)
            except Exception as e:
                log.error(f'Failed to open database, {_t(KeyWord.REASON)}: "{e}"')
                await self.close()
                return False
        log.info(f'Database path: "{self.storage_path}".')
        return True

    async def close(self) -> None:
        """Close the record database."""
        conn: Union[sqlite3.Connection, None] = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception as e:
            log.warning(f'Failed to close database, {_t(KeyWord.REASON)}: "{e}"')

    async def create(self) -> None:
        """Create the table; this is safe to repeat and has no effect if the table already exists."""
        with self.conn:
            self.conn.executescript(self.STORAGE_SCHEMA)

    async def add_storage(self, storage: TRMDStorage) -> bool:
        """Write one record, populate storage_id on success, and use the current time for missing timestamps.

        Keep only one record per file (record type + file path): update the existing
        record on a duplicate download, successful retry, or rescan instead of inserting
        another row, preventing duplicate entries for the same file.
        """
        if not storage.file_path:
            log.warning(f'Database record has no file path; refusing to write "{storage.file_name}".')
            return False
        now: int = int(time.time())
        storage.create_time = storage.create_time or now
        storage.finish_time = storage.finish_time or now
        try:
            with self.conn:
                cursor = self.conn.execute(
                    f'SELECT storage_id, status FROM {self.TABLE_NAME} '
                    'WHERE storage_type = ? AND file_path = ? '
                    'ORDER BY storage_id DESC LIMIT 1',
                    (
                        storage.storage_type,
                        storage.file_path
                    )
                )
                row: Union[tuple, None] = cursor.fetchone()
                if row is not None:
                    storage.storage_id = row[0]
                    # For an existing record of the same file, update only when its status
                    # meaningfully changes (for example, a failed item succeeds on retry).
                    # Leave the record untouched when the status is unchanged or the item
                    # is skipped because the file already exists, preserving successful
                    # records and their historical timestamps during rescans.
                    if storage.status != DownloadStatus.SKIP and row[1] != storage.status:
                        self.conn.execute(
                            f'UPDATE {self.TABLE_NAME} '
                            'SET status = ?, error_msg = ?, finish_time = ? WHERE storage_id = ?',
                            (
                                storage.status,
                                storage.error_msg,
                                storage.finish_time,
                                storage.storage_id
                            )
                        )
                    return True
                cursor = self.conn.execute(
                    f'INSERT INTO {self.TABLE_NAME} '
                    '(storage_type, chat_id, chat_name, message_id, file_name, file_path, '
                    'file_size, file_type, status, error_msg, link, create_time, finish_time) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        storage.storage_type,
                        str(storage.chat_id) if storage.chat_id is not None else None,
                        storage.chat_name,
                        storage.message_id,
                        storage.file_name,
                        storage.file_path,
                        storage.file_size,
                        storage.file_type,
                        storage.status,
                        storage.error_msg,
                        storage.link,
                        storage.create_time,
                        storage.finish_time
                    )
                )
                storage.storage_id = cursor.lastrowid
            return True
        except Exception as e:
            log.warning(f'Failed to write to database, {_t(KeyWord.REASON)}: "{e}"')
            return False

    async def get_storages(
            self,
            storage_type: Union[str, None] = None
    ) -> List[TRMDStorage]:
        """Read records, checking for existence as needed so the returned results are validated.

        Return all records whose files still exist. The frontend handles pagination and
        grouping by channel, so this method does not truncate the results.
        """
        await self.__sweep_missing()
        try:
            query: str = f'SELECT {", ".join(self.COLUMNS)} FROM {self.TABLE_NAME}'
            params: tuple = ()
            if storage_type:
                query += ' WHERE storage_type = ?'
                params = (storage_type,)
            query += ' ORDER BY storage_id DESC'
            rows: list = self.conn.execute(query, params).fetchall()
        except Exception as e:
            log.warning(f'Failed to read database, {_t(KeyWord.REASON)}: "{e}"')
            return []
        return [self.__build_storage(row) for row in rows]

    async def __sweep_missing(self) -> int:
        """Check whether files referenced by records still exist, remove invalid records, and return the number removed.

        Directory-mtime shortcut: adding, removing, or renaming a file updates its parent
        directory's mtime, so stat only parent directories on each pass. If an mtime is
        unchanged, do not stat the files in that directory individually. Run all blocking
        stat calls in a thread pool. When directories are highly dispersed (the parent
        directory count exceeds the threshold), throttle checks with SWEEP_TTL to avoid
        checking individual files too frequently.
        """
        if self._conn is None:
            return 0
        try:
            rows: List[tuple] = self.conn.execute(
                f'SELECT storage_id, file_path FROM {self.TABLE_NAME}'
            ).fetchall()
        except Exception as e:
            log.warning(f'Failed to read database, {_t(KeyWord.REASON)}: "{e}"')
            return 0
        dirs: Dict[str, List[tuple]] = {}  # Parent directory -> [(storage_id, file_path), ...]
        missing_ids: List[int] = []  # IDs of records immediately deemed invalid (records without paths should not exist).
        for storage_id, file_path in rows:
            if not file_path:
                missing_ids.append(storage_id)
                continue
            dirs.setdefault(os.path.dirname(file_path), []).append((storage_id, file_path))
        # Adaptive gate: check on every read when there are few directories (one stat per
        # directory); throttle checks when directories are highly dispersed.
        if len(dirs) > self.SWEEP_TTL_THRESHOLD:
            if time.monotonic() - self._last_sweep_at < self.SWEEP_TTL:
                return 0
        self._last_sweep_at = time.monotonic()
        loop = asyncio.get_running_loop()
        for parent, items in dirs.items():
            stat_result: Union[Tuple[float, bool], None] = await loop.run_in_executor(
                None, self.__stat_dir, parent)
            if stat_result is None:
                # Do not delete a missing directory immediately: require DIR_CONFIRM_TIMES
                # consecutive confirmations to avoid false deletion during network-drive blips.
                confirmed: int = self._dir_missing.get(parent, 0) + 1
                if confirmed >= self.DIR_CONFIRM_TIMES:
                    self._dir_missing.pop(parent, None)
                    self._dir_mtime.pop(parent, None)
                    self._dir_checked_at.pop(parent, None)
                    missing_ids.extend(storage_id for storage_id, _ in items)
                else:
                    self._dir_missing[parent] = confirmed
                continue
            self._dir_missing.pop(parent, None)
            mtime, full_check_due = stat_result
            if not full_check_due and self._dir_mtime.get(parent) == mtime:
                continue  # The directory is unchanged, so its files need no individual checks.
            self._dir_mtime[parent] = mtime
            self._dir_checked_at[parent] = time.monotonic()
            # The directory changed (or it is time for a full check): validate its files
            # in batches, yielding to the event loop between batches.
            for start in range(0, len(items), self.SWEEP_BATCH_SIZE):
                batch: List[tuple] = items[start:start + self.SWEEP_BATCH_SIZE]
                missing_ids.extend(
                    await loop.run_in_executor(None, self.__stat_files, batch)
                )
        if missing_ids:
            self.__remove_storages(storage_ids=missing_ids)
            log.info(f'Discarded {len(missing_ids)} database record(s) whose files no longer exist.')
        return len(missing_ids)

    def __stat_dir(self, parent: str) -> Union[Tuple[float, bool], None]:
        """Stat a parent directory and return (mtime, whether a full check is due); return None if it is inaccessible."""
        try:
            mtime: float = os.stat(parent).st_mtime
        except OSError:
            return None
        checked_at: float = self._dir_checked_at.get(parent, 0.0)
        due: bool = (time.monotonic() - checked_at) >= self.FULL_CHECK_INTERVAL
        return mtime, due

    @staticmethod
    def __stat_files(batch: List[tuple]) -> List[int]:
        """Check a batch of files and return the IDs of records whose files do not exist."""
        return [storage_id for storage_id, file_path in batch if not os.path.isfile(file_path)]

    async def update_chat_names(self, chat_names: Dict[str, str]) -> bool:
        """Fill in channel titles in batches by channel ID, updating only empty database titles."""
        if not chat_names:
            return True
        try:
            with self.conn:
                self.conn.executemany(
                    f'UPDATE {self.TABLE_NAME} SET chat_name = ? '
                    f'WHERE chat_id = ? AND (chat_name IS NULL OR chat_name = \'\')',
                    [(title, chat_id) for chat_id, title in chat_names.items()]
                )
            return True
        except Exception as e:
            log.warning(f'Failed to backfill channel titles in the database, {_t(KeyWord.REASON)}: "{e}"')
            return False

    def __remove_storages(self, storage_ids: List[int]) -> bool:
        """Delete records in batches by ID, splitting them into chunks to stay below SQLite's variable limit."""
        try:
            for start in range(0, len(storage_ids), self.DELETE_CHUNK_SIZE):
                chunk: List[int] = storage_ids[start:start + self.DELETE_CHUNK_SIZE]
                placeholders: str = ', '.join('?' for _ in chunk)
                with self.conn:
                    self.conn.execute(
                        f'DELETE FROM {self.TABLE_NAME} WHERE storage_id IN ({placeholders})',
                        tuple(chunk)
                    )
            return True
        except Exception as e:
            log.warning(f'Failed to delete database records, {_t(KeyWord.REASON)}: "{e}"')
            return False

    @staticmethod
    def __build_storage(row: tuple) -> TRMDStorage:
        """Convert a database row into a record object."""
        data: dict = dict(zip(SqliteStorageDatabase.COLUMNS, row))
        return TRMDStorage(
            storage_type=data.get('storage_type') or '',
            chat_id=data.get('chat_id'),
            chat_name=data.get('chat_name') or '',
            message_id=data.get('message_id'),
            file_name=data.get('file_name') or '',
            file_path=data.get('file_path') or '',
            file_size=int(data.get('file_size') or 0),
            file_type=data.get('file_type') or '',
            status=data.get('status') or '',
            error_msg=data.get('error_msg') or '',
            link=data.get('link') or '',
            create_time=int(data.get('create_time') or 0),
            finish_time=int(data.get('finish_time') or 0),
            storage_id=data.get('storage_id')
        )


def build_storage_database(work_directory: str) -> StorageDatabase:
    """Construct the database.

    Args:
        work_directory: Directory for the record database; uses Telegram's session directory.

    Returns:
        StorageDatabase: By default, returns the sqlite3-based implementation, organized similarly to pyrogram's SQLiteStorage.
    """
    return SqliteStorageDatabase(work_directory=work_directory)
