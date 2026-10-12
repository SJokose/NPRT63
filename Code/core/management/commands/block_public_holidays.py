import holidays
from datetime import date, time, datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import connection
from core.models import User


class Command(BaseCommand):
    help = 'Block all South African public holidays for every active doctor.'

    def add_arguments(self, parser):
        parser.add_argument('--start-year', type=int, default=date.today().year)
        parser.add_argument('--end-year', type=int, default=date.today().year + 5)
        parser.add_argument('--reason', type=str, default='Public Holiday')

    def handle(self, *args, **options):
        start_year = options['start_year']
        end_year = options['end_year']
        reason = options['reason']

        za_holidays = holidays.SouthAfrica(years=range(start_year, end_year + 1))
        doctors = User.objects.filter(role='doctor', is_active=True)
        today = date.today()

        # Build list of 30-min slots 09:00–17:00
        slots = []
        cur_dt = datetime.combine(today, time(9, 0))
        end_dt = datetime.combine(today, time(17, 0))
        while cur_dt <= end_dt:
            slots.append(cur_dt.time())
            cur_dt += timedelta(minutes=30)

        total_inserted = 0
        with connection.cursor() as cur:
            for doctor in doctors:
                for hol_date, hol_name in sorted(za_holidays.items()):
                    if hol_date < today:
                        continue
                    for slot_time in slots:
                        cur.execute(
                            """
                            INSERT IGNORE INTO blocked_slots
                                (doctor_id, blocked_date, blocked_time, reason, created_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            """,
                            [doctor.id, hol_date, slot_time, f"{reason} — {hol_name}"]
                        )
                        total_inserted += cur.rowcount

        self.stdout.write(self.style.SUCCESS(
            f"Blocked {total_inserted} slots across {doctors.count()} doctors "
            f"for {len(za_holidays)} public holidays ({start_year}–{end_year})."
        ))