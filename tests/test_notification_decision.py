from src.appointment_notifications import notification_for


def test_ready_images_send_a_patient_safe_review_notice() -> None:
    decision = notification_for("apt-42", variants_ready=True)

    assert decision.status == "ready_for_review"
    assert decision.message == "Appointment apt-42: images are ready for review."
    assert "diagnosis" not in decision.message.lower()
