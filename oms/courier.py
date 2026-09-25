"""Boundary for a future VERIFIED FDE adapter. No speculative network calls."""
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class Shipment:
    reference: str
    recipient_name: str
    phone: str
    address: str
    city: str
    description: str
    weight_g: int
    cod_cents: int

@dataclass(frozen=True)
class BookingReceipt:
    tracking: str
    official_waybill_pdf: bytes

class Courier(Protocol):
    def find_by_reference(self, reference: str) -> BookingReceipt:
        """Reconcile before retry. Unknown is NOT proof of absence."""
        ...

    def book(self, shipment: Shipment) -> BookingReceipt:
        ...

class FDEUnavailable:
    def find_by_reference(self, reference):
        raise RuntimeError('FDE lookup contract has not been verified.')

    def book(self, shipment):
        raise RuntimeError('FDE booking disabled until credentials and API contract are verified.')
