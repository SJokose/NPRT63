"""
MediSync SA — Test suite.

Runs with:    python manage.py test
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import (
    User, Appointment, FollowUp, Referral,
    Prescription, ClinicalNote, BlockedSlot, Queue,
)


# ==========================================================
# Helpers
# ==========================================================
def make_sa_id(seed=None):
    """
    Generate a valid 13-digit SA ID (Luhn-valid) so tests never
    collide when the test DB is reused (--keepdb).
    """
    if seed is None:
        seed = uuid.uuid4().int
    base = f"{seed:012d}"[-12:]
    total = 0
    for i in range(12):
        digit = int(base[11 - i])
        if i % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    check = (10 - (total % 10)) % 10
    return f"{base}{check}"


# ==========================================================
# Registration & Auth
# ==========================================================
class PatientRegistrationTests(TestCase):

    def test_patient_can_register(self):
        sa_id = make_sa_id()
        response = self.client.post('/register/', {
            'sa_id_number': sa_id,
            'first_name': 'Test',
            'last_name': 'Patient',
            'email': f'test.patient.{sa_id}@example.com',
            'phone_number': '0712345678',
            'date_of_birth': '1990-01-01',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        if response.status_code != 302:
            print("REGISTRATION FORM ERRORS:", response.context['form'].errors)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(sa_id_number=sa_id).exists())
        user = User.objects.get(sa_id_number=sa_id)
        self.assertEqual(user.role, 'patient')
        self.assertEqual(user.username, sa_id)

    def test_duplicate_sa_id_is_rejected(self):
        sa_id = make_sa_id()
        User.objects.create_user(
            username=sa_id,
            sa_id_number=sa_id,
            password='ExistingPass123!',
            role='patient',
            email=f'existing.{sa_id}@example.com',
        )
        self.client.post('/register/', {
            'sa_id_number': sa_id,
            'first_name': 'Dup',
            'last_name': 'Patient',
            'email': f'dup.{sa_id}@example.com',
            'phone_number': '0712345678',
            'date_of_birth': '1990-01-01',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertEqual(User.objects.filter(sa_id_number=sa_id).count(), 1)

    def test_invalid_sa_id_is_rejected(self):
        response = self.client.post('/register/', {
            'sa_id_number': '1234567890123',
            'first_name': 'Bad',
            'last_name': 'ID',
            'email': 'bad@example.com',
            'phone_number': '0712345678',
            'date_of_birth': '1990-01-01',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertFalse(User.objects.filter(sa_id_number='1234567890123').exists())


class StaffRegistrationAccessTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdminPass123!', role='admin',
            email='admin@example.com',
        )

    def test_anonymous_cannot_register_staff(self):
        response = self.client.get('/register/staff/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_admin_can_register_staff(self):
        self.client.login(username='ADM001', password='AdminPass123!')
        response = self.client.get('/register/staff/')
        self.assertEqual(response.status_code, 200)


# ==========================================================
# Role access control
# ==========================================================
class RoleAccessTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=1)
        self.other_patient_sa = make_sa_id(seed=2)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.other_patient = User.objects.create_user(
            username=self.other_patient_sa, sa_id_number=self.other_patient_sa,
            password='PatPass123!', role='patient',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )

    def _login(self, username, password):
        self.client.login(username=username, password=password)

    def test_receptionist_cannot_view_medical_records(self):
        self._login('REC001', 'RecPass123!')
        response = self.client.get(f'/staff/records/view/{self.patient.id}/')
        self.assertEqual(response.status_code, 302)

    def test_patient_cannot_view_other_patients_records(self):
        self._login(self.patient_sa, 'PatPass123!')
        response = self.client.get(f'/staff/records/view/{self.other_patient.id}/')
        self.assertEqual(response.status_code, 302)

    def test_doctor_can_view_medical_records(self):
        self._login('DOC001', 'DocPass123!')
        response = self.client.get(f'/staff/records/view/{self.patient.id}/')
        self.assertEqual(response.status_code, 200)

    def test_nurse_can_view_medical_records(self):
        self._login('NUR001', 'NurPass123!')
        response = self.client.get(f'/staff/records/view/{self.patient.id}/')
        self.assertEqual(response.status_code, 200)

    def test_receptionist_cannot_access_user_management(self):
        self._login('REC001', 'RecPass123!')
        response = self.client.get('/staff/users/')
        self.assertEqual(response.status_code, 302)

    def test_nurse_cannot_access_user_management(self):
        self._login('NUR001', 'NurPass123!')
        response = self.client.get('/staff/users/')
        self.assertEqual(response.status_code, 302)

    def test_admin_can_access_user_management(self):
        self._login('ADM001', 'AdmPass123!')
        response = self.client.get('/staff/users/')
        self.assertEqual(response.status_code, 200)

    def test_doctor_cannot_access_reports(self):
        self._login('DOC001', 'DocPass123!')
        response = self.client.get('/staff/reports/')
        self.assertEqual(response.status_code, 302)

    def test_admin_can_access_reports(self):
        self._login('ADM001', 'AdmPass123!')
        response = self.client.get('/staff/reports/')
        self.assertEqual(response.status_code, 200)

    def test_doctor_cannot_access_queue(self):
        self._login('DOC001', 'DocPass123!')
        response = self.client.get('/staff/queue/')
        self.assertEqual(response.status_code, 302)

    def test_receptionist_can_access_queue(self):
        self._login('REC001', 'RecPass123!')
        response = self.client.get('/staff/queue/')
        self.assertEqual(response.status_code, 200)

    def test_receptionist_cannot_record_vitals(self):
        self._login('REC001', 'RecPass123!')
        response = self.client.get(f'/nurse/record-vitals/{self.patient.id}/')
        self.assertEqual(response.status_code, 302)

    def test_nurse_can_record_vitals(self):
        self._login('NUR001', 'NurPass123!')
        response = self.client.get(f'/nurse/record-vitals/{self.patient.id}/')
        self.assertEqual(response.status_code, 200)


# ==========================================================
# Appointment booking
# ==========================================================
class AppointmentBookingTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.patient_sa = make_sa_id(seed=101)
        self.other_patient_sa = make_sa_id(seed=102)

        self.patient = User.objects.create_user(
            username=self.patient_sa,
            sa_id_number=self.patient_sa,
            password='PatPass123!',
            role='patient',
            email='pat@example.com',
            phone_number='0711111111',
        )
        self.other_patient = User.objects.create_user(
            username=self.other_patient_sa,
            sa_id_number=self.other_patient_sa,
            password='PatPass123!',
            role='patient',
            email='pat2@example.com',
            phone_number='0711111112',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
            email='doc@example.com',
        )
        self.future_date = (timezone.now().date() + timedelta(days=10)).isoformat()

    def test_booking_creates_pending_appointment(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        self.client.post('/patient/book/', {
            'doctor': self.doctor.id,
            'appointment_date': self.future_date,
            'appointment_time': '10:00',
            'reason_for_visit': 'Headache',
        })
        self.assertEqual(Appointment.objects.filter(patient=self.patient).count(), 1)
        appt = Appointment.objects.get(patient=self.patient)
        self.assertEqual(appt.status, 'pending')
        self.assertEqual(appt.doctor, self.doctor)

    def test_double_booking_same_slot_is_rejected(self):
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=self.future_date,
            appointment_time='10:00',
            reason_for_visit='First',
            status='pending',
        )
        self.client.login(username=self.other_patient_sa, password='PatPass123!')
        self.client.post('/patient/book/', {
            'doctor': self.doctor.id,
            'appointment_date': self.future_date,
            'appointment_time': '10:00',
            'reason_for_visit': 'Second',
        })
        count = Appointment.objects.filter(
            doctor=self.doctor,
            appointment_date=self.future_date,
            appointment_time='10:00',
        ).count()
        self.assertEqual(count, 1)

    def test_same_patient_same_day_is_rejected(self):
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=self.future_date,
            appointment_time='10:00',
            reason_for_visit='First',
            status='pending',
        )
        self.client.login(username=self.patient_sa, password='PatPass123!')
        self.client.post('/patient/book/', {
            'doctor': self.doctor.id,
            'appointment_date': self.future_date,
            'appointment_time': '14:00',
            'reason_for_visit': 'Second',
        })
        count = Appointment.objects.filter(
            patient=self.patient,
            appointment_date=self.future_date,
        ).count()
        self.assertEqual(count, 1)


# ==========================================================
# Appointment management
# ==========================================================
class AppointmentManagementTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=201)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=5)),
            appointment_time='10:00',
            reason_for_visit='Test',
            status='pending',
        )

    def test_nurse_cannot_approve_appointment(self):
        self.client.login(username='NUR001', password='NurPass123!')
        self.client.post('/staff/appointments/', {
            'appointment_id': self.appointment.id,
            'action': 'approve',
        })
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'pending')

    def test_doctor_can_approve_own_appointment(self):
        self.client.login(username='DOC001', password='DocPass123!')
        self.client.post('/staff/appointments/', {
            'appointment_id': self.appointment.id,
            'action': 'approve',
        })
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'confirmed')

    def test_doctor_cannot_approve_another_doctors_appointment(self):
        self.client.login(username='DOC002', password='DocPass123!')
        self.client.post('/staff/appointments/', {
            'appointment_id': self.appointment.id,
            'action': 'approve',
        })
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'pending')


# ==========================================================
# Follow-up lifecycle
# ==========================================================
class FollowUpTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=301)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=timezone.now().date(),
            appointment_time='10:00',
            reason_for_visit='Test',
            status='completed',
        )
        self.followup = FollowUp.objects.create(
            patient=self.patient, doctor=self.doctor,
            original_appointment=self.appointment,
            due_date=(timezone.now().date() + timedelta(days=14)),
            reason='Review',
            status='due',
        )

    def test_followup_starts_due(self):
        self.assertEqual(self.followup.status, 'due')
        self.assertIsNone(self.followup.scheduled_appointment)

    def test_patient_sees_followup_on_dashboard(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get('/patient/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Review')


# ==========================================================
# Utils
# ==========================================================
class UtilsGenerateOtpTests(TestCase):

    def test_generate_otp_format(self):
        from core.utils import generate_otp
        otp = generate_otp()
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())

    def test_generate_otp_random(self):
        from core.utils import generate_otp
        self.assertNotEqual(generate_otp(), generate_otp())


class UtilsSaIdTests(TestCase):

    def test_valid_sa_id_accepted(self):
        from core.utils import validate_sa_id
        self.assertTrue(validate_sa_id('8001015009087'))

    def test_invalid_luhn_rejected(self):
        from core.utils import validate_sa_id
        self.assertFalse(validate_sa_id('8001015009088'))

    def test_wrong_length_rejected(self):
        from core.utils import validate_sa_id
        self.assertFalse(validate_sa_id('800101500908'))
        self.assertFalse(validate_sa_id('80010150090870'))

    def test_non_digit_rejected(self):
        from core.utils import validate_sa_id
        self.assertFalse(validate_sa_id('80010150090AB'))
        self.assertFalse(validate_sa_id(''))
        self.assertFalse(validate_sa_id(None))


class UtilsPhoneTests(TestCase):

    def test_format_e164_za_leading_zero(self):
        from core.utils import format_e164_za
        self.assertEqual(format_e164_za('0712345678'), '+27712345678')

    def test_format_e164_za_already_international(self):
        from core.utils import format_e164_za
        self.assertEqual(format_e164_za('+27712345678'), '+27712345678')

    def test_format_e164_za_strips_separators(self):
        from core.utils import format_e164_za
        self.assertEqual(format_e164_za('071 234-5678'), '+27712345678')

    def test_format_e164_za_empty(self):
        from core.utils import format_e164_za
        self.assertEqual(format_e164_za(''), '')
        self.assertIsNone(format_e164_za(None))

    def test_validate_phone_number_valid(self):
        from core.utils import validate_phone_number
        self.assertTrue(validate_phone_number('0712345678'))
        self.assertTrue(validate_phone_number('+27712345678'))
        self.assertTrue(validate_phone_number('27712345678'))

    def test_validate_phone_number_invalid(self):
        from core.utils import validate_phone_number
        self.assertFalse(validate_phone_number('12345'))
        self.assertFalse(validate_phone_number('0512345678'))


class UtilsSmsStubTests(TestCase):

    def test_send_otp_sms_returns_true(self):
        from core.utils import send_otp_sms
        self.assertTrue(send_otp_sms('0712345678', '123456'))

    def test_send_sms_reminder_returns_true(self):
        from core.utils import send_sms_reminder
        self.assertTrue(send_sms_reminder('0712345678', 'Hello'))


# ==========================================================
# Auth flow
# ==========================================================
class LoginFlowTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=401)
        self.patient = User.objects.create_user(
            username=self.patient_sa,
            sa_id_number=self.patient_sa,
            password='PatPass123!',
            role='patient',
            phone_number='0711111111',
        )
        self.doctor = User.objects.create_user(
            username='DOC001',
            staff_id='DOC001',
            password='DocPass123!',
            role='doctor',
            phone_number='0722222222',
        )

    @patch('core.views.send_otp_sms', return_value=True)
    def test_patient_login_sends_otp_and_redirects(self, mock_sms):
        response = self.client.post('/login/', {
            'username': self.patient_sa,
            'password': 'PatPass123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verify-otp/', response.url)
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.otp_code)
        self.assertEqual(len(self.patient.otp_code), 6)
        self.assertEqual(self.client.session.get('user_id'), self.patient.id)
        mock_sms.assert_called_once()

    @patch('core.views.send_otp_sms', return_value=True)
    def test_staff_login_sends_otp_and_redirects(self, mock_sms):
        response = self.client.post('/login/', {
            'username': 'DOC001',
            'password': 'DocPass123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verify-otp/', response.url)
        self.doctor.refresh_from_db()
        self.assertIsNotNone(self.doctor.otp_code)

    @patch('core.views.send_otp_sms', return_value=True)
    def test_unknown_user_shows_error(self, mock_sms):
        response = self.client.post('/login/', {
            'username': '9999999999999',
            'password': 'Whatever123!',
        })
        self.assertEqual(response.status_code, 200)
        mock_sms.assert_not_called()

    @patch('core.views.send_otp_sms', return_value=True)
    def test_wrong_password_for_staff_shows_error(self, mock_sms):
        response = self.client.post('/login/', {
            'username': 'DOC001',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, 200)
        mock_sms.assert_not_called()
        self.doctor.refresh_from_db()
        self.assertIsNone(self.doctor.otp_code)


class VerifyOtpFlowTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=402)
        self.patient = User.objects.create_user(
            username=self.patient_sa,
            sa_id_number=self.patient_sa,
            password='PatPass123!',
            role='patient',
            phone_number='0711111111',
            otp_code='123456',
            otp_created_at=timezone.now(),
        )

    def _set_session(self):
        session = self.client.session
        session['user_id'] = self.patient.id
        session.save()

    def test_correct_otp_logs_patient_in(self):
        self._set_session()
        response = self.client.post('/verify-otp/', {'otp_code': '123456'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.patient.id)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.otp_code)

    def test_wrong_otp_does_not_log_in(self):
        self._set_session()
        response = self.client.post('/verify-otp/', {'otp_code': '000000'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_expired_otp_does_not_log_in(self):
        self.patient.otp_created_at = timezone.now() - timedelta(minutes=11)
        self.patient.save()
        self._set_session()
        response = self.client.post('/verify-otp/', {'otp_code': '123456'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_verify_without_session_redirects_to_login(self):
        response = self.client.get('/verify-otp/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


class LogoutFlowTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=403)
        self.patient = User.objects.create_user(
            username=self.patient_sa,
            sa_id_number=self.patient_sa,
            password='PatPass123!',
            role='patient',
        )

    def test_logout_clears_session(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        self.assertIn('_auth_user_id', self.client.session)
        response = self.client.get('/logout/')
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)


# ==========================================================
# Referrals — forms
# ==========================================================
class ReferralFormTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=501)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )

    def _form_data(self, **overrides):
        data = {
            'referred_to_doctor': '',
            'referred_to': '',
            'specialty': '',
            'reason': 'Patient needs cardiology review',
            'clinical_summary': '',
            'urgency': 'routine',
        }
        data.update(overrides)
        return data

    def test_neither_internal_nor_external_is_invalid(self):
        from core.forms import ReferralForm
        form = ReferralForm(data=self._form_data())
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_external_only_is_valid(self):
        from core.forms import ReferralForm
        form = ReferralForm(data=self._form_data(referred_to='Groote Schuur Hospital'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_internal_only_is_valid(self):
        from core.forms import ReferralForm
        form = ReferralForm(data=self._form_data(referred_to_doctor=self.other_doctor.id))
        self.assertTrue(form.is_valid(), form.errors)

    def test_short_reason_is_invalid(self):
        from core.forms import ReferralForm
        form = ReferralForm(data=self._form_data(
            referred_to='Somewhere', reason='abc'
        ))
        self.assertFalse(form.is_valid())
        self.assertIn('reason', form.errors)

    def test_urgency_choices_restricted(self):
        from core.forms import ReferralForm
        form = ReferralForm(data=self._form_data(
            referred_to='Somewhere', urgency='bogus'
        ))
        self.assertFalse(form.is_valid())
        self.assertIn('urgency', form.errors)


# ==========================================================
# Referrals — views
# ==========================================================
class CreateReferralViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=502)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.url = f'/staff/referral/create/{self.patient.id}/'

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_nurse_cannot_create_referral(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_doctor_gets_form(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_doctor_can_create_external_referral(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'referred_to_doctor': '',
            'referred_to': 'Groote Schuur Hospital',
            'specialty': 'Cardiology',
            'reason': 'Needs specialist review',
            'clinical_summary': 'Patient reports chest pain.',
            'urgency': 'urgent',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/staff/records/view/{self.patient.id}/', response.url)

        ref = Referral.objects.get(patient=self.patient)
        self.assertEqual(ref.referring_doctor, self.doctor)
        self.assertEqual(ref.referred_to, 'Groote Schuur Hospital')
        self.assertEqual(ref.urgency, 'urgent')
        self.assertEqual(ref.status, 'pending')

    def test_doctor_can_create_internal_referral_and_notifies_receiver(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'referred_to_doctor': self.other_doctor.id,
            'referred_to': '',
            'specialty': 'Cardiology',
            'reason': 'Needs specialist review',
            'clinical_summary': '',
            'urgency': 'routine',
        })
        self.assertEqual(response.status_code, 302)

        ref = Referral.objects.get(patient=self.patient)
        self.assertEqual(ref.referred_to_doctor, self.other_doctor)

        from core.models import Notification
        self.assertTrue(
            Notification.objects.filter(
                user=self.other_doctor,
                notification_type='referral',
            ).exists()
        )


class ViewReferralsTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=503)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.referral = Referral.objects.create(
            patient=self.patient,
            referring_doctor=self.doctor,
            referred_to='Groote Schuur Hospital',
            reason='Specialist review needed',
            urgency='routine',
            status='pending',
        )
        self.url = f'/staff/referral/view/{self.patient.id}/'

    def test_doctor_can_view_referrals(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Groote Schuur Hospital')

    def test_nurse_can_view_referrals(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_receptionist_cannot_view_referrals(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)


class ReferralsReceivedTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=504)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.referring_doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.receiving_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
            last_name='Naidoo',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC003', staff_id='DOC003',
            password='DocPass123!', role='doctor',
        )

        self.internal_ref = Referral.objects.create(
            patient=self.patient,
            referring_doctor=self.referring_doctor,
            referred_to_doctor=self.receiving_doctor,
            referred_to='Dr. Naidoo — Cardiology',
            reason='Cardiology review',
            urgency='routine',
            status='pending',
        )
        self.external_ref = Referral.objects.create(
            patient=self.patient,
            referring_doctor=self.referring_doctor,
            referred_to='Dr Naidoo at Milpark',
            reason='Second opinion',
            urgency='urgent',
            status='pending',
        )
        self.other_ref = Referral.objects.create(
            patient=self.patient,
            referring_doctor=self.referring_doctor,
            referred_to='Some other clinic',
            reason='Dermatology',
            urgency='routine',
            status='pending',
        )

    def test_receiving_doctor_sees_internal_and_name_matched(self):
        self.client.login(username='DOC002', password='DocPass123!')
        response = self.client.get('/staff/referrals/received/')
        self.assertEqual(response.status_code, 200)
        referrals = list(response.context['referrals'])
        self.assertIn(self.internal_ref, referrals)
        self.assertIn(self.external_ref, referrals)
        self.assertNotIn(self.other_ref, referrals)

    def test_unrelated_doctor_sees_nothing(self):
        self.client.login(username='DOC003', password='DocPass123!')
        response = self.client.get('/staff/referrals/received/')
        self.assertEqual(response.status_code, 200)
        referrals = list(response.context['referrals'])
        self.assertNotIn(self.internal_ref, referrals)
        self.assertNotIn(self.external_ref, referrals)
        self.assertNotIn(self.other_ref, referrals)

    def test_status_filter(self):
        self.internal_ref.status = 'accepted'
        self.internal_ref.save()

        self.client.login(username='DOC002', password='DocPass123!')
        response = self.client.get('/staff/referrals/received/?status=accepted')
        self.assertEqual(response.status_code, 200)
        referrals = list(response.context['referrals'])
        self.assertIn(self.internal_ref, referrals)
        self.assertNotIn(self.external_ref, referrals)
        self.assertNotIn(self.other_ref, referrals)


class UpdateReferralStatusTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=505)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.referring_doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.receiving_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )
        self.unrelated_doctor = User.objects.create_user(
            username='DOC003', staff_id='DOC003',
            password='DocPass123!', role='doctor',
        )
        self.referral = Referral.objects.create(
            patient=self.patient,
            referring_doctor=self.referring_doctor,
            referred_to_doctor=self.receiving_doctor,
            referred_to='Dr. Receiving',
            reason='Review needed',
            urgency='routine',
            status='pending',
        )
        self.url = f'/staff/referrals/{self.referral.id}/update/'

    def test_receiving_doctor_can_accept(self):
        self.client.login(username='DOC002', password='DocPass123!')
        response = self.client.post(self.url, {'status': 'accepted'})
        self.assertEqual(response.status_code, 302)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, 'accepted')

        from core.models import Notification
        self.assertTrue(
            Notification.objects.filter(
                user=self.referring_doctor,
                notification_type='referral',
            ).exists()
        )

    def test_receiving_doctor_can_complete(self):
        self.client.login(username='DOC002', password='DocPass123!')
        self.client.post(self.url, {'status': 'completed'})
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, 'completed')

    def test_receiving_doctor_can_cancel(self):
        self.client.login(username='DOC002', password='DocPass123!')
        self.client.post(self.url, {'status': 'cancelled'})
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, 'cancelled')

    def test_unrelated_doctor_cannot_change_status(self):
        self.client.login(username='DOC003', password='DocPass123!')
        response = self.client.post(self.url, {'status': 'accepted'})
        self.assertEqual(response.status_code, 302)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, 'pending')

    def test_invalid_status_value_is_ignored(self):
        self.client.login(username='DOC002', password='DocPass123!')
        self.client.post(self.url, {'status': 'bogus'})
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, 'pending')


# ==========================================================
# Prescriptions
# ==========================================================
class PrescriptionViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=601)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
            phone_number='0711111111',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.url = f'/staff/prescription/add/{self.patient.id}/'

    def _valid_data(self):
        return {
            'medication_name': 'Amoxicillin',
            'dosage': '500mg',
            'frequency': '3x daily',
            'duration': '7 days',
            'instructions': 'Take after meals',
            'expiry_date': '',
        }

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_receptionist_cannot_add_prescription(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_doctor_gets_form(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_doctor_can_create_prescription(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, self._valid_data())
        self.assertEqual(response.status_code, 302)

        prescription = Prescription.objects.get(patient=self.patient)
        self.assertEqual(prescription.doctor, self.doctor)
        self.assertEqual(prescription.medication_name, 'Amoxicillin')
        self.assertEqual(prescription.dosage, '500mg')

    def test_doctor_creating_prescription_notifies_patient(self):
        from core.models import Notification
        self.client.login(username='DOC001', password='DocPass123!')
        self.client.post(self.url, self._valid_data())
        self.assertTrue(
            Notification.objects.filter(
                user=self.patient,
                notification_type='prescription',
            ).exists()
        )

    def test_nurse_gets_readonly_view(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('form', response.context)

    def test_nurse_cannot_create_prescription(self):
        self.client.login(username='NUR001', password='NurPass123!')
        self.client.post(self.url, self._valid_data())
        self.assertFalse(Prescription.objects.filter(patient=self.patient).exists())


class NurseViewPrescriptionsTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=602)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.prescription = Prescription.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            medication_name='Paracetamol',
            dosage='1g',
            frequency='4x daily',
            duration='3 days',
        )
        self.url = f'/staff/prescription/view/{self.patient.id}/'

    def test_doctor_can_view_prescriptions(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_nurse_can_view_prescriptions(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        prescriptions = list(response.context['prescriptions'])
        self.assertIn(self.prescription, prescriptions)

    def test_receptionist_cannot_view_prescriptions(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_patient_cannot_view_prescriptions(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)


# ==========================================================
# Clinical notes
# ==========================================================
class ClinicalNoteFormTests(TestCase):

    def _form_data(self, **overrides):
        data = {
            'note_type': 'nursing',
            'title': 'Post-op observation',
            'content': 'Patient stable.',
        }
        data.update(overrides)
        return data

    def test_valid_content_accepted(self):
        from core.forms import ClinicalNoteForm
        form = ClinicalNoteForm(data=self._form_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_content_shorter_than_3_chars_rejected(self):
        from core.forms import ClinicalNoteForm
        form = ClinicalNoteForm(data=self._form_data(content='ab'))
        self.assertFalse(form.is_valid())
        self.assertIn('content', form.errors)

    def test_content_exactly_3_chars_accepted(self):
        from core.forms import ClinicalNoteForm
        form = ClinicalNoteForm(data=self._form_data(content='abc'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_note_type_rejected(self):
        from core.forms import ClinicalNoteForm
        data = self._form_data()
        del data['note_type']
        form = ClinicalNoteForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('note_type', form.errors)


class AddClinicalNoteViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=603)
        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.url = f'/staff/clinical-note/add/{self.patient.id}/'

    def _valid_data(self):
        return {
            'note_type': 'nursing',
            'title': 'Observation',
            'content': 'Patient is stable and comfortable.',
        }

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_receptionist_cannot_add_note(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_doctor_gets_form(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_nurse_gets_form(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_doctor_can_add_note(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, self._valid_data())
        self.assertEqual(response.status_code, 302)

        note = ClinicalNote.objects.get(patient=self.patient)
        self.assertEqual(note.author, self.doctor)
        self.assertEqual(note.note_type, 'nursing')
        self.assertEqual(note.content, 'Patient is stable and comfortable.')

    def test_nurse_can_add_note(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.post(self.url, self._valid_data())
        self.assertEqual(response.status_code, 302)

        note = ClinicalNote.objects.get(patient=self.patient)
        self.assertEqual(note.author, self.nurse)

    def test_short_content_does_not_create_note(self):
        self.client.login(username='DOC001', password='DocPass123!')
        data = self._valid_data()
        data['content'] = 'ab'
        self.client.post(self.url, data)
        self.assertFalse(ClinicalNote.objects.filter(patient=self.patient).exists())


# ==========================================================
# Blocked slots — access, validation, direct ORM
# ==========================================================
class BlockedSlotTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=701)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )

        self.url = '/staff/block-slots/'
        self.future_date = (timezone.now().date() + timedelta(days=7)).isoformat()
        self.future_date_2 = (timezone.now().date() + timedelta(days=8)).isoformat()
        self.past_date = (timezone.now().date() - timedelta(days=1)).isoformat()

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_doctor_gets_page(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_nurse_cannot_access_block_slots(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_receptionist_cannot_access_block_slots(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_past_slot_is_rejected(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'block',
            'scope': 'slot',
            'blocked_date': self.past_date,
            'blocked_time': '10:00',
            'reason': 'Nope',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BlockedSlot.objects.filter(
                doctor=self.doctor,
                blocked_date=self.past_date,
            ).exists()
        )

    def test_missing_time_is_rejected(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'block',
            'scope': 'slot',
            'blocked_date': self.future_date,
            'blocked_time': '',
            'reason': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BlockedSlot.objects.filter(
                doctor=self.doctor,
                blocked_date=self.future_date,
            ).exists()
        )

    def test_range_with_end_before_start_is_rejected(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'block',
            'scope': 'range',
            'start_date': self.future_date_2,
            'end_date': self.future_date,
            'reason': 'Bad range',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BlockedSlot.objects.filter(
                doctor=self.doctor,
                blocked_date__in=[self.future_date, self.future_date_2],
            ).exists()
        )

    def test_range_exceeding_90_days_is_rejected(self):
        long_end = (timezone.now().date() + timedelta(days=120)).isoformat()
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'block',
            'scope': 'range',
            'start_date': self.future_date,
            'end_date': long_end,
            'reason': 'Too long',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BlockedSlot.objects.filter(
                doctor=self.doctor,
                blocked_date__gte=self.future_date,
            ).exists()
        )

    def test_doctor_cannot_unblock_another_doctors_slot(self):
        other = BlockedSlot.objects.create(
            doctor=self.other_doctor,
            blocked_date=self.future_date,
            blocked_time='11:00',
            reason='Belongs to other doctor',
        )
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'unblock',
            'slot_id': other.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedSlot.objects.filter(id=other.id).exists())

    def test_unblock_slot_view_cannot_touch_another_doctors_slot(self):
        slot = BlockedSlot.objects.create(
            doctor=self.other_doctor,
            blocked_date=self.future_date,
            blocked_time='15:00',
            reason='Other',
        )
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(f'/staff/block-slots/unblock/{slot.id}/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedSlot.objects.filter(id=slot.id).exists())

    def test_unblock_slot_view_requires_doctor(self):
        slot = BlockedSlot.objects.create(
            doctor=self.doctor,
            blocked_date=self.future_date,
            blocked_time='15:00',
            reason='Test',
        )
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(f'/staff/block-slots/unblock/{slot.id}/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BlockedSlot.objects.filter(id=slot.id).exists())

    def test_unblock_slot_view_deletes_own_slot(self):
        slot = BlockedSlot.objects.create(
            doctor=self.doctor,
            blocked_date=self.future_date,
            blocked_time='15:00',
            reason='Test',
        )
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(f'/staff/block-slots/unblock/{slot.id}/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BlockedSlot.objects.filter(id=slot.id).exists())


# ==========================================================
# Blocked slots — tests that call the stored procedures
# ==========================================================
class BlockedSlotSPTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.patient_sa = make_sa_id(seed=702)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.other_doctor = User.objects.create_user(
            username='DOC002', staff_id='DOC002',
            password='DocPass123!', role='doctor',
        )

        self.url = '/staff/block-slots/'
        self.future_date = (timezone.now().date() + timedelta(days=7)).isoformat()
        self.future_date_2 = (timezone.now().date() + timedelta(days=8)).isoformat()

    def _call_sp_block_range(self, doctor_id, start, end, reason):
        """Call the SP directly, bypassing the view."""
        with connection.cursor() as cur:
            cur.callproc('sp_block_range',
                         [doctor_id, start, end, '09:00:00', '17:00:00', reason])

    def test_doctor_can_block_single_slot(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {
            'action': 'block',
            'scope': 'slot',
            'blocked_date': self.future_date,
            'blocked_time': '10:00',
            'reason': 'Conference',
        })
        self.assertEqual(response.status_code, 302)

        blocked = BlockedSlot.objects.filter(
            doctor=self.doctor,
            blocked_date=self.future_date,
        )
        self.assertTrue(blocked.exists())
        self.assertIn('10:00', [b.blocked_time.strftime('%H:%M') for b in blocked])

    def test_sp_block_range_inserts_rows(self):
        """
        Direct SP call — verifies the SP inserts the expected number
        of slots for a whole-day block. Doesn't go through the view.
        """
        start = timezone.now().date() + timedelta(days=7)
        self._call_sp_block_range(self.doctor.id, start, start, 'Sick day')

        count = BlockedSlot.objects.filter(
            doctor=self.doctor,
            blocked_date=start,
        ).count()
        self.assertGreaterEqual(count, 10)
        self.assertLessEqual(count, 20)

    def test_sp_block_range_multiple_days(self):
        start = timezone.now().date() + timedelta(days=7)
        end = timezone.now().date() + timedelta(days=8)
        self._call_sp_block_range(self.doctor.id, start, end, 'Leave')

        self.assertTrue(
            BlockedSlot.objects.filter(
                doctor=self.doctor, blocked_date=start,
            ).exists()
        )
        self.assertTrue(
            BlockedSlot.objects.filter(
                doctor=self.doctor, blocked_date=end,
            ).exists()
        )

    def test_doctor_can_unblock_their_slot(self):
        self.client.login(username='DOC001', password='DocPass123!')
        self.client.post(self.url, {
            'action': 'block',
            'scope': 'slot',
            'blocked_date': self.future_date,
            'blocked_time': '11:00',
            'reason': 'Test',
        })
        slot = BlockedSlot.objects.filter(
            doctor=self.doctor,
            blocked_date=self.future_date,
        ).first()
        self.assertIsNotNone(slot)

        response = self.client.post(self.url, {
            'action': 'unblock',
            'slot_id': slot.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            BlockedSlot.objects.filter(
                doctor=self.doctor,
                blocked_date=self.future_date,
            ).exists()
        )


# ==========================================================
# Reschedule appointment
# ==========================================================
class RescheduleAppointmentViewTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.patient_sa = make_sa_id(seed=801)
        self.other_patient_sa = make_sa_id(seed=802)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
            phone_number='0711111111',
        )
        self.other_patient = User.objects.create_user(
            username=self.other_patient_sa, sa_id_number=self.other_patient_sa,
            password='PatPass123!', role='patient',
            phone_number='0711111112',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )

        self.appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=5)),
            appointment_time='10:00',
            reason_for_visit='Headache',
            status='confirmed',
        )

        self.url = f'/patient/reschedule/{self.appointment.id}/'
        self.new_date = (timezone.now().date() + timedelta(days=10)).isoformat()

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_cannot_reschedule_another_patients_appointment(self):
        self.client.login(username=self.other_patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_cancelled_appointment_cannot_be_rescheduled(self):
        self.appointment.status = 'cancelled'
        self.appointment.save()
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/patient/appointments/', response.url)

    def test_doctor_gets_form(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_successful_reschedule_creates_new_appointment(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.post(self.url, {
            'appointment_date': self.new_date,
            'appointment_time': '14:00',
            'reason_for_visit': 'Rescheduled - headache',
        })
        self.assertEqual(response.status_code, 302)

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'cancelled')

        new_appt = Appointment.objects.filter(
            patient=self.patient,
            appointment_date=self.new_date,
            appointment_time='14:00',
            status='pending',
        ).first()
        self.assertIsNotNone(new_appt)
        self.assertNotEqual(new_appt.id, self.appointment.id)

    def test_reschedule_notifies_patient(self):
        from core.models import Notification
        self.client.login(username=self.patient_sa, password='PatPass123!')
        self.client.post(self.url, {
            'appointment_date': self.new_date,
            'appointment_time': '14:00',
            'reason_for_visit': 'Rescheduled - headache',
        })
        self.assertTrue(
            Notification.objects.filter(
                user=self.patient,
                notification_type='appointment',
            ).exists()
        )


# ==========================================================
# Cancel appointment
# ==========================================================
class CancelAppointmentViewTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.patient_sa = make_sa_id(seed=803)
        self.other_patient_sa = make_sa_id(seed=804)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
            phone_number='0711111111',
        )
        self.other_patient = User.objects.create_user(
            username=self.other_patient_sa, sa_id_number=self.other_patient_sa,
            password='PatPass123!', role='patient',
            phone_number='0711111112',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )

        self.appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=5)),
            appointment_time='10:00',
            reason_for_visit='Headache',
            status='confirmed',
        )

        self.url = f'/patient/cancel/{self.appointment.id}/'

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_cannot_cancel_another_patients_appointment(self):
        self.client.login(username=self.other_patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_get_shows_confirmation(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_post_cancels_appointment(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.post(self.url, {
            'reason': 'Cannot make it',
        })
        self.assertEqual(response.status_code, 302)

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'cancelled')
        self.assertIsNotNone(self.appointment.cancelled_at)

    def test_cancel_notifies_patient(self):
        from core.models import Notification
        self.client.login(username=self.patient_sa, password='PatPass123!')
        self.client.post(self.url, {'reason': 'Cannot make it'})
        self.assertTrue(
            Notification.objects.filter(
                user=self.patient,
                notification_type='appointment',
            ).exists()
        )


# ==========================================================
# Queue management
# ==========================================================
class ManageQueueViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=901)
        self.other_patient_sa = make_sa_id(seed=902)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )

        self.url = '/staff/queue/'

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_doctor_cannot_access_queue(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_receptionist_can_access_queue(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_nurse_can_access_queue(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access_queue(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_receptionist_can_add_patient_to_queue(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.post(self.url, {
            'patient_id': self.patient.id,
            'doctor_id': self.doctor.id,
        })
        self.assertEqual(response.status_code, 302)

        queue = Queue.objects.filter(patient=self.patient, doctor=self.doctor).first()
        self.assertIsNotNone(queue)
        self.assertEqual(queue.status, 'waiting')
        self.assertTrue(queue.queue_number.startswith('Q'))

    def test_missing_patient_does_not_create_queue(self):
        self.client.login(username='REC001', password='RecPass123!')
        self.client.post(self.url, {
            'patient_id': '',
            'doctor_id': self.doctor.id,
        })
        self.assertEqual(Queue.objects.count(), 0)

    def test_missing_doctor_does_not_create_queue(self):
        self.client.login(username='REC001', password='RecPass123!')
        self.client.post(self.url, {
            'patient_id': self.patient.id,
            'doctor_id': '',
        })
        self.assertEqual(Queue.objects.count(), 0)


class UpdateQueueStatusViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=911)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )

        self.queue = Queue.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            queue_number='Q241014-001',
            status='waiting',
        )
        self.url = f'/staff/queue/update/{self.queue.id}/'

    def test_anonymous_post_redirects(self):
        response = self.client.post(self.url, {'status': 'in_progress'})
        self.assertEqual(response.status_code, 302)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'waiting')

    def test_doctor_cannot_update_queue(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.post(self.url, {'status': 'in_progress'})
        self.assertEqual(response.status_code, 302)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'waiting')

    def test_receptionist_can_set_in_progress(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.post(self.url, {'status': 'in_progress'})
        self.assertEqual(response.status_code, 302)
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'in_progress')
        self.assertIsNotNone(self.queue.started_at)

    def test_receptionist_can_complete(self):
        self.client.login(username='REC001', password='RecPass123!')
        self.client.post(self.url, {'status': 'completed'})
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'completed')
        self.assertIsNotNone(self.queue.completed_at)

    def test_receptionist_can_skip(self):
        self.client.login(username='REC001', password='RecPass123!')
        self.client.post(self.url, {'status': 'skipped'})
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'skipped')

    def test_invalid_status_value_is_ignored(self):
        self.client.login(username='REC001', password='RecPass123!')
        self.client.post(self.url, {'status': 'bogus'})
        self.queue.refresh_from_db()
        self.assertEqual(self.queue.status, 'waiting')


class NurseCheckInViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=921)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )

        self.url = '/nurse/check-in/'

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_doctor_cannot_access_check_in(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_nurse_gets_page(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_nurse_can_check_in_patient(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.post(self.url, {
            'patient_id': self.patient.id,
            'doctor_id': self.doctor.id,
        })
        self.assertEqual(response.status_code, 302)

        queue = Queue.objects.filter(patient=self.patient, doctor=self.doctor).first()
        self.assertIsNotNone(queue)
        self.assertEqual(queue.status, 'waiting')
        self.assertTrue(queue.queue_number.startswith('Q'))

    def test_missing_doctor_does_not_create_queue(self):
        self.client.login(username='NUR001', password='NurPass123!')
        self.client.post(self.url, {
            'patient_id': self.patient.id,
            'doctor_id': '',
        })
        self.assertEqual(Queue.objects.count(), 0)


# ==========================================================
# Reports
# ==========================================================
class ReportsDashboardViewTests(TestCase):

    def setUp(self):
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.nurse = User.objects.create_user(
            username='NUR001', staff_id='NUR001',
            password='NurPass123!', role='nurse',
        )
        self.receptionist = User.objects.create_user(
            username='REC001', staff_id='REC001',
            password='RecPass123!', role='receptionist',
        )
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )

        self.url = '/staff/reports/'

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_doctor_cannot_access_reports(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_nurse_cannot_access_reports(self):
        self.client.login(username='NUR001', password='NurPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_receptionist_cannot_access_reports(self):
        self.client.login(username='REC001', password='RecPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_admin_can_access_reports(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class AppointmentReportViewTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=1001)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )

        self.pending = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=3)),
            appointment_time='09:00',
            reason_for_visit='Pending',
            status='pending',
        )
        self.completed = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=5)),
            appointment_time='10:00',
            reason_for_visit='Completed',
            status='completed',
        )

        self.url = '/staff/reports/appointments/'

    def test_doctor_cannot_access(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_admin_gets_report(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('appointments', response.context)

    def test_status_filter_pending(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url + '?status=pending')
        self.assertEqual(response.status_code, 200)
        appointments = list(response.context['appointments'])
        self.assertEqual(len(appointments), 1)
        self.assertEqual(appointments[0].id, self.pending.id)

    def test_summary_counts(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.context['total'], 2)
        self.assertEqual(response.context['pending'], 1)
        self.assertEqual(response.context['completed'], 1)


class PatientActivityReportViewTests(TestCase):

    def setUp(self):
        self.patient_sa_1 = make_sa_id(seed=1011)
        self.patient_sa_2 = make_sa_id(seed=1012)

        self.patient_1 = User.objects.create_user(
            username=self.patient_sa_1, sa_id_number=self.patient_sa_1,
            password='PatPass123!', role='patient',
        )
        self.patient_2 = User.objects.create_user(
            username=self.patient_sa_2, sa_id_number=self.patient_sa_2,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )

        Appointment.objects.create(
            patient=self.patient_1, doctor=self.doctor,
            appointment_date=(timezone.now().date() + timedelta(days=3)),
            appointment_time='09:00',
            reason_for_visit='Checkup',
            status='confirmed',
        )

        self.url = '/staff/reports/patients/'

    def test_doctor_cannot_access(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_admin_gets_report(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('patients', response.context)

    def test_total_patients_matches(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.context['total_patients'], 2)


class WeeklySummaryReportViewTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username='ADM001', staff_id='ADM001',
            password='AdmPass123!', role='admin',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
        )
        self.url = '/staff/reports/weekly/'

    def test_doctor_cannot_access(self):
        self.client.login(username='DOC001', password='DocPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_admin_gets_report(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('week_days', response.context)

    def test_week_days_has_seven_entries(self):
        self.client.login(username='ADM001', password='AdmPass123!')
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['week_days']), 7)


# ==========================================================
# API: available slots
# ==========================================================
class GetAvailableSlotsApiTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=1101)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
            first_name='Naledi', last_name='Naidoo',
        )
        self.other_patient_sa = make_sa_id(seed=1102)
        self.other_patient = User.objects.create_user(
            username=self.other_patient_sa, sa_id_number=self.other_patient_sa,
            password='PatPass123!', role='patient',
        )

        self.url = '/api/available-slots/'
        self.future_date = (timezone.now().date() + timedelta(days=7)).isoformat()

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url, {
            'doctor_id': self.doctor.id,
            'date': self.future_date,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_missing_doctor_id_returns_400(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url, {'date': self.future_date})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_missing_date_returns_400(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url, {'doctor_id': self.doctor.id})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_nonexistent_doctor_returns_404(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url, {
            'doctor_id': 999999,
            'date': self.future_date,
        })
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.json())

    def test_valid_request_returns_17_slots(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url, {
            'doctor_id': self.doctor.id,
            'date': self.future_date,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('slots', data)
        self.assertEqual(len(data['slots']), 17)
        first = data['slots'][0]
        self.assertIn('time', first)
        self.assertIn('available', first)
        self.assertEqual(first['time'], '09:00')

    def test_booked_slot_shows_unavailable(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            appointment_date=self.future_date,
            appointment_time='10:00',
            reason_for_visit='Booked',
            status='pending',
        )
        response = self.client.get(self.url, {
            'doctor_id': self.doctor.id,
            'date': self.future_date,
        })
        self.assertEqual(response.status_code, 200)
        slots = {s['time']: s['available'] for s in response.json()['slots']}
        self.assertFalse(slots['10:00'])
        self.assertTrue(slots['09:00'])

    def test_blocked_slot_shows_unavailable(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        BlockedSlot.objects.create(
            doctor=self.doctor,
            blocked_date=self.future_date,
            blocked_time='11:00',
            reason='Lunch',
        )
        response = self.client.get(self.url, {
            'doctor_id': self.doctor.id,
            'date': self.future_date,
        })
        self.assertEqual(response.status_code, 200)
        slots = {s['time']: s['available'] for s in response.json()['slots']}
        self.assertFalse(slots['11:00'])
        self.assertTrue(slots['09:00'])


# ==========================================================
# API: available doctors
# ==========================================================
class GetAvailableDoctorsApiTests(TestCase):

    def setUp(self):
        self.patient_sa = make_sa_id(seed=1111)

        self.patient = User.objects.create_user(
            username=self.patient_sa, sa_id_number=self.patient_sa,
            password='PatPass123!', role='patient',
        )
        self.doctor = User.objects.create_user(
            username='DOC001', staff_id='DOC001',
            password='DocPass123!', role='doctor',
            first_name='Naledi', last_name='Naidoo',
            specialization='Cardiology',
        )

        self.url = '/api/available-doctors/'
        self.future_date = (timezone.now().date() + timedelta(days=7)).isoformat()

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url, {'date': self.future_date})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_missing_date_returns_400(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_valid_request_returns_doctor_list(self):
        self.client.login(username=self.patient_sa, password='PatPass123!')
        response = self.client.get(self.url, {'date': self.future_date})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('doctors', data)
        self.assertEqual(len(data['doctors']), 1)
        doctor = data['doctors'][0]
        self.assertEqual(doctor['id'], self.doctor.id)
        self.assertIn('name', doctor)
        self.assertEqual(doctor['specialization'], 'Cardiology')
        self.assertIn('available', doctor)
        self.assertTrue(doctor['available'])