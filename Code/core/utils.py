import random
import re
from datetime import datetime, timedelta


# ============================================================
# SMS (console only — no external gateway)
# ============================================================

def format_e164_za(phone):
    """Convert a South African phone number to E.164 (+27...) format."""
    if not phone:
        return phone
    phone = str(phone).replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
    if phone.startswith("0"):
        phone = "+27" + phone[1:]
    elif phone.startswith("27") and not phone.startswith("+"):
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+" + phone
    return phone


def send_otp_sms(phone_number, otp):
    """
    Print the OTP to the console.
    No SMS is actually sent — this is a demo/development build.
    """
    to_number = format_e164_za(phone_number)
    print("\n" + "=" * 60)
    print(f"[OTP STORED IN DATABASE]")
    print(f"Phone: {to_number}")
    print(f"OTP:   {otp}")
    print("=" * 60 + "\n")
    return True


def send_sms_reminder(phone_number, message):
    """
    Print the reminder to the console.
    No SMS is actually sent — this is a demo/development build.
    """
    to_number = format_e164_za(phone_number)
    print("\n" + "=" * 60)
    print(f"[REMINDER LOGGED]")
    print(f"Phone:   {to_number}")
    print(f"Message: {message}")
    print("=" * 60 + "\n")
    return True


# ============================================================
# SA ID validation
# ============================================================

def validate_sa_id(sa_id):
    """Validate South African ID number using Luhn algorithm"""
    try:
        if not sa_id or not sa_id.isdigit() or len(sa_id) != 13:
            return False
        total = 0
        for i in range(12):
            digit = int(sa_id[11 - i])
            if i % 2 == 0:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        check_digit = (10 - (total % 10)) % 10
        return check_digit == int(sa_id[12])
    except Exception:
        return False


def validate_phone_number(phone):
    """Validate South African phone number"""
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    patterns = [
        r'^0[6789][0-9]{8}$',
        r'^27[6789][0-9]{8}$',
        r'^\+27[6789][0-9]{8}$',
    ]
    for pattern in patterns:
        if re.match(pattern, phone):
            return True
    return False


# ============================================================
# Helpers
# ============================================================

def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])


def generate_staff_id():
    """Generate a unique staff ID"""
    import uuid
    return f"STAFF{uuid.uuid4().hex[:6].upper()}"


def get_current_time():
    """Get current time in Africa/Johannesburg timezone"""
    from django.utils import timezone
    return timezone.now()


def format_time_for_display(time_obj):
    if time_obj:
        return time_obj.strftime('%H:%M')
    return ''


def format_date_for_display(date_obj):
    if date_obj:
        return date_obj.strftime('%Y-%m-%d')
    return ''