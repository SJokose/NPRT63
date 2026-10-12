from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import connection, DatabaseError
from django.db.models import Q, Count, Sum, Max
from django.utils import timezone
import random
from .tips import HEALTH_TIPS
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from .models import (
    User, Appointment, Queue, Prescription, MedicalRecord,
    Notification, AuditLog, ClinicalNote, Referral, FollowUp,
)
from .forms import (
    PatientRegistrationForm, StaffRegistrationForm, LoginForm,
    AppointmentForm, UserEditForm, QueueForm, PrescriptionForm,
    MedicalRecordForm, PasswordResetRequestForm, PasswordResetConfirmForm,
    OTPVerificationForm, ClinicalNoteForm, ReferralForm, FollowUpForm,
    RescheduleAppointmentForm,
)
from .utils import generate_otp, send_otp_sms, send_sms_reminder, validate_sa_id
import csv
import json
import holidays
from datetime import datetime, timedelta
from functools import wraps


# ============ Helper Functions ============

def log_audit(request, action, model_name, object_id=None, changes=None):
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        model_name=model_name,
        object_id=object_id,
        changes=changes,
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )


def call_sp_book_appointment(doctor_id, patient_id, appt_date, appt_time, duration, reason):
    try:
        with connection.cursor() as cur:
            cur.callproc(
                'sp_book_appointment',
                [doctor_id, patient_id, appt_date, appt_time, duration, reason or '', 0]
            )
            cur.execute("SELECT @_sp_book_appointment_6")
            row = cur.fetchone()
            return row[0] if row else None
    except DatabaseError as e:
        msg = e.args[1] if len(e.args) > 1 else str(e)
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', errors='replace')
        raise ValueError(msg)


def call_sp_reschedule_appointment(appointment_id, new_date, new_time, reason):
    try:
        with connection.cursor() as cur:
            cur.callproc(
                'sp_reschedule_appointment',
                [appointment_id, new_date, new_time, reason or '', 0]
            )
            cur.execute("SELECT @_sp_reschedule_appointment_4")
            row = cur.fetchone()
            return row[0] if row else None
    except DatabaseError as e:
        msg = e.args[1] if len(e.args) > 1 else str(e)
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', errors='replace')
        raise ValueError(msg)


def call_sp_cancel_appointment(appointment_id, reason):
    try:
        with connection.cursor() as cur:
            cur.callproc('sp_cancel_appointment', [appointment_id, reason or ''])
    except DatabaseError as e:
        msg = e.args[1] if len(e.args) > 1 else str(e)
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', errors='replace')
        raise ValueError(msg)


def is_public_holiday(check_date):
    za_holidays = holidays.SouthAfrica(years=[check_date.year])
    if check_date in za_holidays:
        return True, za_holidays[check_date]
    return False, None


# ============ Role Check Helpers ============

def _dashboard_for(user):
    if user.role == 'patient':
        return redirect('core:patient_dashboard')
    elif user.role == 'nurse':
        return redirect('core:nurse_dashboard')
    else:
        return redirect('core:staff_dashboard')


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect('core:login')
            if user.role not in allowed_roles:
                messages.warning(
                    request,
                    "You don't have permission to view that page. "
                    "If you think this is a mistake, please contact an administrator."
                )
                return _dashboard_for(user)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


# ============ Role Check Decorators ============

def is_staff_member(user):
    return user.is_authenticated and user.role in ['doctor', 'nurse', 'receptionist', 'admin']

def is_admin(user):
    return user.is_authenticated and user.role == 'admin'

def is_admin_or_receptionist(user):
    return user.is_authenticated and user.role in ['admin', 'receptionist']

def is_doctor(user):
    return user.is_authenticated and user.role == 'doctor'

def is_nurse(user):
    return user.is_authenticated and user.role == 'nurse'

def is_patient(user):
    return user.is_authenticated and user.role == 'patient'

def is_doctor_or_nurse(user):
    return user.is_authenticated and user.role in ['doctor', 'nurse']

def is_doctor_or_nurse_or_admin(user):
    return user.is_authenticated and user.role in ['doctor', 'nurse', 'admin']

def is_receptionist_or_admin(user):
    return user.is_authenticated and user.role in ['receptionist', 'admin']


# ============ Authentication Views ============

def home(request):
    return render(request, 'home.html')


def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = None
            try:
                if len(username) == 13 and username.isdigit():
                    user = User.objects.get(sa_id_number=username)
                else:
                    user = User.objects.get(staff_id=username.upper())
            except User.DoesNotExist:
                pass

            if user:
                if user.role != 'patient':
                    authenticated_user = authenticate(request, username=user.username, password=password)
                    if not authenticated_user:
                        messages.error(request, 'Invalid password.')
                        return render(request, 'login.html', {'form': form})

                otp = generate_otp()
                user.otp_code = otp
                user.otp_created_at = timezone.now()
                user.save()

                if send_otp_sms(user.phone_number, otp):
                    request.session['user_id'] = user.id
                    messages.success(request, f'OTP sent to {user.phone_number}.')
                    return redirect('core:verify_otp')
                else:
                    messages.error(request, 'Failed to send OTP. Please try again.')
            else:
                messages.error(request, 'User not found. Please check your ID.')
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})


def verify_otp_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('core:login')
    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp_code']
            if user.otp_code == otp and user.otp_created_at > timezone.now() - timedelta(minutes=10):
                user.is_verified = True
                user.otp_code = None
                user.save()
                login(request, user)
                log_audit(request, 'login', 'User', str(user.id))
                messages.success(request, 'Login successful!')

                if user.role == 'patient':
                    return redirect('core:patient_dashboard')
                elif user.role == 'nurse':
                    return redirect('core:nurse_dashboard')
                elif user.role in ['doctor', 'receptionist', 'admin']:
                    return redirect('core:staff_dashboard')
                else:
                    return redirect('core:home')
            else:
                messages.error(request, 'Invalid or expired OTP. Please try again.')
    else:
        form = OTPVerificationForm()

    return render(request, 'verify_otp.html', {'form': form, 'phone_number': user.phone_number})


def logout_view(request):
    if request.user.is_authenticated:
        log_audit(request, 'logout', 'User', str(request.user.id))
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('core:home')


# ============ Registration ============

@login_required
@role_required('admin')
def register_staff(request):
    if request.method == 'POST':
        form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                messages.success(
                    request,
                    f'✅ Staff registered successfully! '
                    f'Staff ID: {user.staff_id}. '
                    f'They will use this ID to log in.'
                )
                log_audit(request, 'create', 'User', str(user.id),
                          f'Staff registered by admin: {user.staff_id}')
                return redirect('core:user_management')
            except Exception as e:
                messages.error(request, f'Registration error: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f'{field}: {error}')
    else:
        form = StaffRegistrationForm()
    return render(request, 'register_staff.html', {'form': form})


def register_patient(request):
    if request.method == 'POST':
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                messages.success(request, 'Registration successful! Please login with your SA ID.')
                log_audit(request, 'create', 'User', str(user.id), f'Patient registered')
                return redirect('core:login')
            except Exception as e:
                messages.error(request, f'Registration error: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f'{field}: {error}')
    else:
        form = PatientRegistrationForm()
    return render(request, 'register.html', {'form': form})


def forgot_password(request):
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                messages.success(request, 'Password reset link sent to your email.')
                log_audit(request, 'update', 'User', str(user.id), 'Password reset requested')
                return redirect('core:login')
            except User.DoesNotExist:
                messages.error(request, 'No user found with this email address.')
    else:
        form = PasswordResetRequestForm()
    return render(request, 'forgot_password.html', {'form': form})


# ============ Patient Dashboard ============

@login_required
@user_passes_test(is_patient)
def patient_dashboard(request):
    patient = request.user
    total_appointments = Appointment.objects.filter(patient=patient).count()
    completed_visits = Appointment.objects.filter(patient=patient, status='completed').count()
    upcoming_count = Appointment.objects.filter(
        patient=patient,
        status__in=['pending', 'confirmed'],
        appointment_date__gte=timezone.now().date()
    ).count()
    upcoming_appointments = Appointment.objects.filter(
        patient=patient,
        status__in=['pending', 'confirmed'],
        appointment_date__gte=timezone.now().date()
    ).order_by('appointment_date', 'appointment_time')[:5]
    notifications = Notification.objects.filter(user=patient, is_read=False).order_by('-created_at')[:5]

    followup_preview = FollowUp.objects.filter(
        patient=patient,
        status__in=['due', 'scheduled']
    ).order_by('due_date')[:3]

    health_tip = random.choice(HEALTH_TIPS)

    context = {
        'total_appointments': total_appointments,
        'completed_visits': completed_visits,
        'upcoming_count': upcoming_count,
        'patient_id': patient.sa_id_number,
        'upcoming_appointments': upcoming_appointments,
        'notifications': notifications,
        'followup_preview': followup_preview,
        'health_tip': health_tip,
    }
    return render(request, 'patient_dashboard.html', context)


@login_required
@user_passes_test(is_patient)
def my_appointments(request):
    patient = request.user
    appointments = Appointment.objects.filter(patient=patient).order_by('-appointment_date', '-appointment_time')
    context = {
        'appointments': appointments,
        'today': timezone.now().date(),
    }
    return render(request, 'my_appointments.html', context)


# ============ Book Appointment ============

@login_required
@user_passes_test(is_patient)
def book_appointment(request):
    if request.method == 'POST':
        form = AppointmentForm(request.POST, patient=request.user)
        if form.is_valid():
            data = form.cleaned_data
            try:
                appt_id = call_sp_book_appointment(
                    doctor_id=data['doctor'].id,
                    patient_id=request.user.id,
                    appt_date=data['appointment_date'],
                    appt_time=data['appointment_time'],
                    duration=data.get('duration_minutes', 30),
                    reason=data.get('reason_for_visit', ''),
                )
                appointment = Appointment.objects.get(id=appt_id)
                Notification.objects.create(
                    user=request.user,
                    title='Appointment Submitted',
                    message=(
                        f'Your appointment request with {appointment.doctor.get_doctor_display()} '
                        f'on {appointment.appointment_date} is waiting for doctor approval.'
                    ),
                    notification_type='appointment',
                )
                log_audit(request, 'create', 'Appointment', str(appt_id))
                messages.success(request, 'Appointment submitted! Waiting for doctor approval.')
                return redirect('core:my_appointments')
            except ValueError as e:
                messages.error(request, str(e))
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = AppointmentForm(patient=request.user)

    today = timezone.now().date()

    busy_slots = {}
    confirmed_slots = {}
    blocked_slots = {}

    future_appointments = Appointment.objects.filter(
        appointment_date__gte=today,
        status__in=['pending', 'confirmed']
    ).select_related('doctor')

    for appt in future_appointments:
        key = f"{appt.doctor_id}_{appt.appointment_date.strftime('%Y-%m-%d')}"
        time_str = appt.appointment_time.strftime('%H:%M')
        if appt.status == 'confirmed':
            confirmed_slots.setdefault(key, []).append(time_str)
        else:
            busy_slots.setdefault(key, []).append(time_str)

    with connection.cursor() as cur:
        cur.execute(
            "SELECT doctor_id, blocked_date, blocked_time, reason "
            "FROM blocked_slots "
            "WHERE blocked_date >= CURDATE() "
            "AND blocked_date <= DATE_ADD(CURDATE(), INTERVAL 6 MONTH)"
        )
        for doctor_id, blocked_date, blocked_time, reason in cur.fetchall():
            key = f"{doctor_id}_{blocked_date.strftime('%Y-%m-%d')}"
            time_str = blocked_time.strftime('%H:%M')
            blocked_slots.setdefault(key, []).append(time_str)

    za_holidays = holidays.SouthAfrica(years=[today.year, today.year + 1])
    holidays_dict = {d.isoformat(): name for d, name in za_holidays.items()}

    return render(request, 'book_appointment.html', {
        'form': form,
        'busy_slots_json': json.dumps(busy_slots),
        'confirmed_slots_json': json.dumps(confirmed_slots),
        'blocked_slots_json': json.dumps(blocked_slots),
        'holidays_json': json.dumps(holidays_dict),
    })


# ============ Cancel Appointment ============

@login_required
@user_passes_test(is_patient)
def cancel_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, patient=request.user)

    if request.method == 'POST':
        try:
            call_sp_cancel_appointment(appointment.id, request.POST.get('reason', ''))
            appointment.refresh_from_db()

            Notification.objects.create(
                user=request.user,
                title='Appointment Cancelled',
                message=f'Your appointment with {appointment.doctor.get_doctor_display()} has been cancelled.',
                notification_type='appointment'
            )

            try:
                send_sms_reminder(
                    request.user.phone_number,
                    f"MediSync SA: Your appointment with {appointment.doctor.get_doctor_display()} "
                    f"on {appointment.appointment_date} at {appointment.appointment_time} has been cancelled."
                )
            except Exception as e:
                print(f"[WARN] SMS not sent on cancel: {e}")

            log_audit(request, 'update', 'Appointment', str(appointment.id), 'Cancelled')
            messages.success(request, 'Appointment cancelled successfully.')
        except ValueError as e:
            messages.error(request, str(e))

        return redirect('core:my_appointments')

    return render(request, 'cancel_appointment.html', {'appointment': appointment})


# ============ Reschedule Appointment ============

@login_required
@user_passes_test(is_patient)
def reschedule_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, patient=request.user)

    if appointment.status not in ['pending', 'confirmed']:
        messages.error(request, 'This appointment cannot be rescheduled.')
        return redirect('core:my_appointments')

    if request.method == 'POST':
        form = RescheduleAppointmentForm(request.POST, appointment=appointment)
        if form.is_valid():
            data = form.cleaned_data
            old_date = appointment.appointment_date
            old_time = appointment.appointment_time

            try:
                new_id = call_sp_reschedule_appointment(
                    appointment.id,
                    data['appointment_date'],
                    data['appointment_time'],
                    data.get('reason_for_visit', appointment.reason_for_visit or ''),
                )
                new_appt = Appointment.objects.get(id=new_id)

                Notification.objects.create(
                    user=request.user,
                    title='Appointment Rescheduled',
                    message=(
                        f'Your appointment with {new_appt.doctor.get_doctor_display()} '
                        f'has been moved from {old_date} {old_time} to '
                        f'{new_appt.appointment_date} {new_appt.appointment_time}.'
                    ),
                    notification_type='appointment'
                )

                try:
                    send_sms_reminder(
                        request.user.phone_number,
                        f"MediSync SA: Your appointment with {new_appt.doctor.get_doctor_display()} "
                        f"has been rescheduled to {new_appt.appointment_date} at "
                        f"{new_appt.appointment_time}."
                    )
                except Exception as e:
                    print(f"[WARN] SMS not sent on reschedule: {e}")

                log_audit(request, 'update', 'Appointment', str(new_appt.id), 'Rescheduled')
                messages.success(request, 'Appointment rescheduled successfully.')
                return redirect('core:my_appointments')
            except ValueError as e:
                messages.error(request, str(e))
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f'{field}: {error}')
    else:
        form = RescheduleAppointmentForm(appointment=appointment)

    future_appointments = Appointment.objects.filter(
        doctor=appointment.doctor,
        appointment_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).exclude(id=appointment.id)

    busy_slots = {}
    confirmed_slots = {}
    for appt in future_appointments:
        date_key = appt.appointment_date.strftime('%Y-%m-%d')
        time_str = appt.appointment_time.strftime('%H:%M')
        busy_slots.setdefault(date_key, []).append(time_str)
        if appt.status == 'confirmed':
            confirmed_slots.setdefault(date_key, []).append(time_str)

    blocked_slots = {}
    with connection.cursor() as cur:
        cur.execute(
            "SELECT blocked_date, blocked_time "
            "FROM blocked_slots "
            "WHERE doctor_id = %s AND blocked_date >= CURDATE()",
            [appointment.doctor.id]
        )
        for bdate, btime in cur.fetchall():
            date_key = bdate.strftime('%Y-%m-%d')
            time_str = btime.strftime('%H:%M')
            blocked_slots.setdefault(date_key, []).append(time_str)

    today = timezone.now().date()
    za_holidays = holidays.SouthAfrica(years=[today.year, today.year + 1])
    holidays_dict = {d.isoformat(): name for d, name in za_holidays.items()}

    return render(request, 'reschedule_appointment.html', {
        'form': form,
        'appointment': appointment,
        'busy_slots_json': json.dumps(busy_slots),
        'confirmed_slots_json': json.dumps(confirmed_slots),
        'blocked_slots_json': json.dumps(blocked_slots),
        'holidays_json': json.dumps(holidays_dict),
    })


# ============ Staff Dashboard ============

@login_required
@user_passes_test(is_staff_member)
def staff_dashboard(request):
    user = request.user
    today = timezone.now().date()
    all_patients = User.objects.filter(role='patient', is_active=True).order_by('first_name', 'last_name')
    total_patients = all_patients.count()
    if user.role == 'doctor':
        today_appointments_qs = Appointment.objects.filter(
            doctor=user, appointment_date=today
        ).order_by('appointment_time')
        today_appointments_list = today_appointments_qs
        today_appointments = today_appointments_qs.count()
        completed_today = today_appointments_qs.filter(status='completed').count()
        missed_appointments = Appointment.objects.filter(doctor=user, status='missed').count()
        active_queue = Queue.objects.filter(doctor=user, status__in=['waiting', 'in_progress'])
        pending_appointments = Appointment.objects.filter(
            doctor=user, status='pending'
        ).order_by('appointment_date', 'appointment_time')
        pending_count = pending_appointments.count()
    else:
        today_appointments_qs = Appointment.objects.filter(appointment_date=today)
        today_appointments_list = today_appointments_qs.order_by('appointment_time')
        today_appointments = today_appointments_qs.count()
        completed_today = today_appointments_qs.filter(status='completed').count()
        missed_appointments = Appointment.objects.filter(status='missed').count()
        active_queue = Queue.objects.filter(status__in=['waiting', 'in_progress'])
        pending_appointments = Appointment.objects.filter(
            status='pending'
        ).order_by('appointment_date', 'appointment_time')
        pending_count = pending_appointments.count()
    context = {
        'total_patients': total_patients,
        'all_patients': all_patients,
        'today_appointments': today_appointments,
        'today_appointments_list': today_appointments_list,
        'completed_today': completed_today,
        'missed_appointments': missed_appointments,
        'active_queue': active_queue[:10],
        'pending_appointments': pending_appointments[:10],
        'pending_count': pending_count,
        'user': user,
    }
    return render(request, 'staff_dashboard.html', context)


# ============ Nurse Dashboard ============

@login_required
@user_passes_test(is_nurse)
def nurse_dashboard(request):
    user = request.user
    today = timezone.now().date()
    today_appointments = Appointment.objects.filter(
        appointment_date=today
    ).order_by('appointment_time')
    pending_appointments = Appointment.objects.filter(
        appointment_date=today,
        status__in=['pending', 'confirmed']
    ).order_by('appointment_time')
    active_queue = Queue.objects.filter(
        status__in=['waiting', 'in_progress']
    ).order_by('entered_at')
    total_patients = User.objects.filter(role='patient', is_active=True).count()
    today_count = today_appointments.count()
    completed_today = today_appointments.filter(status='completed').count()
    checked_in = Queue.objects.filter(entered_at__date=today).count()

    my_notes = ClinicalNote.objects.filter(
        author=user
    ).order_by('-created_at')[:10]
    my_notes_count = ClinicalNote.objects.filter(author=user).count()
    notes_today = ClinicalNote.objects.filter(
        author=user, created_at__date=today
    ).count()

    context = {
        'user': user,
        'today_appointments': today_appointments,
        'pending_appointments': pending_appointments,
        'active_queue': active_queue[:10],
        'total_patients': total_patients,
        'today_count': today_count,
        'completed_today': completed_today,
        'checked_in': checked_in,
        'my_notes': my_notes,
        'my_notes_count': my_notes_count,
        'notes_today': notes_today,
    }
    return render(request, 'nurse_dashboard.html', context)


# ============ Nurse Check-In ============

@login_required
@user_passes_test(is_nurse)
def nurse_check_in(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        doctor_id = request.POST.get('doctor_id')
        if not patient_id or not doctor_id:
            messages.error(request, 'Please select both a patient and a doctor.')
            return redirect('core:nurse_check_in')
        patient = get_object_or_404(User, id=patient_id, role='patient')
        doctor = get_object_or_404(User, id=doctor_id, role='doctor')
        queue_count = Queue.objects.filter(doctor=doctor, status='waiting').count() + 1
        queue_number = f"Q{datetime.now().strftime('%y%m%d')}-{queue_count:03d}"
        Queue.objects.create(
            patient=patient,
            doctor=doctor,
            queue_number=queue_number,
            status='waiting'
        )
        log_audit(request, 'create', 'Queue', None,
                  f'Checked in {patient.get_full_name()} → {queue_number}')
        messages.success(request, f'{patient.get_full_name()} checked in — {queue_number}')
        return redirect('core:nurse_check_in')
    all_patients = User.objects.filter(role='patient', is_active=True).order_by('first_name', 'last_name')
    all_doctors = User.objects.filter(role='doctor', is_active=True).order_by('first_name', 'last_name')
    context = {
        'all_patients': all_patients,
        'all_doctors': all_doctors,
    }
    return render(request, 'nurse_check_in.html', context)


# ============ Nurse Record Vitals ============

@login_required
@role_required('doctor', 'nurse')
def nurse_record_vitals(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    if request.method == 'POST':
        vitals_data = {
            'weight': request.POST.get('weight', '').strip(),
            'height': request.POST.get('height', '').strip(),
            'temperature': request.POST.get('temperature', '').strip(),
            'blood_pressure': request.POST.get('blood_pressure', '').strip(),
            'heart_rate': request.POST.get('heart_rate', '').strip(),
            'respiratory_rate': request.POST.get('respiratory_rate', '').strip(),
            'oxygen_saturation': request.POST.get('oxygen_saturation', '').strip(),
            'notes': request.POST.get('notes', '').strip(),
        }
        record = MedicalRecord.objects.create(
            patient=patient,
            created_by=request.user,
            diagnosis='Vitals recorded',
            treatment_plan=json.dumps(vitals_data, indent=2),
            notes=vitals_data['notes'],
        )
        log_audit(request, 'create', 'MedicalRecord', str(record.id),
                  f'Vitals recorded for {patient.get_full_name()}')
        messages.success(request, f'Vitals recorded for {patient.get_full_name()}.')
        return redirect('core:nurse_dashboard')
    return render(request, 'nurse_record_vitals.html', {'patient': patient})


# ============ Nurse Vitals Picker ============

@login_required
@user_passes_test(is_nurse)
def nurse_vitals_picker(request):
    today = timezone.now().date()
    today_patients = User.objects.filter(
        role='patient',
        is_active=True,
        appointments_as_patient__appointment_date=today,
    ).distinct().order_by('first_name', 'last_name')
    other_patients = User.objects.filter(
        role='patient', is_active=True,
    ).exclude(
        id__in=today_patients.values_list('id', flat=True)
    ).order_by('first_name', 'last_name')
    context = {
        'today_patients': today_patients,
        'other_patients': other_patients,
        'today': today,
    }
    return render(request, 'nurse_vitals_picker.html', context)


# ============ User Management ============

@login_required
@role_required('admin')
def user_management(request):
    users = User.objects.all().order_by('-date_joined')
    role_filter = request.GET.get('role', '')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('search', '')
    if role_filter:
        users = users.filter(role=role_filter)
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(sa_id_number__icontains=search_query) |
            Q(staff_id__icontains=search_query)
        )
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    users_page = paginator.get_page(page_number)
    stats = {
        'total': User.objects.count(),
        'patients': User.objects.filter(role='patient').count(),
        'doctors': User.objects.filter(role='doctor').count(),
        'staff': User.objects.filter(role__in=['nurse', 'receptionist', 'admin']).count(),
        'active': User.objects.filter(is_active=True).count(),
        'inactive': User.objects.filter(is_active=False).count(),
    }
    context = {
        'users': users_page,
        'stats': stats,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'search_query': search_query,
    }
    return render(request, 'user_management.html', context)


@login_required
@role_required('admin')
def add_user(request):
    if request.method == 'POST':
        role = request.POST.get('role')
        if role == 'patient':
            form = PatientRegistrationForm(request.POST)
        else:
            form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_audit(request, 'create', 'User', str(user.id), f'User added: {user.get_full_name()}')
            messages.success(request, f'User {user.get_full_name()} added successfully!')
            return redirect('core:user_management')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = PatientRegistrationForm()
    return render(request, 'add_user.html', {'form': form})


@login_required
@role_required('admin')
def edit_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            log_audit(request, 'update', 'User', str(user.id), f'User updated: {user.get_full_name()}')
            messages.success(request, 'User updated successfully!')
            return redirect('core:user_management')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = UserEditForm(instance=user)
    return render(request, 'edit_user.html', {'form': form, 'edit_user': user})


@login_required
@role_required('admin')
def delete_user(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        full_name = user.get_full_name()
        log_audit(request, 'delete', 'User', str(user.id), f'User deleted: {full_name}')
        user.delete()
        messages.success(request, f'User {full_name} deleted successfully!')
        return redirect('core:user_management')
    return render(request, 'delete_user.html', {'delete_user': user})


@login_required
@role_required('admin')
def toggle_user_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_active = not user.is_active
    user.save()
    status = 'activated' if user.is_active else 'deactivated'
    log_audit(request, 'update', 'User', str(user.id), f'User {status}')
    messages.success(request, f'User {user.get_full_name()} has been {status}.')
    return redirect('core:user_management')


@login_required
@role_required('admin')
def bulk_import_users(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        try:
            decoded = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded)
            imported_count = 0
            errors = []
            for idx, row in enumerate(reader, start=2):
                try:
                    role = row.get('role', 'patient')
                    user = User.objects.create_user(
                        username=row.get('username'),
                        first_name=row.get('first_name'),
                        last_name=row.get('last_name'),
                        email=row.get('email'),
                        password=row.get('password', 'ChangeMe123!')
                    )
                    user.role = role
                    if role == 'patient':
                        user.sa_id_number = row.get('sa_id_number')
                    else:
                        user.staff_id = row.get('staff_id')
                    user.phone_number = row.get('phone_number', '')
                    user.save()
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Row {idx}: {str(e)}")
            log_audit(request, 'create', 'User', None, f'Bulk imported {imported_count} users')
            messages.success(request, f'Successfully imported {imported_count} users.')
            if errors:
                messages.warning(request, f'Errors: {", ".join(errors[:5])}')
        except Exception as e:
            messages.error(request, f'Error processing CSV: {str(e)}')
        return redirect('core:user_management')
    return render(request, 'bulk_import.html')


# ============ Queue ============

@login_required
@role_required('receptionist', 'nurse', 'admin')
def manage_queue(request):
    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        doctor_id = request.POST.get('doctor_id')
        if patient_id and doctor_id:
            patient = get_object_or_404(User, id=patient_id, role='patient')
            doctor = get_object_or_404(User, id=doctor_id, role='doctor')
            queue_count = Queue.objects.filter(doctor=doctor, status='waiting').count() + 1
            queue_number = f"Q{datetime.now().strftime('%y%m%d')}-{queue_count:03d}"
            Queue.objects.create(
                patient=patient,
                doctor=doctor,
                queue_number=queue_number,
                status='waiting'
            )
            messages.success(request, f'✅ Patient added to queue: {queue_number}')
        else:
            messages.error(request, 'Please select both a patient and a doctor.')
        return redirect('core:manage_queue')
    today = timezone.now().date()
    active_queues = Queue.objects.filter(
        status__in=['waiting', 'in_progress']
    ).order_by('entered_at')
    completed_queues = Queue.objects.filter(
        status='completed'
    ).order_by('-completed_at')[:20]
    today_count = Queue.objects.filter(entered_at__date=today).count()
    all_patients = User.objects.filter(role='patient', is_active=True).order_by('first_name')
    all_doctors = User.objects.filter(role='doctor', is_active=True).order_by('first_name')
    context = {
        'active_queues': active_queues,
        'completed_queues': completed_queues,
        'today_count': today_count,
        'all_patients': all_patients,
        'all_doctors': all_doctors,
    }
    return render(request, 'manage_queue.html', context)


@login_required
@role_required('receptionist', 'nurse', 'admin')
def update_queue_status(request, queue_id):
    queue = get_object_or_404(Queue, id=queue_id)
    status = request.POST.get('status')
    if status in ['in_progress', 'completed', 'skipped', 'waiting']:
        queue.status = status
        if status == 'in_progress':
            queue.started_at = timezone.now()
        elif status == 'completed':
            queue.completed_at = timezone.now()
        queue.save()
        messages.success(request, f'Queue status updated to {status}.')
    return redirect('core:manage_queue')


# ============ Appointments (Staff) ============

@login_required
@user_passes_test(is_staff_member)
def manage_appointments(request):
    if request.method == 'POST':
        if request.user.role not in ['doctor', 'admin']:
            messages.warning(
                request,
                "Only doctors and administrators can manage appointments."
            )
            return redirect('core:manage_appointments')

        action = request.POST.get('action')
        appointment_id = request.POST.get('appointment_id')
        if appointment_id:
            try:
                appointment = Appointment.objects.get(id=appointment_id)
                if request.user.role == 'doctor' and appointment.doctor != request.user:
                    messages.error(request, 'You can only manage your own appointments.')
                    return redirect('core:manage_appointments')

                if action == 'approve':
                    appointment.status = 'confirmed'
                    appointment.save()
                    Notification.objects.create(
                        user=appointment.patient,
                        title='Appointment Approved',
                        message=f'Your appointment with {appointment.doctor.get_doctor_display()} on {appointment.appointment_date} at {appointment.appointment_time} has been confirmed.',
                        notification_type='appointment'
                    )
                    messages.success(request, 'Appointment approved.')

                elif action == 'complete':
                    appointment.status = 'completed'
                    appointment.save()
                    FollowUp.objects.filter(
                        scheduled_appointment=appointment,
                        status__in=['due', 'scheduled'],
                    ).update(status='completed')
                    messages.success(request, 'Appointment marked as completed.')

                elif action == 'cancel':
                    appointment.status = 'cancelled'
                    appointment.cancelled_at = timezone.now()
                    appointment.save()
                    messages.success(request, 'Appointment cancelled.')

                elif action == 'missed':
                    appointment.status = 'missed'
                    appointment.save()
                    messages.warning(request, 'Appointment marked as missed.')

                log_audit(request, 'update', 'Appointment', str(appointment.id), f'Status: {appointment.status}')
            except Appointment.DoesNotExist:
                messages.error(request, 'Appointment not found.')
        return redirect('core:manage_appointments')

    if request.user.role == 'doctor':
        appointments = Appointment.objects.filter(
            doctor=request.user
        ).order_by('-appointment_date', '-appointment_time')
    else:
        appointments = Appointment.objects.all().order_by('-appointment_date', '-appointment_time')

    status_filter = request.GET.get('status', '')
    if status_filter:
        appointments = appointments.filter(status=status_filter)

    pending_count = appointments.filter(status='pending').count()
    context = {
        'appointments': appointments,
        'today': timezone.now().date(),
        'status_filter': status_filter,
        'pending_count': pending_count,
        'can_manage': request.user.role in ['doctor', 'admin'],
    }
    return render(request, 'manage_appointments.html', context)


# ============ Medical Records ============

@login_required
@role_required('doctor')
def add_medical_record(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')

    appointment = None
    appt_id = request.GET.get('appointment')
    if appt_id and appt_id.isdigit():
        appointment = Appointment.objects.filter(id=appt_id, patient=patient).first()
    if appointment is None and request.user.role == 'doctor':
        appointment = Appointment.objects.filter(
            patient=patient, doctor=request.user, status='confirmed',
            appointment_date=timezone.localdate(),
        ).order_by('appointment_time').first()

    if request.method == 'POST':
        form = MedicalRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.patient = patient
            record.created_by = request.user
            record.appointment = appointment
            record.save()
            log_audit(request, 'create', 'MedicalRecord', str(record.id))
            messages.success(request, 'Medical record added successfully!')
            return redirect('core:view_patient_records', patient_id=patient.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = MedicalRecordForm()
    return render(request, 'add_medical_record.html', {
        'form': form, 'patient': patient, 'appointment': appointment})


@login_required
@role_required('doctor', 'nurse', 'admin')
def view_patient_records(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    records = MedicalRecord.objects.filter(patient=patient).select_related(
        'appointment', 'created_by').order_by('-created_at')
    prescriptions = Prescription.objects.filter(patient=patient).order_by('-prescribed_date')
    appointments = Appointment.objects.filter(patient=patient).order_by('-appointment_date')[:10]
    clinical_notes = ClinicalNote.objects.filter(patient=patient).order_by('-created_at')
    referrals = Referral.objects.filter(patient=patient).order_by('-created_at')
    followups = FollowUp.objects.filter(patient=patient).select_related(
        'doctor', 'original_appointment').order_by('-due_date')
    context = {
        'patient': patient,
        'records': records,
        'prescriptions': prescriptions,
        'appointments': appointments,
        'clinical_notes': clinical_notes,
        'referrals': referrals,
        'followups': followups,
    }
    return render(request, 'view_patient_records.html', context)


# ============ Prescriptions ============

@login_required
@user_passes_test(is_doctor_or_nurse)
def add_prescription(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')

    if request.user.role != 'doctor':
        prescriptions = Prescription.objects.filter(patient=patient).order_by('-prescribed_date')
        context = {
            'patient': patient,
            'prescriptions': prescriptions,
        }
        return render(request, 'add_prescription.html', context)

    if request.method == 'POST':
        form = PrescriptionForm(request.POST)
        if form.is_valid():
            prescription = form.save(commit=False)
            prescription.patient = patient
            prescription.doctor = request.user
            prescription.save()
            Notification.objects.create(
                user=patient,
                title='New Prescription',
                message=f'{request.user.get_doctor_display()} has prescribed {prescription.medication_name} for you.',
                notification_type='prescription'
            )
            log_audit(request, 'create', 'Prescription', str(prescription.id))
            messages.success(request, 'Prescription added successfully!')
            return redirect('core:view_patient_records', patient_id=patient.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = PrescriptionForm()
    return render(request, 'add_prescription.html', {'form': form, 'patient': patient})


# ============ Reports ============

@login_required
@role_required('admin')
def reports_dashboard(request):
    total_patients = User.objects.filter(role='patient').count()
    total_appointments = Appointment.objects.count()
    completed_appointments = Appointment.objects.filter(status='completed').count()
    today = timezone.now().date()
    this_week_start = today - timedelta(days=today.weekday())
    weekly_data = []
    for i in range(7):
        day = this_week_start + timedelta(days=i)
        count = Appointment.objects.filter(appointment_date=day, status='completed').count()
        weekly_data.append({'day': day.strftime('%A'), 'count': count})
    context = {
        'total_patients': total_patients,
        'total_appointments': total_appointments,
        'completed_appointments': completed_appointments,
        'weekly_data': json.dumps(weekly_data),
    }
    return render(request, 'reports_dashboard.html', context)


@login_required
@role_required('admin')
def appointment_report(request):
    appointments = Appointment.objects.all().order_by('-appointment_date', '-appointment_time')
    status_filter = request.GET.get('status', '')
    if status_filter:
        appointments = appointments.filter(status=status_filter)
    total = appointments.count()
    completed = appointments.filter(status='completed').count()
    pending = appointments.filter(status='pending').count()
    cancelled = appointments.filter(status__in=['cancelled', 'missed']).count()
    context = {
        'appointments': appointments,
        'status_filter': status_filter,
        'total': total,
        'completed': completed,
        'pending': pending,
        'cancelled': cancelled,
    }
    return render(request, 'appointment_report.html', context)


@login_required
@role_required('admin')
def patient_activity_report(request):
    patients = User.objects.filter(role='patient', is_active=True).annotate(
        total_appointments=Count('appointments_as_patient'),
        completed_appointments=Count(
            'appointments_as_patient',
            filter=Q(appointments_as_patient__status='completed')
        ),
        last_visit=Max('appointments_as_patient__appointment_date'),
    ).order_by('-total_appointments')
    total_patients = patients.count()
    active_patients = patients.filter(total_appointments__gt=0).count()
    total_completed = Appointment.objects.filter(status='completed').count()
    context = {
        'patients': patients,
        'total_patients': total_patients,
        'active_patients': active_patients,
        'total_completed': total_completed,
    }
    return render(request, 'patient_activity_report.html', context)


@login_required
@role_required('admin')
def weekly_summary_report(request):
    today = timezone.now().date()
    this_week_start = today - timedelta(days=today.weekday())
    this_week_end = this_week_start + timedelta(days=6)
    week_days = []
    for i in range(7):
        day = this_week_start + timedelta(days=i)
        total = Appointment.objects.filter(appointment_date=day).count()
        completed = Appointment.objects.filter(appointment_date=day, status='completed').count()
        pending = Appointment.objects.filter(appointment_date=day, status='pending').count()
        cancelled = Appointment.objects.filter(
            appointment_date=day, status__in=['cancelled', 'missed']
        ).count()
        week_days.append({
            'date': day,
            'day_name': day.strftime('%A'),
            'total': total,
            'completed': completed,
            'pending': pending,
            'cancelled': cancelled,
        })
    week_appointments = Appointment.objects.filter(
        appointment_date__gte=this_week_start,
        appointment_date__lte=this_week_end,
    )
    context = {
        'week_start': this_week_start,
        'week_end': this_week_end,
        'week_days': week_days,
        'week_total': week_appointments.count(),
        'week_completed': week_appointments.filter(status='completed').count(),
        'week_pending': week_appointments.filter(status='pending').count(),
        'week_cancelled': week_appointments.filter(status__in=['cancelled', 'missed']).count(),
    }
    return render(request, 'weekly_summary.html', context)


# ============ Search ============

@login_required
@user_passes_test(is_staff_member)
def search_patient(request):
    search_query = request.GET.get('query', '').strip()
    patients = None
    searched = bool(search_query)

    if search_query:
        patients = User.objects.filter(
            role='patient', is_active=True
        ).filter(
            Q(sa_id_number__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone_number__icontains=search_query)
        ).order_by('first_name', 'last_name')

    context = {
        'patients': patients,
        'search_query': search_query,
        'searched': searched,
        'result_count': patients.count() if patients is not None else 0,
    }
    return render(request, 'search_patient.html', context)


# ============ API Endpoints ============

@login_required
def get_available_slots(request):
    doctor_id = request.GET.get('doctor_id')
    date = request.GET.get('date')
    if not doctor_id or not date:
        return JsonResponse({'error': 'Missing parameters'}, status=400)
    try:
        doctor = User.objects.get(id=doctor_id, role='doctor')
        appointment_date = datetime.strptime(date, '%Y-%m-%d').date()
        booked_appointments = Appointment.objects.filter(
            doctor=doctor, appointment_date=appointment_date,
            status__in=['confirmed', 'pending']
        ).values_list('appointment_time', flat=True)

        with connection.cursor() as cur:
            cur.execute(
                "SELECT blocked_time FROM blocked_slots "
                "WHERE doctor_id = %s AND blocked_date = %s",
                [doctor.id, appointment_date]
            )
            blocked_times = {row[0].strftime('%H:%M') for row in cur.fetchall()}

        booked_set = {t.strftime('%H:%M') for t in booked_appointments}

        slots = []
        start_time = datetime.strptime('09:00', '%H:%M')
        end_time = datetime.strptime('17:00', '%H:%M')
        current_time = start_time
        while current_time <= end_time:
            time_str = current_time.strftime('%H:%M')
            taken = (time_str in booked_set) or (time_str in blocked_times)
            slots.append({'time': time_str, 'available': not taken})
            current_time += timedelta(minutes=30)
        return JsonResponse({'slots': slots})
    except User.DoesNotExist:
        return JsonResponse({'error': 'Doctor not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_available_doctors(request):
    date = request.GET.get('date')
    if not date:
        return JsonResponse({'error': 'Date required'}, status=400)
    try:
        appointment_date = datetime.strptime(date, '%Y-%m-%d').date()
        doctors = User.objects.filter(role='doctor', is_active=True)
        doctor_list = []
        for doctor in doctors:
            appointment_count = Appointment.objects.filter(
                doctor=doctor, appointment_date=appointment_date,
                status__in=['confirmed', 'pending']
            ).count()
            doctor_list.append({
                'id': doctor.id,
                'name': doctor.get_doctor_display(),
                'specialization': doctor.specialization or 'General Practice',
                'available': appointment_count < 16
            })
        return JsonResponse({'doctors': doctor_list})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============ Notifications ============

@login_required
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return JsonResponse({'success': True})


@login_required
def clear_notifications(request):
    Notification.objects.filter(user=request.user, is_read=True).delete()
    messages.success(request, 'Notifications cleared.')
    return redirect('core:home')


# ============ Profile ============

@login_required
def view_profile(request):
    return render(request, 'profile.html', {'user': request.user})


@login_required
def edit_profile(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        user.save()
        log_audit(request, 'update', 'User', str(user.id), 'Profile updated')
        messages.success(request, 'Profile updated successfully!')
        return redirect('core:view_profile')
    return render(request, 'edit_profile.html', {'user': request.user})


# ============ Clinical Notes ============

@login_required
@user_passes_test(is_doctor_or_nurse)
def add_clinical_note(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    if request.method == 'POST':
        form = ClinicalNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.patient = patient
            note.author = request.user
            note.save()
            log_audit(request, 'create', 'ClinicalNote', str(note.id),
                      f'{note.get_note_type_display()} added for {patient.get_full_name()}')
            messages.success(request, 'Clinical note added successfully.')
            return redirect('core:view_patient_records', patient_id=patient.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ClinicalNoteForm()
    context = {
        'patient': patient,
        'form': form,
    }
    return render(request, 'add_clinical_note.html', context)


# ============ Referrals ============

@login_required
@user_passes_test(is_doctor)
def create_referral(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    if request.method == 'POST':
        form = ReferralForm(request.POST)
        if form.is_valid():
            referral = form.save(commit=False)
            referral.patient = patient
            referral.referring_doctor = request.user
            referral.save()

            if referral.referred_to_doctor:
                Notification.objects.create(
                    user=referral.referred_to_doctor,
                    title='New Referral',
                    message=(
                        f'{request.user.get_doctor_display()} referred '
                        f'{patient.get_full_name()} to you: {referral.reason[:80]}'
                    ),
                    notification_type='referral',
                )

            log_audit(request, 'create', 'Referral', str(referral.id),
                      f'Referral to {referral.referred_to or referral.referred_to_doctor} for {patient.get_full_name()}')
            messages.success(request, f'Referral created.')
            return redirect('core:view_patient_records', patient_id=patient.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ReferralForm()
    context = {
        'patient': patient,
        'form': form,
    }
    return render(request, 'create_referral.html', context)


@login_required
@user_passes_test(is_doctor_or_nurse)
def view_referrals(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    referrals = Referral.objects.filter(patient=patient).order_by('-created_at')
    context = {
        'patient': patient,
        'referrals': referrals,
    }
    return render(request, 'view_referrals.html', context)


# ============ Referrals Received ============

@login_required
@user_passes_test(is_doctor)
def referrals_received(request):
    q = Q(referred_to_doctor=request.user)
    if request.user.last_name:
        q |= Q(referred_to__icontains=request.user.last_name)

    referrals = Referral.objects.filter(q).select_related(
        'patient', 'referring_doctor', 'referred_to_doctor'
    ).order_by('-created_at')

    status_filter = request.GET.get('status', '')
    if status_filter:
        referrals = referrals.filter(status=status_filter)

    counts = {
        'pending': referrals.filter(status='pending').count(),
        'accepted': referrals.filter(status='accepted').count(),
        'completed': referrals.filter(status='completed').count(),
        'cancelled': referrals.filter(status='cancelled').count(),
    }

    return render(request, 'referrals_received.html', {
        'referrals': referrals,
        'status_filter': status_filter,
        'counts': counts,
    })


@login_required
@user_passes_test(is_doctor)
def update_referral_status(request, referral_id):
    referral = get_object_or_404(Referral, id=referral_id)

    is_receiving_doctor = (
        referral.referred_to_doctor == request.user
        or (request.user.last_name
            and request.user.last_name.lower() in (referral.referred_to or '').lower())
    )
    if not is_receiving_doctor:
        messages.error(request, 'This referral is not addressed to you.')
        return redirect('core:referrals_received')

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ['accepted', 'completed', 'cancelled']:
            referral.status = new_status
            referral.save()

            if referral.referring_doctor:
                Notification.objects.create(
                    user=referral.referring_doctor,
                    title=f'Referral {new_status}',
                    message=(
                        f'{request.user.get_doctor_display()} marked the referral '
                        f'for {referral.patient.get_full_name()} as {new_status}.'
                    ),
                    notification_type='referral',
                )
            log_audit(request, 'update', 'Referral', str(referral.id), f'Status: {new_status}')
            messages.success(request, f'Referral marked as {new_status}.')

    return redirect('core:referrals_received')


# ============ Nurse View Prescriptions ============

@login_required
@user_passes_test(is_doctor_or_nurse)
def nurse_view_prescriptions(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    prescriptions = Prescription.objects.filter(patient=patient).order_by('-prescribed_date')
    context = {
        'patient': patient,
        'prescriptions': prescriptions,
    }
    return render(request, 'nurse_view_prescriptions.html', context)


# ============ Receptionist: Register Patient ============

@login_required
@user_passes_test(is_admin_or_receptionist)
def receptionist_register_patient(request):
    if request.method == 'POST':
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                messages.success(
                    request,
                    f'✅ Patient registered successfully! '
                    f'SA ID: {user.sa_id_number}. You can now book an appointment.'
                )
                log_audit(request, 'create', 'User', str(user.id),
                          f'Patient registered by receptionist: {user.sa_id_number}')
                return redirect(f"{request.path.replace('register/', 'search/')}?query={user.sa_id_number}")
            except Exception as e:
                messages.error(request, f'Registration error: {str(e)}')
        else:
            for error in form.non_field_errors():
                messages.error(request, error)
    else:
        initial = {}
        sa_id = request.GET.get('sa_id', '').strip()
        if sa_id and sa_id.isdigit() and len(sa_id) == 13:
            initial['sa_id_number'] = sa_id
        form = PatientRegistrationForm(initial=initial)

    return render(request, 'receptionist_register_patient.html', {'form': form})


# ============ Doctor: Block / Unblock Slots ============

@login_required
@user_passes_test(is_doctor)
def block_slots_view(request):
    doctor = request.user

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'block':
            scope = request.POST.get('scope', 'slot')
            reason = request.POST.get('reason', '').strip()
            today = timezone.now().date()

            try:
                if scope == 'slot':
                    date_str = request.POST.get('blocked_date', '').strip()
                    time_str = request.POST.get('blocked_time', '').strip()
                    if not date_str or not time_str:
                        messages.error(request, 'Please pick both a date and a time.')
                        return redirect('core:block_slots')
                    bdate = datetime.strptime(date_str, '%Y-%m-%d').date()
                    btime = datetime.strptime(time_str, '%H:%M').time()
                    if bdate < today:
                        messages.error(request, 'You cannot block a slot in the past.')
                        return redirect('core:block_slots')
                    with connection.cursor() as cur:
                        cur.callproc('sp_block_slot', [doctor.id, bdate, btime, reason or ''])
                    messages.success(request, f'Slot {bdate} at {btime} blocked.')

                elif scope == 'day':
                    date_str = request.POST.get('blocked_date', '').strip()
                    if not date_str:
                        messages.error(request, 'Please pick a date.')
                        return redirect('core:block_slots')
                    bdate = datetime.strptime(date_str, '%Y-%m-%d').date()
                    if bdate < today:
                        messages.error(request, 'You cannot block a slot in the past.')
                        return redirect('core:block_slots')
                    with connection.cursor() as cur:
                        cur.callproc('sp_block_range',
                                     [doctor.id, bdate, bdate, '09:00:00', '17:00:00', reason or 'Whole day'])
                    messages.success(request, f'Whole day {bdate} blocked.')

                elif scope == 'range':
                    start_str = request.POST.get('start_date', '').strip()
                    end_str = request.POST.get('end_date', '').strip()
                    if not start_str or not end_str:
                        messages.error(request, 'Please pick both start and end dates.')
                        return redirect('core:block_slots')
                    start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
                    end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
                    if start_date < today:
                        messages.error(request, 'You cannot block a slot in the past.')
                        return redirect('core:block_slots')
                    if end_date < start_date:
                        messages.error(request, 'End date must be after start date.')
                        return redirect('core:block_slots')
                    if (end_date - start_date).days > 90:
                        messages.error(request, 'Range cannot exceed 90 days.')
                        return redirect('core:block_slots')
                    with connection.cursor() as cur:
                        cur.callproc('sp_block_range',
                                     [doctor.id, start_date, end_date, '09:00:00', '17:00:00', reason or 'Blocked'])
                    messages.success(request, f'Blocked {start_date} to {end_date}.')

                log_audit(request, 'create', 'BlockedSlot', None,
                          f'Block ({scope}): {reason}')

            except DatabaseError as e:
                msg = e.args[1] if len(e.args) > 1 else str(e)
                if isinstance(msg, bytes):
                    msg = msg.decode('utf-8', errors='replace')
                messages.error(request, msg)

            return redirect('core:block_slots')

        if action == 'unblock':
            slot_id = request.POST.get('slot_id')
            if not slot_id:
                messages.error(request, 'No slot selected.')
                return redirect('core:block_slots')

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT blocked_date, reason FROM blocked_slots "
                    "WHERE id = %s AND doctor_id = %s",
                    [slot_id, doctor.id]
                )
                ref = cur.fetchone()
                if not ref:
                    messages.error(request, 'Block not found.')
                    return redirect('core:block_slots')

                ref_date, ref_reason = ref
                cur.execute(
                    "DELETE FROM blocked_slots "
                    "WHERE doctor_id = %s AND blocked_date = %s AND reason = %s",
                    [doctor.id, ref_date, ref_reason]
                )
                deleted = cur.rowcount

            log_audit(request, 'delete', 'BlockedSlot', str(slot_id),
                      f'Unblocked {deleted} slots on {ref_date}')
            messages.success(request, f'Unblocked {deleted} slots.')
            return redirect('core:block_slots')

    with connection.cursor() as cur:
        cur.execute(
            "SELECT MIN(id), blocked_date, COUNT(*), MIN(blocked_time), MAX(blocked_time), "
            "       MIN(reason), MIN(created_at) "
            "FROM blocked_slots "
            "WHERE doctor_id = %s AND blocked_date >= CURDATE() "
            "GROUP BY blocked_date, reason "
            "ORDER BY blocked_date",
            [doctor.id]
        )
        rows = cur.fetchall()

    blocked_slots = []
    for r in rows:
        slot_count = r[2]
        first_time = r[3]
        last_time = r[4]

        if slot_count >= 17:
            time_label = 'Whole day'
        else:
            end_dt = (datetime.combine(r[1], last_time) + timedelta(minutes=30)).time()
            time_label = f"{first_time.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"

        blocked_slots.append({
            'id': r[0],
            'blocked_date': r[1],
            'time_label': time_label,
            'reason': r[5],
            'created_at': r[6],
        })

    time_choices = []
    t = datetime.strptime('09:00', '%H:%M')
    end = datetime.strptime('17:00', '%H:%M')
    while t <= end:
        time_choices.append(t.strftime('%H:%M'))
        t += timedelta(minutes=30)

    context = {
        'blocked_slots': blocked_slots,
        'time_choices': time_choices,
        'today': timezone.now().date(),
    }
    return render(request, 'block_slots.html', context)


@login_required
@user_passes_test(is_doctor)
def unblock_slot_view(request, slot_id):
    doctor = request.user
    with connection.cursor() as cur:
        cur.execute(
            "SELECT blocked_date, reason FROM blocked_slots "
            "WHERE id = %s AND doctor_id = %s",
            [slot_id, doctor.id]
        )
        ref = cur.fetchone()
        if ref:
            ref_date, ref_reason = ref
            cur.execute(
                "DELETE FROM blocked_slots "
                "WHERE doctor_id = %s AND blocked_date = %s AND reason = %s",
                [doctor.id, ref_date, ref_reason]
            )
    log_audit(request, 'delete', 'BlockedSlot', str(slot_id), 'Unblocked slot group')
    messages.success(request, 'Slot unblocked.')
    return redirect('core:block_slots')


# ============ Follow-ups ============

@login_required
@user_passes_test(is_doctor)
def create_followup(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')

    initial = {}
    appt_id = request.GET.get('appointment')
    if appt_id and appt_id.isdigit():
        appt = Appointment.objects.filter(
            id=appt_id, patient=patient, doctor=request.user
        ).first()
        if appt:
            initial['original_appointment'] = appt

    if request.method == 'POST':
        form = FollowUpForm(request.POST, patient=patient, doctor=request.user)
        if form.is_valid():
            due = form.cleaned_data['due_date']
            blocked_reasons = []

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM blocked_slots "
                    "WHERE doctor_id = %s AND blocked_date = %s",
                    [request.user.id, due]
                )
                if cur.fetchone()[0] > 0:
                    blocked_reasons.append('you have blocked that day')

            za_holidays = holidays.SouthAfrica(years=[due.year])
            if due in za_holidays:
                blocked_reasons.append(f"it's a public holiday ({za_holidays[due]})")

            if blocked_reasons:
                messages.error(
                    request,
                    "You can't set a follow-up for that date because "
                    + " and ".join(blocked_reasons) + "."
                )
            else:
                followup = form.save(commit=False)
                followup.patient = patient
                followup.doctor = request.user
                followup.status = 'due'
                followup.save()

                appt_note = ''
                if followup.original_appointment:
                    a = followup.original_appointment
                    appt_note = f' following your visit on {a.appointment_date}'

                Notification.objects.create(
                    user=patient,
                    title='Follow-up Recommended',
                    message=(
                        f'{request.user.get_doctor_display()} recommends a follow-up '
                        f'by {followup.due_date}{appt_note}: {followup.reason[:80]}'
                    ),
                    notification_type='followup',
                )
                log_audit(request, 'create', 'FollowUp', str(followup.id),
                          f'Follow-up for {patient.get_full_name()} due {followup.due_date}')
                messages.success(request, f'Follow-up scheduled for {followup.due_date}.')
                return redirect('core:view_patient_records', patient_id=patient.id)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = FollowUpForm(patient=patient, doctor=request.user, initial=initial)

    with connection.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT blocked_date FROM blocked_slots "
            "WHERE doctor_id = %s AND blocked_date >= CURDATE()",
            [request.user.id]
        )
        blocked_dates = [row[0].isoformat() for row in cur.fetchall()]

    today = timezone.now().date()
    za_holidays = holidays.SouthAfrica(years=[today.year, today.year + 1])
    holidays_dict = {d.isoformat(): name for d, name in za_holidays.items() if d >= today}

    return render(request, 'create_followup.html', {
        'patient': patient,
        'form': form,
        'blocked_dates_json': json.dumps(blocked_dates),
        'holidays_json': json.dumps(holidays_dict),
    })


@login_required
@user_passes_test(is_doctor_or_nurse)
def view_followups(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    followups = FollowUp.objects.filter(patient=patient).select_related(
        'doctor', 'original_appointment').order_by('-due_date')
    return render(request, 'view_followups.html', {
        'patient': patient,
        'followups': followups,
    })


@login_required
@user_passes_test(is_patient)
def my_followups(request):
    followups = FollowUp.objects.filter(
        patient=request.user
    ).select_related('doctor', 'original_appointment').order_by('due_date')
    return render(request, 'my_followups.html', {
        'followups': followups,
    })


@login_required
@user_passes_test(is_doctor)
def complete_followup(request, followup_id):
    followup = get_object_or_404(FollowUp, id=followup_id, doctor=request.user)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ['completed', 'cancelled', 'scheduled']:
            followup.status = new_status
            followup.save()
            log_audit(request, 'update', 'FollowUp', str(followup.id), f'Status: {new_status}')
            messages.success(request, f'Follow-up marked as {new_status}.')
        return redirect('core:view_patient_records', patient_id=followup.patient.id)

    return render(request, 'complete_followup.html', {'followup': followup})