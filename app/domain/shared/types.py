"""Common types shared across domain modules.

Includes result wrappers, error types, and clock abstractions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass
class Ok(Generic[T]):
    value: T


@dataclass
class Err(Generic[E]):
    error: E


Result = Ok[T] | Err[E]


class DomainClock:
    """Abstract clock so domain logic stays testable."""

    def now(self) -> datetime:
        return datetime.utcnow()
