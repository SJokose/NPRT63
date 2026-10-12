import random
import re
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.conf import settings

#ClickSend SDK Import
try:
    import clicksend
    CLICKSEND_AVAILABLE = True
    CLICKSEND_IMPORT_ERROR = None
except Exception as e:
    clicksend = None
    CLICKSEND_AVAILABLE = False
    CLICKSEND_IMPORT_ERROR = str(e)


def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])


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


def _send_via_clicksend(to_number, message_body):
    """
    Internal helper — sends an SMS using the ClickSend SDK.
    Returns (success, response_or_error).
    """
    account_username = settings.CLICKSEND_USERNAME
    api_key = settings.CLICKSEND_API_KEY

    # Configure the API client
    configuration = clicksend.Configuration()
    configuration.username = account_username
    configuration.password = api_key

    api_client = clicksend.ApiClient(configuration)

    # Build the message
    message = clicksend.SendSmsRequestMessagesInner(
        source="MediSync",
        body=message_body,
        to=to_number,
    )

    # Wrap it in a request
    send_request = clicksend.SendSmsRequest(
        messages=[message],
    )

    # Send via the SMS API
    sms_api = clicksend.SmsApi(api_client)
    response = sms_api.send_sms(send_sms_request=send_request)

    return True, response


def send_otp_sms(phone_number, otp):
    """
    Sends an OTP via ClickSend SMS. Falls back to console logging if
    ClickSend credentials are missing or the SDK is unavailable.
    """
    account_username = settings.CLICKSEND_USERNAME
    api_key = settings.CLICKSEND_API_KEY
    to_number = format_e164_za(phone_number)

    # Fallback: print to console if ClickSend isn't configured
    if not CLICKSEND_AVAILABLE or not account_username or not api_key:
        print("\n" + "=" * 60)
        print(f"[SMS MOCK — ClickSend not configured]")
        print(f"Phone: {to_number}")
        print(f"OTP:   {otp}")
        if CLICKSEND_IMPORT_ERROR:
            print(f"SDK error: {CLICKSEND_IMPORT_ERROR}")
        print("=" * 60 + "\n")
        return True

    try:
        message_body = (
            f"Your MediSync SA verification code is: {otp}. "
            f"Valid for 10 minutes. Do not share this code."
        )
        success, response = _send_via_clicksend(to_number, message_body)
        print(f"[OK] OTP sent to {to_number}. Response: {response}")
        return True
    except Exception as e:
        print(f"[FAIL] Failed to send OTP to {to_number}: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_sms_reminder(phone_number, message):
    """
    Sends an appointment reminder via ClickSend SMS. Falls back to
    console logging if ClickSend credentials are missing.
    """
    account_username = settings.CLICKSEND_USERNAME
    api_key = settings.CLICKSEND_API_KEY
    to_number = format_e164_za(phone_number)

    # Fallback: print to console if ClickSend isn't configured
    if not CLICKSEND_AVAILABLE or not account_username or not api_key:
        print("\n" + "=" * 60)
        print(f"[REMINDER MOCK — ClickSend not configured]")
        print(f"Phone:   {to_number}")
        print(f"Message: {message}")
        if CLICKSEND_IMPORT_ERROR:
            print(f"SDK error: {CLICKSEND_IMPORT_ERROR}")
        print("=" * 60 + "\n")
        return True

    try:
        success, response = _send_via_clicksend(to_number, message)
        print(f"[OK] Reminder sent to {to_number}. Response: {response}")
        return True
    except Exception as e:
        print(f"[FAIL] Failed to send reminder to {to_number}: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# Unchanged functions
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
    except:
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


def generate_staff_id():
    """Generate a unique staff ID"""
    import uuid
    return f"STAFF{uuid.uuid4().hex[:6].upper()}"


def get_current_time():
    """Get current time in Africa/Johannesburg timezone"""
    from django.utils import timezone
    return timezone.now()


def format_time_for_display(time_obj):
    """Format time for display"""
    if time_obj:
        return time_obj.strftime('%H:%M')
    return ''


def format_date_for_display(date_obj):
    """Format date for display"""
    if date_obj:
        return date_obj.strftime('%Y-%m-%d')
    return ''