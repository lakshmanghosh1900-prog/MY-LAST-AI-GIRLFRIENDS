"""Transactional append-only budget reservations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .storage import Database, utc_now


def month_bucket() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def estimate_usd_micros(input_tokens: int, output_tokens: int, input_price: Decimal, output_price: Decimal) -> int:
    value = (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / Decimal(1_000_000)
    return int((value * Decimal(1_000_000)).to_integral_value())


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    amount_usd_micros: int
    accepted: bool
    reason: str


class BudgetLedger:
    def __init__(self, db: Database, monthly_limit_usd_micros: int):
        self.db = db
        self.monthly_limit_usd_micros = monthly_limit_usd_micros

    def reserve(self, task_id: str, amount_usd_micros: int, key: str) -> Reservation:
        bucket = month_bucket()
        with self.db.transaction():
            existing = self.db.connection.execute(
                "SELECT reservation_id, amount_usd_micros FROM budget_events WHERE idempotency_key = ?",
                (f"reserve:{key}",),
            ).fetchone()
            if existing:
                return Reservation(existing["reservation_id"], int(existing["amount_usd_micros"]), True, "idempotent-existing")
            rejected = self.db.connection.execute(
                "SELECT 1 FROM budget_events WHERE idempotency_key = ?",
                (f"reject:{key}",),
            ).fetchone()
            if rejected:
                return Reservation("none", 0, False, "monthly budget would be exceeded")
            current = self.db.month_usage(bucket)
            if amount_usd_micros < 0 or current + amount_usd_micros > self.monthly_limit_usd_micros:
                self.db.connection.execute(
                    "INSERT INTO budget_events(id, task_id, reservation_id, event_type, amount_usd_micros, bucket_month, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (self.db.new_id(), task_id, "none", "rejected", 0, bucket, f"reject:{key}", utc_now()),
                )
                return Reservation("none", 0, False, "monthly budget would be exceeded")
            reservation_id = self.db.new_id()
            self.db.connection.execute(
                "INSERT INTO budget_events(id, task_id, reservation_id, event_type, amount_usd_micros, bucket_month, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.db.new_id(), task_id, reservation_id, "reserve", amount_usd_micros, bucket, f"reserve:{key}", utc_now()),
            )
            return Reservation(reservation_id, amount_usd_micros, True, "reserved")

    def settle(self, task_id: str, reservation: Reservation, actual_usd_micros: int, key: str) -> None:
        if not reservation.accepted:
            return
        actual = max(0, int(actual_usd_micros))
        delta = actual - reservation.amount_usd_micros
        with self.db.transaction():
            existing = self.db.connection.execute(
                "SELECT 1 FROM budget_events WHERE idempotency_key = ?", (f"settle:{key}",)
            ).fetchone()
            if existing:
                return
            self.db.connection.execute(
                "INSERT INTO budget_events(id, task_id, reservation_id, event_type, amount_usd_micros, bucket_month, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.db.new_id(), task_id, reservation.reservation_id, "settle", delta, month_bucket(), f"settle:{key}", utc_now()),
            )

    def usage_usd_micros(self) -> int:
        return self.db.month_usage(month_bucket())
