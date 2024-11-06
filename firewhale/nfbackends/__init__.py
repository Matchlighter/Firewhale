
from contextlib import contextmanager
from threading import Lock, local
from typing import List

from .base import NFTBackend


class NFTBackendStore:
    def __init__(self):
        self._list_lock = Lock()
        self._local = local()
        self.global_backends = []

    def __iter__(self):
        return iter(self.get_backends())

    def get_backends(self) -> List[NFTBackend]:
        with self._list_lock:
            return list(self.global_backends)

    # def register_backend(self, backend: NFTBackend):
    #     with self._list_lock:
    #         self.global_backends.append(backend)

    # def unregister_backend(self, backend: NFTBackend):
    #     with self._list_lock:
    #         self.global_backends.remove(backend)

    def set_backend(self, backend: NFTBackend):
        self.global_backends = [backend]

    @property
    def connected(self):
        return bool(self.global_backends) or bool(getattr(self._local, "current_backend", None))

    @property
    def current_backend(self):
        return getattr(self._local, "current_backend", None) or self.global_backends[0]

    @contextmanager
    def with_backend(self, backend: NFTBackend):
        self._local.current_backend = backend

nf_backend_store = NFTBackendStore()
