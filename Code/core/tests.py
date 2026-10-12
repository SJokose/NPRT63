from django.test import TestCase, Client
from .models import User, Patient
from django.contrib.auth.hashers import make_password
from datetime import date


class RegistrationTests(TestCase):

    def setUp(self):
        # Create one existing patient before each test runs
        user = User.objects.create(
            name='Existing',
            surname='Patient',
            email='existing@example.com',
            phone='0800000000',
            passwordhash=make_password('Password123'),
            role='Patient',
            isactive=1,
        )
        Patient.objects.create(
            saidnumber='1111111111111',
            dateofbirth=date(1990, 1, 1),
            userid=user,
            isverified=0,
        )

    def test_duplicate_sa_id_is_rejected(self):
        client = Client()
        response = client.post('/register/', {
            'name': 'New',
            'surname': 'Person',
            'email': 'new@example.com',
            'phone': '0811111111',
            'sa_id': '1111111111111',  # same SA ID as setUp patient
            'dob': '1995-05-05',
            'password': 'AnotherPass1',
            'confirm_password': 'AnotherPass1',
        })

        # The duplicate should NOT create a second patient
        count = Patient.objects.filter(saidnumber='1111111111111').count()
        self.assertEqual(count, 1)

class LoginTests(TestCase):

    def setUp(self):
        user = User.objects.create(
            name='Login',
            surname='Tester',
            email='logintest@example.com',
            phone='0822222222',
            passwordhash=make_password('CorrectPass1'),
            role='Patient',
            isactive=1,
        )
        Patient.objects.create(
            saidnumber='2222222222222',
            dateofbirth=date(1985, 3, 3),
            userid=user,
            isverified=0,
        )

    def test_wrong_password_is_rejected(self):
        client = Client()
        response = client.post('/login/', {
            'sa_id': '2222222222222',
            'password': 'WrongPassword',
        })
        # Should show the login page again with an error, not redirect to dashboard
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_correct_password_logs_in(self):
        client = Client()
        response = client.post('/login/', {
            'sa_id': '2222222222222',
            'password': 'CorrectPass1',
        })
        # Should redirect to dashboard on success
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')
        
class AppointmentBookingTests(TestCase):

    def setUp(self):
        from .models import Staff, Doctor
        from datetime import date

        # Create a patient
        patient_user = User.objects.create(
            name='Booking',
            surname='Tester',
            email='bookingtest@example.com',
            phone='0833333333',
            passwordhash=make_password('BookPass1'),
            role='Patient',
            isactive=1,
        )
        self.patient = Patient.objects.create(
            saidnumber='3333333333333',
            dateofbirth=date(1992, 6, 6),
            userid=patient_user,
            isverified=0,
        )

        # Create a doctor
        doctor_user = User.objects.create(
            name='Test',
            surname='Doctor',
            email='testdoctor@example.com',
            phone='0844444444',
            passwordhash=make_password('DocPass1'),
            role='Doctor',
            isactive=1,
        )
        staff = Staff.objects.create(
            staffid='TESTDOC01',
            department='General',
            hiredate=date.today(),
            userid=doctor_user,
        )
        self.doctor = Doctor.objects.create(
            specialization='General Practice',
            licensenumber='LIC999',
            staffid=staff,
        )

    def test_booking_creates_appointment_and_sms_log(self):
        from .models import Appointment, Smslog

        client = Client()
        # Log the patient in first
        client.post('/login/', {'sa_id': '3333333333333', 'password': 'BookPass1'})

        # Book an appointment
        client.post('/book/', {
            'doctor': self.doctor.doctorid,
            'department': 'General',
            'appointment_date': '2026-12-01',
            'appointment_time': '10:00',
        })

        appointment_exists = Appointment.objects.filter(patientid=self.patient, doctorid=self.doctor).exists()
        self.assertTrue(appointment_exists)

        sms_exists = Smslog.objects.filter(phonenumber='0833333333', type='Confirmation').exists()
        self.assertTrue(sms_exists)
        
class DoubleBookingTests(TestCase):

    def setUp(self):
        from .models import Staff, Doctor, Appointment
        from datetime import date

        patient_user = User.objects.create(
            name='Double',
            surname='Booker',
            email='doublebooker@example.com',
            phone='0855555555',
            passwordhash=make_password('DoublePass1'),
            role='Patient',
            isactive=1,
        )
        self.patient = Patient.objects.create(
            saidnumber='4444444444444',
            dateofbirth=date(1988, 8, 8),
            userid=patient_user,
            isverified=0,
        )

        doctor_user = User.objects.create(
            name='Busy',
            surname='Doc',
            email='busydoc@example.com',
            phone='0866666666',
            passwordhash=make_password('DocPass1'),
            role='Doctor',
            isactive=1,
        )
        staff = Staff.objects.create(
            staffid='BUSYDOC01',
            department='General',
            hiredate=date.today(),
            userid=doctor_user,
        )
        self.doctor = Doctor.objects.create(
            specialization='General Practice',
            licensenumber='LIC888',
            staffid=staff,
        )

        # Pre-existing appointment already occupying this slot
        Appointment.objects.create(
            datetime='2026-12-15 09:00',
            status='Booked',
            colourcode='Red',
            department='General',
            patientid=self.patient,
            doctorid=self.doctor,
        )

    def test_double_booking_is_rejected(self):
        from .models import Appointment

        client = Client()
        client.post('/login/', {'sa_id': '4444444444444', 'password': 'DoublePass1'})

        client.post('/book/', {
            'doctor': self.doctor.doctorid,
            'department': 'General',
            'appointment_date': '2026-12-15',
            'appointment_time': '09:00',
        })

        # Should still only be ONE appointment for this doctor at this exact time
        count = Appointment.objects.filter(
            doctorid=self.doctor,
            datetime='2026-12-15 09:00',
        ).count()
        self.assertEqual(count, 1)
        