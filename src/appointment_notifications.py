"""Patient-safe operational language for appointment image processing."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VariantDecision:
    status: str
    message: str


def notification_for(appointment_id: str, variants_ready: bool) -> VariantDecision:
    if variants_ready:
        return VariantDecision("ready_for_review", f"Appointment {appointment_id}: images are ready for review.")
    return VariantDecision("processing", f"Appointment {appointment_id}: image preparation is in progress.")
