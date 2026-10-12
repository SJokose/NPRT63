from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # ============ HOME ============
    path('', views.home, name='home'),

    # ============ AUTH ============
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),

    # ============ REGISTRATION ============
    path('register/', views.register_patient, name='register'),
    path('register/staff/', views.register_staff, name='register_staff'),

    # ============ PATIENT ============
    path('patient/dashboard/', views.patient_dashboard, name='patient_dashboard'),
    path('patient/appointments/', views.my_appointments, name='my_appointments'),
    path('patient/book/', views.book_appointment, name='book_appointment'),
    path('patient/cancel/<int:appointment_id>/', views.cancel_appointment, name='cancel_appointment'),
    path('patient/reschedule/<int:appointment_id>/', views.reschedule_appointment, name='reschedule_appointment'),

    # ============ STAFF DASHBOARD ============
    path('staff/dashboard/', views.staff_dashboard, name='staff_dashboard'),

    # ============ DOCTOR: BLOCK SLOTS ============
    path('staff/block-slots/', views.block_slots_view, name='block_slots'),
    path('staff/block-slots/unblock/<int:slot_id>/', views.unblock_slot_view, name='unblock_slot'),

    # ============ NURSE DASHBOARD ============
    path('nurse/dashboard/', views.nurse_dashboard, name='nurse_dashboard'),
    path('nurse/check-in/', views.nurse_check_in, name='nurse_check_in'),
    path('nurse/record-vitals/', views.nurse_vitals_picker, name='nurse_vitals_picker'),
    path('nurse/record-vitals/<int:patient_id>/', views.nurse_record_vitals, name='nurse_record_vitals'),

    # ============ APPOINTMENTS ============
    path('staff/appointments/', views.manage_appointments, name='manage_appointments'),

    # ============ QUEUE ============
    path('staff/queue/', views.manage_queue, name='manage_queue'),
    path('staff/queue/update/<int:queue_id>/', views.update_queue_status, name='update_queue_status'),

    # ============ USER MANAGEMENT ============
    path('staff/register-patient/', views.receptionist_register_patient, name='receptionist_register_patient'),
    path('staff/users/', views.user_management, name='user_management'),
    path('staff/users/add/', views.add_user, name='add_user'),
    path('staff/users/edit/<int:user_id>/', views.edit_user, name='edit_user'),
    path('staff/users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('staff/users/toggle/<int:user_id>/', views.toggle_user_status, name='toggle_user_status'),
    path('staff/users/bulk-import/', views.bulk_import_users, name='bulk_import_users'),

    # ============ PATIENT SEARCH ============
    path('staff/search/', views.search_patient, name='search_patient'),

    # ============ MEDICAL RECORDS ============
    path('staff/records/add/<int:patient_id>/', views.add_medical_record, name='add_medical_record'),
    path('staff/records/view/<int:patient_id>/', views.view_patient_records, name='view_patient_records'),

    # ============ PRESCRIPTIONS ============
    path('staff/prescription/add/<int:patient_id>/', views.add_prescription, name='add_prescription'),
    path('staff/prescription/view/<int:patient_id>/', views.nurse_view_prescriptions, name='nurse_view_prescriptions'),

    # ============ CLINICAL NOTES ============
    path('staff/clinical-note/add/<int:patient_id>/', views.add_clinical_note, name='add_clinical_note'),

    # ============ REFERRALS ============
    path('staff/referral/create/<int:patient_id>/', views.create_referral, name='create_referral'),
    path('staff/referral/view/<int:patient_id>/', views.view_referrals, name='view_referrals'),

    # ============ REPORTS ============
    path('staff/reports/', views.reports_dashboard, name='reports_dashboard'),
    path('staff/reports/appointments/', views.appointment_report, name='appointment_report'),
    path('staff/reports/patients/', views.patient_activity_report, name='patient_activity_report'),
    path('staff/reports/weekly/', views.weekly_summary_report, name='weekly_summary_report'),

    # ============ API ENDPOINTS ============
    path('api/available-slots/', views.get_available_slots, name='get_available_slots'),
    path('api/available-doctors/', views.get_available_doctors, name='get_available_doctors'),

    # ============ PROFILE ============
    path('profile/', views.view_profile, name='view_profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),

    # ============ NOTIFICATIONS ============
    path('notifications/clear/', views.clear_notifications, name='clear_notifications'),
    path('notifications/read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
    
    # ============ FOLLOW-UPS ============
    path('staff/followup/create/<int:patient_id>/', views.create_followup, name='create_followup'),
    path('staff/followup/view/<int:patient_id>/', views.view_followups, name='view_followups'),
    path('staff/followup/<int:followup_id>/complete/', views.complete_followup, name='complete_followup'),
    path('patient/followups/', views.my_followups, name='my_followups'),
    
        # ============ REFERRALS RECEIVED ============
    path('staff/referrals/received/', views.referrals_received, name='referrals_received'),
    path('staff/referrals/<int:referral_id>/update/', views.update_referral_status, name='update_referral_status'),
]