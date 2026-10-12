from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import User, Appointment, Queue, Prescription, MedicalRecord, ClinicalNote, Referral
import re


# ==========================================================
# ============ AUTHENTICATION FORMS ========================
# ==========================================================

class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SA ID / Staff ID'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )


# ==========================================================
# ============ PATIENT REGISTRATION ========================
# ==========================================================

class PatientRegistrationForm(UserCreationForm):
    sa_id_number = forms.CharField(
        max_length=13, min_length=13, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0000000000000'}),
        help_text='Enter your 13-digit South African ID number'
    )
    first_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}))
    last_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Surname'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'your@email.com'}))
    phone_number = forms.CharField(max_length=15, required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'}))
    date_of_birth = forms.DateField(required=True, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    password1 = forms.CharField(required=True, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Minimum 8 characters'}))
    password2 = forms.CharField(required=True, widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}))

    class Meta:
        model = User
        fields = ['sa_id_number', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth', 'password1', 'password2']

    def clean_sa_id_number(self):
        sa_id = self.cleaned_data.get('sa_id_number', '').strip()
        if not sa_id:
            raise ValidationError('SA ID Number is required for patients.')
        if not sa_id.isdigit():
            raise ValidationError('SA ID Number must contain only digits.')
        if len(sa_id) != 13:
            raise ValidationError('SA ID Number must be exactly 13 digits.')
        if not self.validate_sa_id(sa_id):
            raise ValidationError('Invalid SA ID Number. Please check your ID.')
        if User.objects.filter(sa_id_number=sa_id).exists():
            raise ValidationError('A user with this SA ID already exists.')
        return sa_id

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            raise ValidationError('Email address is required.')
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise ValidationError('Please enter a valid email address.')
        if User.objects.filter(email=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number', '').strip()
        if not phone:
            raise ValidationError('Phone number is required.')
        if not phone.isdigit():
            raise ValidationError('Phone number must contain only digits.')
        if len(phone) < 10 or len(phone) > 15:
            raise ValidationError('Phone number must be between 10 and 15 digits.')
        return phone

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get('date_of_birth')
        if not dob:
            raise ValidationError('Date of birth is required.')
        if dob >= timezone.now().date():
            raise ValidationError('Date of birth must be in the past.')
        age = (timezone.now().date() - dob).days // 365
        if age < 1:
            raise ValidationError('Date of birth must be at least 1 year ago.')
        return dob

    def clean_password1(self):
        password = self.cleaned_data.get('password1', '')
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters long.')
        common_passwords = ['password', '12345678', 'qwerty123', 'admin123', 'password123']
        if password.lower() in common_passwords:
            raise ValidationError('Password is too common. Please choose a stronger password.')
        return password

    def validate_sa_id(self, sa_id):
        try:
            if not sa_id.isdigit() or len(sa_id) != 13:
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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['sa_id_number']
        user.sa_id_number = self.cleaned_data['sa_id_number']
        user.phone_number = self.cleaned_data['phone_number']
        user.date_of_birth = self.cleaned_data['date_of_birth']
        user.role = 'patient'
        user.is_active = True
        if commit:
            user.save()
        return user


# ==========================================================
# ============ STAFF REGISTRATION ==========================
# ==========================================================

class StaffRegistrationForm(UserCreationForm):
    """Staff registration — auto-generates Staff ID (DOC001, NUR001, R001, ADM001)"""
    sa_id_number = forms.CharField(
        max_length=13,
        min_length=13,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0000000000000'}),
        help_text='Enter your 13-digit SA ID (for records only)'
    )
    first_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Surname'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'your@email.com'})
    )
    phone_number = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'})
    )
    role = forms.ChoiceField(
        choices=[
            ('doctor', 'Doctor'),
            ('nurse', 'Nurse'),
            ('receptionist', 'Receptionist'),
            ('admin', 'Administrator')
        ],
        required=True,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    specialization = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Cardiology'}),
        help_text='Required for doctors only'
    )

    class Meta:
        model = User
        fields = ['sa_id_number', 'first_name', 'last_name', 'email', 'phone_number',
                  'role', 'specialization', 'password1', 'password2']

    def clean_sa_id_number(self):
        sa_id = self.cleaned_data.get('sa_id_number', '').strip()
        if not sa_id:
            raise ValidationError('SA ID Number is required.')
        if not sa_id.isdigit():
            raise ValidationError('SA ID Number must contain only digits.')
        if len(sa_id) != 13:
            raise ValidationError('SA ID Number must be exactly 13 digits.')
        if not self.validate_sa_id(sa_id):
            raise ValidationError('Invalid SA ID Number.')
        if User.objects.filter(sa_id_number=sa_id).exists():
            raise ValidationError('A user with this SA ID already exists.')
        return sa_id

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if User.objects.filter(email=email).exists():
            raise ValidationError('A user with this email already exists.')
        return email

    def clean_password1(self):
        password = self.cleaned_data.get('password1', '')
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters.')
        return password

    def validate_sa_id(self, sa_id):
        try:
            if not sa_id.isdigit() or len(sa_id) != 13:
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

    def generate_staff_id(self, role):
        """Generate DOC001, NUR001, R001, ADM001"""
        prefixes = {
            'doctor': 'DOC',
            'nurse': 'NUR',
            'receptionist': 'R',
            'admin': 'ADM',
        }
        prefix = prefixes.get(role, 'STF')

        existing = User.objects.filter(
            staff_id__startswith=prefix
        ).exclude(staff_id__isnull=True).values_list('staff_id', flat=True)

        max_num = 0
        for sid in existing:
            try:
                num_part = sid.replace(prefix, '')
                num = int(num_part) if num_part.isdigit() else 0
                if num > max_num:
                    max_num = num
            except:
                continue

        next_num = max_num + 1

        if prefix == 'R':
            return f"R{next_num:03d}"
        return f"{prefix}{next_num:03d}"

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data['role']
        user.sa_id_number = self.cleaned_data['sa_id_number']
        user.role = role
        user.phone_number = self.cleaned_data['phone_number']

        if role == 'doctor':
            user.specialization = self.cleaned_data.get('specialization', '')

        # Auto-generate permanent Staff ID
        user.staff_id = self.generate_staff_id(role)
        user.username = user.staff_id

        user.is_active = True
        if commit:
            user.save()
        return user


# ==========================================================
# ============ USER EDIT FORM ==============================
# ==========================================================

class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'role', 'specialization', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'specialization': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==========================================================
# ============ APPOINTMENT FORM ============================
# ==========================================================

class AppointmentForm(forms.ModelForm):
    doctor = forms.ModelChoiceField(
        queryset=User.objects.filter(role='doctor', is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        empty_label='Select a doctor...'
    )
    appointment_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    appointment_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    reason_for_visit = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )

    class Meta:
        model = Appointment
        fields = ['doctor', 'appointment_date', 'appointment_time', 'reason_for_visit']

    def __init__(self, *args, **kwargs):
        self.patient = kwargs.pop('patient', None)
        super().__init__(*args, **kwargs)
        # Show doctor as "Dr. S. Nkosi" in dropdown
        self.fields['doctor'].label_from_instance = self._doctor_label

    def _doctor_label(self, obj):
        """Safe doctor label — 'Dr. S. Nkosi' format"""
        if hasattr(obj, 'get_doctor_display'):
            return obj.get_doctor_display()
        if obj.first_name:
            initial = obj.first_name[0].upper() + '.'
            return f"Dr. {initial} {obj.last_name}"
        return f"Dr. {obj.last_name}"

    def clean(self):
        cleaned_data = super().clean()
        doctor = cleaned_data.get('doctor')
        date = cleaned_data.get('appointment_date')
        time = cleaned_data.get('appointment_time')

        if not doctor:
            raise ValidationError('Please select a doctor.')
        if not date:
            raise ValidationError('Please select a date.')
        if not time:
            raise ValidationError('Please select a time.')

        if doctor and date and time:
            if Appointment.objects.filter(
                doctor=doctor, appointment_date=date,
                appointment_time=time, status__in=['confirmed', 'pending']
            ).exists():
                raise ValidationError('This time slot is already booked. Please choose another time.')
            if date < timezone.now().date():
                raise ValidationError('Cannot book appointments in the past.')

        return cleaned_data


# ==========================================================
# ============ QUEUE / PRESCRIPTION / MEDICAL ==============
# ==========================================================

class QueueForm(forms.ModelForm):
    patient = forms.ModelChoiceField(
        queryset=User.objects.filter(role='patient', is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}), empty_label='Select a patient...')
    doctor = forms.ModelChoiceField(
        queryset=User.objects.filter(role='doctor', is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'}), empty_label='Select a doctor...')

    class Meta:
        model = Queue
        fields = ['patient', 'doctor']


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ['medication_name', 'dosage', 'frequency', 'duration', 'instructions', 'expiry_date']
        widgets = {
            'medication_name': forms.TextInput(attrs={'class': 'form-control'}),
            'dosage': forms.TextInput(attrs={'class': 'form-control'}),
            'frequency': forms.TextInput(attrs={'class': 'form-control'}),
            'duration': forms.TextInput(attrs={'class': 'form-control'}),
            'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ['diagnosis', 'treatment_plan', 'notes', 'blood_pressure', 'heart_rate', 'temperature', 'weight', 'height']
        widgets = {
            'diagnosis': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'treatment_plan': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'blood_pressure': forms.TextInput(attrs={'class': 'form-control'}),
            'heart_rate': forms.NumberInput(attrs={'class': 'form-control'}),
            'temperature': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'height': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


# ==========================================================
# ============ NEW: CLINICAL NOTE FORM =====================
# ==========================================================

class ClinicalNoteForm(forms.ModelForm):
    class Meta:
        model = ClinicalNote
        fields = ['note_type', 'title', 'content']
        widgets = {
            'note_type': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional — e.g. "Post-op observation"',
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Enter nursing note, observation, or progress update...',
            }),
        }
        labels = {
            'note_type': 'Note Type',
            'title': 'Title (optional)',
            'content': 'Note Content',
        }

    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 3:
            raise ValidationError('Note content is too short.')
        return content


# ==========================================================
# ============ NEW: REFERRAL FORM ==========================
# ==========================================================

class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ['referred_to', 'specialty', 'reason', 'clinical_summary', 'urgency']
        widgets = {
            'referred_to': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Dr. Naidoo — Cardiology, or Groote Schuur Hospital',
            }),
            'specialty': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Cardiology, Orthopaedics, Oncology',
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Why is the patient being referred?',
            }),
            'clinical_summary': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Brief summary of history, findings, current treatment...',
            }),
            'urgency': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'referred_to': 'Referred To *',
            'specialty': 'Specialty',
            'reason': 'Reason for Referral *',
            'clinical_summary': 'Clinical Summary',
            'urgency': 'Urgency',
        }

    def clean_referred_to(self):
        value = self.cleaned_data.get('referred_to', '').strip()
        if len(value) < 2:
            raise ValidationError('Please enter the specialist or facility name.')
        return value

    def clean_reason(self):
        value = self.cleaned_data.get('reason', '').strip()
        if len(value) < 5:
            raise ValidationError('Please give a reason for this referral.')
        return value


# ==========================================================
# ============ PASSWORD / OTP FORMS ========================
# ==========================================================

class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'}))

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            raise ValidationError('Email address is required.')
        if not User.objects.filter(email=email).exists():
            raise ValidationError('No user found with this email address.')
        return email


class PasswordResetConfirmForm(forms.Form):
    new_password1 = forms.CharField(required=True, min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    new_password2 = forms.CharField(required=True, min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('new_password1')
        p2 = cleaned_data.get('new_password2')
        if p1 and p2 and p1 != p2:
            raise ValidationError('Passwords do not match.')
        return cleaned_data


class OTPVerificationForm(forms.Form):
    otp_code = forms.CharField(max_length=6, min_length=6, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter 6-digit OTP'}))

    def clean_otp_code(self):
        otp = self.cleaned_data.get('otp_code', '').strip()
        if not otp:
            raise ValidationError('OTP code is required.')
        if not otp.isdigit():
            raise ValidationError('OTP must contain only digits.')
        if len(otp) != 6:
            raise ValidationError('OTP must be exactly 6 digits.')
        return otp