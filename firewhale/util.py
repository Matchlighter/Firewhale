
from functools import wraps
from typing import Dict, Generic, TypeVar, Set

T = TypeVar("T")
U = TypeVar("U")

class MultiMap(Generic[T, U]):
    def __init__(self) -> None:
        self._store: Dict[T, Set[U]] = {}

    def __getitem__(self, k: T) -> Set[U]:
        return self._store[k]

    def add(self, key: T, value: U) -> bool:
        """ Returns True if the key was not already in the map """
        ret = False
        if key not in self._store:
            self._store[key] = set()
            ret = True
        self._store[key].add(value)
        return ret

    def remove(self, key: T, value: U) -> bool:
        """ Returns True if the key was removed """
        if key not in self._store: return True
        self._store[key].discard(value)
        if len(self._store[key]) == 0:
            del self._store[key]
            return True
        return False


class BiMultiMap(Generic[T, U]):
    def __init__(self) -> None:
        self._left = MultiMap[T, U]()
        self._right = MultiMap[U, T]()

    def keys(self) -> Set[T]:
        return set(self._left._store.keys())

    def get_by_key(self, key: T) -> Set[U]:
        return self._left[key]

    def get_by_value(self, value: U) -> Set[T]:
        return self._right[value]

    def has_key(self, key: T) -> bool:
        return key in self._left._store

    def has_value(self, value: U) -> bool:
        return value in self._right._store

    def add(self, key: T, value: U) -> bool:
        """ Returns True if the key was not already in the map """
        self._right.add(value, key)
        return self._left.add(key, value)

    def remove(self, key: T, value: U) -> bool:
        """ Returns True if the key was removed """
        self._right.remove(value, key)
        return self._left.remove(key, value)


def protected(message):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                func(*args, **kwargs)
            except Exception as e:
                print(f"{message}: {e}")
        return wrapper
    return decorator
