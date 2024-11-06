
from threading import Lock
from typing import Literal


class NftError(Exception):
    pass


class NFTBackend:
    def __init__(self):
        self._lock = Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()

    def cmd(self, cmd, *, throw: bool | Literal["continue"] = True):
        raise NotImplementedError()
