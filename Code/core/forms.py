from datetime import datetime

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import connection
from .models import (
    User, Appointment, Queue, Prescription, MedicalRecord,
    ClinicalNote, Referral, FollowUp,
)


# ==========================================================
# ============ SA ID VALIDATION HELPER =====================
# ==========================================================

def validate_sa_id_structure(sa_id, form_dob=None):
    """
    Validate a South African ID number:
      - 13 digits
      - YYMMDD is a real calendar date
      - (optional) YYMMDD matches form_dob within 1 day
      - citizenship digit (position 11, index 10) is 0 or 1
      - Luhn checksum on the last digit

    Returns (is_valid: bool, error_message: str | None).
    """
    if not sa_id or not sa_id.isdigit() or len(sa_id) != 13:
        return False, 'SA ID Number must be exactly 13 digits.'

    # --- 1. Date portion ---
    yy = int(sa_id[0:2])
    mm = int(sa_id[2:4])
    dd = int(sa_id[4:6])

    current_yy = datetime.now().year % 100
    century = 2000 if yy <= current_yy else 1900
    year = century + yy

    try:
        dob_from_id = datetime(year, mm, dd).date()
    except ValueError:
        return False, (
            'The first 6 digits of a SA ID encode a birth date (YYMMDD). '
            'That date does not exist.'
        )

    # --- 2. Cross-check with form's date_of_birth (if provided) ---
    if form_dob:
        delta = abs((dob_from_id - form_dob).days)
        if delta > 1:  # 1-day tolerance for timezone/edge cases
            return False, (
                f"The date of birth encoded in the ID ({dob_from_id}) "
                f"does not match the date of birth you entered ({form_dob})."
            )

    # --- 3. Citizenship digit ---
    citizen = int(sa_id[10])
    if citizen not in (0, 1):
        return False, (
            'The 11th digit of a SA ID must be 0 (citizen) or 1 '
            '(permanent resident).'
        )

    # --- 4. Luhn checksum ---
    total = 0
    for i in range(12):
        d = int(sa_id[11 - i])
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    expected = (10 - (total % 10)) % 10
    if expected != int(sa_id[12]):
        return False, (
            'The ID number failed the South African checksum test. '
            'Please double-check the digits.'
        )

    return True, None


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
        fields = ['sa_id_number', 'first_name', 'last_name', 'email',
                  'phone_number', 'date_of_birth', 'password1', 'password2']

    def clean_sa_id_number(self):
        sa_id = self.cleaned_data.get('sa_id_number', '').strip()
        if not sa_id:
            raise ValidationError('SA ID Number is required for patients.')
        if not sa_id.isdigit():
            raise ValidationError('SA ID Number must contain only digits.')
        if len(sa_id) != 13:
            raise ValidationError('SA ID Number must be exactly 13 digits.')

        # Pull DOB from the form if the user already entered it.
        # Note: clean_<field> order isn't guaranteed, so if DOB hasn't
        # been cleaned yet, self.cleaned_data may not have it — we fall
        # back to None and let the form-level clean() catch mismatches.
        form_dob = self.cleaned_data.get('date_of_birth')

        is_valid, msg = validate_sa_id_structure(sa_id, form_dob=form_dob)
        if not is_valid:
            raise ValidationError(msg)

        if User.objects.filter(sa_id_number=sa_id).exists():
            raise ValidationError('A user with this SA ID already exists.')
        return sa_id

    def clean_email(self):
        import re
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
        # FIX 2: prevent duplicate phone numbers (fake IDs often come
        # with fake/reused phone numbers too).
        if User.objects.filter(phone_number=phone).exists():
            raise ValidationError('A user with this phone number already exists.')
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

    def clean(self):
        """
        Form-level cross-check: the DOB encoded in the SA ID must match
        the date_of_birth field. Doing this here guarantees both fields
        have been cleaned regardless of field order.
        """
        cleaned = super().clean()
        sa_id = cleaned.get('sa_id_number')
        dob = cleaned.get('date_of_birth')
        if sa_id and dob:
            is_valid, msg = validate_sa_id_structure(sa_id, form_dob=dob)
            if not is_valid:
                # Only surface the DOB-mismatch error here; other errors
                # were already raised in clean_sa_id_number.
                if 'date of birth' in msg.lower():
                    raise ValidationError(msg)
        return cleaned

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
    sa_id_number = forms.CharField(
        max_length=13, min_length=13, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0000000000000'}),
        help_text='Enter your 13-digit SA ID (for records only)'
    )
    first_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'}))
    last_name = forms.CharField(required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Surname'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'your@email.com'}))
    phone_number = forms.CharField(max_length=15, required=True, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'}))
    role = forms.ChoiceField(
        choices=[('doctor', 'Doctor'), ('nurse', 'Nurse'), ('receptionist', 'Receptionist'), ('admin', 'Administrator')],
        required=True, widget=forms.Select(attrs={'class': 'form-control'})
    )
    specialization = forms.CharField(
        max_length=100, required=False,
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

        # Staff form has no date_of_birth field, so no DOB cross-check here.
        is_valid, msg = validate_sa_id_structure(sa_id, form_dob=None)
        if not is_valid:
            raise ValidationError(msg)

        if User.objects.filter(sa_id_number=sa_id).exists():
            raise ValidationError('A user with this SA ID already exists.')
        return sa_id

    def clean_email(self):
        import re
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
        if User.objects.filter(phone_number=phone).exists():
            raise ValidationError('A user with this phone number already exists.')
        return phone

    def clean_password1(self):
        password = self.cleaned_data.get('password1', '')
        if len(password) < 8:
            raise ValidationError('Password must be at least 8 characters.')
        return password

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get('role')
        specialization = (cleaned.get('specialization') or '').strip()
        if role == 'doctor' and not specialization:
            self.add_error('specialization', 'Specialization is required for doctors.')
        return cleaned

    def generate_staff_id(self, role):
        prefixes = {'doctor': 'DOC', 'nurse': 'NUR', 'receptionist': 'R', 'admin': 'ADM'}
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
            except Exception:
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
        self.fields['doctor'].label_from_instance = self._doctor_label

    def _doctor_label(self, obj):
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
# ============ RESCHEDULE APPOINTMENT FORM =================
# ==========================================================

class RescheduleAppointmentForm(forms.ModelForm):
    """
    Used to move an existing appointment to a new date/time.
    The doctor is fixed (inherited from the original appointment)
    so it is NOT a form field.
    """
    appointment_date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    appointment_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    reason_for_visit = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )

    class Meta:
        model = Appointment
        fields = ['appointment_date', 'appointment_time', 'reason_for_visit']

    def __init__(self, *args, **kwargs):
        self.appointment = kwargs.pop('appointment', None)
        super().__init__(*args, **kwargs)

        if self.appointment:
            if not self.is_bound:
                self.fields['appointment_date'].initial = self.appointment.appointment_date
                self.fields['appointment_time'].initial = self.appointment.appointment_time
                self.fields['reason_for_visit'].initial = self.appointment.reason_for_visit

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get('appointment_date')
        time = cleaned.get('appointment_time')

        if not self.appointment:
            raise ValidationError('Original appointment is missing.')

        if not date or not time:
            return cleaned

        if date < timezone.now().date():
            raise ValidationError('Cannot reschedule to a date in the past.')

        if (date == self.appointment.appointment_date
                and time == self.appointment.appointment_time):
            raise ValidationError(
                'The new date and time are the same as the current appointment.'
            )

        doctor = self.appointment.doctor
        patient = self.appointment.patient

        if Appointment.objects.filter(
            doctor=doctor,
            appointment_date=date,
            appointment_time=time,
            status__in=['confirmed', 'pending'],
        ).exclude(pk=self.appointment.pk).exists():
            raise ValidationError(
                'This doctor is already booked for that time slot. '
                'Please choose another time.'
            )

        if Appointment.objects.filter(
            patient=patient,
            appointment_date=date,
            appointment_time=time,
            status__in=['confirmed', 'pending'],
        ).exclude(pk=self.appointment.pk).exists():
            raise ValidationError(
                'You already have another appointment at that time.'
            )

        with connection.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM blocked_slots "
                "WHERE doctor_id = %s AND blocked_date = %s AND blocked_time = %s",
                [doctor.id, date, time]
            )
            if cur.fetchone()[0] > 0:
                raise ValidationError(
                    'That slot is blocked by the doctor. Pick another time.'
                )

        return cleaned


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
# ============ CLINICAL NOTE FORM ==========================
# ==========================================================

class ClinicalNoteForm(forms.ModelForm):
    class Meta:
        model = ClinicalNote
        fields = ['note_type', 'title', 'content']
        widgets = {
            'note_type': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional — e.g. "Post-op observation"'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Enter nursing note, observation, or progress update...'}),
        }
        labels = {'note_type': 'Note Type', 'title': 'Title (optional)', 'content': 'Note Content'}

    def clean_content(self):
        content = self.cleaned_data.get('content', '').strip()
        if len(content) < 3:
            raise ValidationError('Note content is too short.')
        return content


# ==========================================================
# ============ REFERRAL FORM ===============================
# ==========================================================

class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ['referred_to_doctor', 'referred_to', 'specialty', 'reason', 'clinical_summary', 'urgency']
        widgets = {
            'referred_to_doctor': forms.Select(attrs={'class': 'form-control'}),
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
            'referred_to_doctor': 'Internal doctor (optional)',
            'referred_to': 'Referred To (name or facility)',
            'specialty': 'Specialty',
            'reason': 'Reason for Referral *',
            'clinical_summary': 'Clinical Summary',
            'urgency': 'Urgency',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['referred_to_doctor'].queryset = User.objects.filter(
            role='doctor', is_active=True
        )
        self.fields['referred_to_doctor'].required = False
        self.fields['referred_to_doctor'].label_from_instance = (
            lambda obj: obj.get_doctor_display()
        )
        self.fields['referred_to'].required = False

    def clean(self):
        cleaned = super().clean()
        internal = cleaned.get('referred_to_doctor')
        external = (cleaned.get('referred_to') or '').strip()
        if not internal and not external:
            raise ValidationError(
                'Please pick an internal doctor OR type a name/facility in "Referred To".'
            )
        return cleaned

    def clean_reason(self):
        value = (self.cleaned_data.get('reason') or '').strip()
        if len(value) < 5:
            raise ValidationError('Please give a reason for this referral.')
        return value


# ==========================================================
# ============ PASSWORD / OTP FORMS ========================
# ==========================================================

class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            raise ValidationError('Email address is required.')
        if not User.objects.filter(email=email).exists():
            raise ValidationError('No user found with this email address.')
        return email


class PasswordResetConfirmForm(forms.Form):
    new_password1 = forms.CharField(required=True, min_length=8, widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    new_password2 = forms.CharField(required=True, min_length=8, widget=forms.PasswordInput(attrs={'class': 'form-control'}))

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


# ==========================================================
# ============ FOLLOW-UP FORM ==============================
# ==========================================================

class FollowUpForm(forms.ModelForm):
    class Meta:
        model = FollowUp
        fields = ['original_appointment', 'due_date', 'reason']
        widgets = {
            'original_appointment': forms.Select(attrs={'class': 'form-control'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'e.g. Review blood test results, check wound healing'}),
        }
        labels = {
            'original_appointment': 'Follow-up from which visit?',
            'due_date': 'Follow-up Due Date',
            'reason': 'Reason for Follow-up',
        }

    def __init__(self, *args, **kwargs):
        patient = kwargs.pop('patient', None)
        doctor = kwargs.pop('doctor', None)
        self.doctor = doctor
        super().__init__(*args, **kwargs)

        if patient and doctor:
            qs = Appointment.objects.filter(
                patient=patient, doctor=doctor,
                status__in=['completed', 'confirmed'],
            ).order_by('-appointment_date', '-appointment_time')
            self.fields['original_appointment'].queryset = qs
            self.fields['original_appointment'].label_from_instance = (
                lambda obj: f"{obj.appointment_date} {obj.appointment_time.strftime('%H:%M')} — {obj.reason_for_visit[:50]}"
            )
        elif patient:
            self.fields['original_appointment'].queryset = Appointment.objects.filter(
                patient=patient,
            ).order_by('-appointment_date')

    def clean_due_date(self):
        import holidays
        from django.db import connection
        from django.utils import timezone

        due = self.cleaned_data.get('due_date')
        if not due:
            return due

        if due < timezone.now().date():
            raise forms.ValidationError('Follow-up date cannot be in the past.')

        if self.doctor:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM blocked_slots "
                    "WHERE doctor_id = %s AND blocked_date = %s",
                    [self.doctor.id, due]
                )
                if cur.fetchone()[0] > 0:
                    raise forms.ValidationError(
                        'You have blocked that day. Pick another date.'
                    )

        za_holidays = holidays.SouthAfrica(years=[due.year])
        if due in za_holidays:
            raise forms.ValidationError(
                f"That day is a public holiday ({za_holidays[due]}). Pick another date."
            )

        return due