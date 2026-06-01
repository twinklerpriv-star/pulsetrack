# Base ORM model declaration und UTCDateTime TypeDecorator
#
# Datum: 31.05.2026 | Version: 1.1

from datetime import datetime

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class UTCDateTime(TypeDecorator):
    """
    Ein robuster DateTime-Type-Decorator, der sowohl datetime-Objekte als auch
    ISO-8601-Datumsstrings akzeptiert und sicher für SQLite konvertiert.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                raise ValueError(f"Ungueltiges Datumsformat: {value}")
        return value

    def process_result_value(self, value, dialect):
        return value
