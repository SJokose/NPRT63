from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime
from core.models import Appointment
from core.utils import send_sms_reminder


class Command(BaseCommand):
    help = 'Send SMS reminders at 72h, 24h, and 2h before confirmed appointments'

    def handle(self, *args, **options):
        now = timezone.now()
        total_sent = 0

        cutoff = now + timedelta(hours=73)
        upcoming = Appointment.objects.filter(
            status='confirmed',
            appointment_date__gte=now.date(),
            appointment_date__lte=cutoff.date(),
        )

        for appt in upcoming:
            appt_dt = timezone.make_aware(
                datetime.combine(appt.appointment_date, appt.appointment_time)
            )
            hours_until = (appt_dt - now).total_seconds() / 3600

            # 72h reminder
            if 71 <= hours_until <= 73 and not appt.reminder_sent_72h:
                msg = (
                    f"MediSync SA: Reminder - appointment with "
                    f"{appt.doctor.get_doctor_display} on {appt.appointment_date} "
                    f"at {appt.appointment_time}."
                )
                if send_sms_reminder(appt.patient.phone_number, msg):
                    appt.reminder_sent_72h = True
                    appt.save(update_fields=['reminder_sent_72h'])
                    total_sent += 1
                    self.stdout.write(f"Sent 72h reminder -> {appt.patient.get_full_name()}")

            # 24h reminder
            if 23 <= hours_until <= 25 and not appt.reminder_sent_24h:
                msg = (
                    f"MediSync SA: Reminder - appointment TOMORROW at "
                    f"{appt.appointment_time} with {appt.doctor.get_doctor_display}."
                )
                if send_sms_reminder(appt.patient.phone_number, msg):
                    appt.reminder_sent_24h = True
                    appt.save(update_fields=['reminder_sent_24h'])
                    total_sent += 1
                    self.stdout.write(f"Sent 24h reminder -> {appt.patient.get_full_name()}")

            # 2h reminder
            if 1.5 <= hours_until <= 2.5 and not appt.reminder_sent_2h:
                msg = (
                    f"MediSync SA: Reminder - appointment with "
                    f"{appt.doctor.get_doctor_display} in 2 HOURS at "
                    f"{appt.appointment_time}."
                )
                if send_sms_reminder(appt.patient.phone_number, msg):
                    appt.reminder_sent_2h = True
                    appt.save(update_fields=['reminder_sent_2h'])
                    total_sent += 1
                    self.stdout.write(f"Sent 2h reminder -> {appt.patient.get_full_name()}")

        self.stdout.write(self.style.SUCCESS(f'Total reminders sent: {total_sent}'))