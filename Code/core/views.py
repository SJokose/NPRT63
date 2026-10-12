from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q, Count, Sum, Max
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from .models import (
    User, Appointment, Queue, Prescription, MedicalRecord,
    Notification, AuditLog, ClinicalNote, Referral,
)
from .forms import (
    PatientRegistrationForm, StaffRegistrationForm, LoginForm,
    AppointmentForm, UserEditForm, QueueForm, PrescriptionForm,
    MedicalRecordForm, PasswordResetRequestForm, PasswordResetConfirmForm,
    OTPVerificationForm, ClinicalNoteForm, ReferralForm,
)
from .utils import generate_otp, send_otp_sms, send_sms_reminder, validate_sa_id
import csv
import json
from datetime import datetime, timedelta

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

# ============ Role Check Decorators ============

def is_staff_member(user):
    return user.is_authenticated and user.role in ['doctor', 'nurse', 'receptionist', 'admin']

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

def is_receptionist_or_admin(user):
    return user.is_authenticated and user.role in ['receptionist', 'admin']

# ============ Authentication Views ============

def home(request):
    """Home page - shows hero landing page for everyone."""
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

def register_staff(request):
    if request.method == 'POST':
        form = StaffRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                messages.success(
                    request,
                    f'✅ Registration successful! Your Staff ID is: {user.staff_id}. '
                    f'Please save it — you will use it to log in.'
                )
                log_audit(request, 'create', 'User', str(user.id), f'Staff registered: {user.staff_id}')
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
    context = {
        'total_appointments': total_appointments,
        'completed_visits': completed_visits,
        'upcoming_count': upcoming_count,
        'patient_id': patient.sa_id_number,
        'upcoming_appointments': upcoming_appointments,
        'notifications': notifications,
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
            appointment = form.save(commit=False)
            appointment.patient = request.user
            appointment.status = 'pending'
            appointment.save()
            Notification.objects.create(
                user=request.user,
                title='Appointment Submitted',
                message=f'Your appointment request with {appointment.doctor.get_doctor_display} on {appointment.appointment_date} is waiting for doctor approval.',
                notification_type='appointment'
            )
            log_audit(request, 'create', 'Appointment', str(appointment.id))
            messages.success(request, 'Appointment submitted! Waiting for doctor approval.')
            return redirect('core:my_appointments')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = AppointmentForm(patient=request.user)
    future_appointments = Appointment.objects.filter(
        appointment_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    )
    busy_slots = {}
    confirmed_slots = {}
    for appt in future_appointments:
        key = appt.appointment_date.strftime('%Y-%m-%d')
        time_str = appt.appointment_time.strftime('%H:%M')
        busy_slots.setdefault(key, []).append(time_str)
        if appt.status == 'confirmed':
            confirmed_slots.setdefault(key, []).append(time_str)
    return render(request, 'book_appointment.html', {
        'form': form,
        'busy_slots_json': json.dumps(busy_slots),
        'confirmed_slots_json': json.dumps(confirmed_slots),
    })

# ============ Cancel Appointment ============

@login_required
@user_passes_test(is_patient)
def cancel_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, patient=request.user)
    if request.method == 'POST':
        appointment.status = 'cancelled'
        appointment.cancelled_at = timezone.now()
        appointment.cancellation_reason = request.POST.get('reason', '')
        appointment.save()

        Notification.objects.create(
            user=request.user,
            title='Appointment Cancelled',
            message=f'Your appointment with {appointment.doctor.get_doctor_display} has been cancelled.',
            notification_type='appointment'
        )

        # Send SMS confirmation
        try:
            send_sms_reminder(
                request.user.phone_number,
                f"MediSync SA: Your appointment with {appointment.doctor.get_doctor_display} "
                f"on {appointment.appointment_date} at {appointment.appointment_time} has been cancelled."
            )
        except Exception as e:
            print(f"[WARN] SMS not sent on cancel: {e}")

        log_audit(request, 'update', 'Appointment', str(appointment.id), 'Cancelled appointment')
        messages.success(request, 'Appointment cancelled successfully.')
        return redirect('core:my_appointments')
    return render(request, 'cancel_appointment.html', {'appointment': appointment})

# ============ Reschedule Appointment ============

@login_required
@user_passes_test(is_patient)
def reschedule_appointment(request, appointment_id):
    """Patient reschedules an existing appointment."""
    appointment = get_object_or_404(Appointment, id=appointment_id, patient=request.user)

    if appointment.status not in ['pending', 'confirmed']:
        messages.error(request, 'This appointment cannot be rescheduled.')
        return redirect('core:my_appointments')

    if request.method == 'POST':
        form = AppointmentForm(request.POST, patient=request.user)
        if form.is_valid():
            old_date = appointment.appointment_date
            old_time = appointment.appointment_time

            appointment.appointment_date = form.cleaned_data['appointment_date']
            appointment.appointment_time = form.cleaned_data['appointment_time']
            appointment.reason_for_visit = form.cleaned_data.get('reason_for_visit', appointment.reason_for_visit)
            appointment.status = 'pending'
            appointment.rescheduled_count += 1
            appointment.last_rescheduled_at = timezone.now()
            # Reset reminder flags so new reminders fire for the new date
            appointment.reminder_sent_72h = False
            appointment.reminder_sent_24h = False
            appointment.reminder_sent_2h = False
            appointment.save()

            Notification.objects.create(
                user=request.user,
                title='Appointment Rescheduled',
                message=(
                    f'Your appointment with {appointment.doctor.get_doctor_display} '
                    f'has been moved from {old_date} {old_time} to '
                    f'{appointment.appointment_date} {appointment.appointment_time}.'
                ),
                notification_type='appointment'
            )

            try:
                send_sms_reminder(
                    request.user.phone_number,
                    f"MediSync SA: Your appointment with {appointment.doctor.get_doctor_display} "
                    f"has been rescheduled to {appointment.appointment_date} at "
                    f"{appointment.appointment_time}."
                )
            except Exception as e:
                print(f"[WARN] SMS not sent on reschedule: {e}")

            log_audit(request, 'update', 'Appointment', str(appointment.id), 'Rescheduled')
            messages.success(request, 'Appointment rescheduled successfully. Waiting for approval.')
            return redirect('core:my_appointments')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = AppointmentForm(patient=request.user, initial={
            'appointment_date': appointment.appointment_date,
            'appointment_time': appointment.appointment_time,
            'reason_for_visit': appointment.reason_for_visit,
        })

    future_appointments = Appointment.objects.filter(
        appointment_date__gte=timezone.now().date(),
        status__in=['pending', 'confirmed']
    ).exclude(id=appointment.id)

    busy_slots = {}
    confirmed_slots = {}
    for appt in future_appointments:
        key = appt.appointment_date.strftime('%Y-%m-%d')
        time_str = appt.appointment_time.strftime('%H:%M')
        busy_slots.setdefault(key, []).append(time_str)
        if appt.status == 'confirmed':
            confirmed_slots.setdefault(key, []).append(time_str)

    return render(request, 'reschedule_appointment.html', {
        'form': form,
        'appointment': appointment,
        'busy_slots_json': json.dumps(busy_slots),
        'confirmed_slots_json': json.dumps(confirmed_slots),
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

# ============ NURSE DASHBOARD ============

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

# ============ NURSE CHECK-IN ============

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

# ============ NURSE RECORD VITALS ============

@login_required
@user_passes_test(is_staff_member)
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
            treatment=json.dumps(vitals_data, indent=2),
            notes=vitals_data['notes'],
        )
        log_audit(request, 'create', 'MedicalRecord', str(record.id),
                  f'Vitals recorded for {patient.get_full_name()}')
        messages.success(request, f'Vitals recorded for {patient.get_full_name()}.')
        return redirect('core:nurse_dashboard')
    return render(request, 'nurse_record_vitals.html', {'patient': patient})

# ============ NURSE VITALS PICKER ============

@login_required
@user_passes_test(is_nurse)
def nurse_vitals_picker(request):
    today = timezone.now().date()
    today_patients = User.objects.filter(
        role='patient',
        is_active=True,
        appointments__appointment_date=today,
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
@user_passes_test(is_admin_or_receptionist)
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
@user_passes_test(is_admin_or_receptionist)
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
@user_passes_test(is_admin_or_receptionist)
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
@user_passes_test(is_admin_or_receptionist)
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
@user_passes_test(is_admin_or_receptionist)
def toggle_user_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    user.is_active = not user.is_active
    user.save()
    status = 'activated' if user.is_active else 'deactivated'
    log_audit(request, 'update', 'User', str(user.id), f'User {status}')
    messages.success(request, f'User {user.get_full_name()} has been {status}.')
    return redirect('core:user_management')

@login_required
@user_passes_test(is_admin_or_receptionist)
def bulk_import_users(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        try:
            decoded = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded)
            imported_count = 0
            errors = []
            for row in reader:
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
                    errors.append(f"Row {reader.line_num}: {str(e)}")
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
@user_passes_test(is_staff_member)
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
@user_passes_test(is_staff_member)
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
                        message=f'Your appointment with {appointment.doctor.get_doctor_display} on {appointment.appointment_date} at {appointment.appointment_time} has been confirmed.',
                        notification_type='appointment'
                    )
                    messages.success(request, 'Appointment approved.')
                elif action == 'complete':
                    appointment.status = 'completed'
                    appointment.save()
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
    }
    return render(request, 'manage_appointments.html', context)

# ============ Medical Records ============

@login_required
@user_passes_test(is_staff_member)
def add_medical_record(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    if request.method == 'POST':
        form = MedicalRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.patient = patient
            record.created_by = request.user
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
    return render(request, 'add_medical_record.html', {'form': form, 'patient': patient})

@login_required
def view_patient_records(request, patient_id):
    patient = get_object_or_404(User, id=patient_id, role='patient')
    records = MedicalRecord.objects.filter(patient=patient).order_by('-created_at')
    prescriptions = Prescription.objects.filter(patient=patient).order_by('-prescribed_date')
    appointments = Appointment.objects.filter(patient=patient).order_by('-appointment_date')[:10]
    clinical_notes = ClinicalNote.objects.filter(patient=patient).order_by('-created_at')
    referrals = Referral.objects.filter(patient=patient).order_by('-created_at')
    context = {
        'patient': patient,
        'records': records,
        'prescriptions': prescriptions,
        'appointments': appointments,
        'clinical_notes': clinical_notes,
        'referrals': referrals,
    }
    return render(request, 'view_patient_records.html', context)

# ============ Prescriptions ============

@login_required
@user_passes_test(is_doctor_or_nurse)
def add_prescription(request, patient_id):
    """Doctors write prescriptions. Nurses see a read-only view with a notice."""
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
                message=f'{request.user.get_doctor_display} has prescribed {prescription.medication_name} for you.',
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
@user_passes_test(is_staff_member)
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
@user_passes_test(is_staff_member)
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
@user_passes_test(is_staff_member)
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
@user_passes_test(is_staff_member)
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
    search_query = request.GET.get('query', '')
    patients = None
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
    return render(request, 'search_patient.html', {'patients': patients, 'search_query': search_query})

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
        slots = []
        start_time = datetime.strptime('09:00', '%H:%M')
        end_time = datetime.strptime('17:00', '%H:%M')
        current_time = start_time
        while current_time <= end_time:
            time_str = current_time.strftime('%H:%M')
            slots.append({'time': time_str, 'available': time_str not in booked_appointments})
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


# ==========================================================
# ============ CLINICAL NOTES ==============================
# ==========================================================

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


# ==========================================================
# ============ REFERRALS ===================================
# ==========================================================

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
            log_audit(request, 'create', 'Referral', str(referral.id),
                      f'Referral to {referral.referred_to} for {patient.get_full_name()}')
            messages.success(request, f'Referral to {referral.referred_to} created.')
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


# ==========================================================
# ============ NURSE VIEW PRESCRIPTIONS ====================
# ==========================================================

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


# ==========================================================
# ============ RECEPTIONIST: REGISTER PATIENT ==============
# ==========================================================

@login_required
@user_passes_test(is_admin_or_receptionist)
def receptionist_register_patient(request):
    """Receptionist registers a new patient on their behalf."""
    if request.method == 'POST':
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
                messages.success(
                    request,
                    f'✅ Patient registered successfully! '
                    f'SA ID: {user.sa_id_number}. They can log in with their SA ID.'
                )
                log_audit(request, 'create', 'User', str(user.id),
                          f'Patient registered by receptionist: {user.sa_id_number}')
                return redirect('core:receptionist_register_patient')
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

    context = {
        'form': form,
    }
    return render(request, 'receptionist_register_patient.html', context)