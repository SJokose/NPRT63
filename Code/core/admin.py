from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Appointment, Queue, Prescription, MedicalRecord,
    Notification, AuditLog, BlockedSlot, ClinicalNote,
    Referral, FollowUp,
)


class CustomUserAdmin(UserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name',
        'role', 'sa_id_number', 'staff_id', 'is_active',
    )
    list_filter = ('role', 'is_active', 'date_joined')
    search_fields = (
        'username', 'email', 'first_name', 'last_name',
        'sa_id_number', 'staff_id',
    )
    ordering = ('-date_joined',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {
            'fields': (
                'first_name', 'last_name', 'email',
                'phone_number', 'date_of_birth', 'address',
            )
        }),
        ('Identification', {'fields': ('sa_id_number', 'staff_id', 'role')}),
        ('Permissions', {
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions',
            )
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'email', 'password1', 'password2',
                'role', 'sa_id_number', 'staff_id',
            ),
        }),
    )


class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'patient', 'doctor', 'appointment_date',
        'appointment_time', 'status',
    )
    list_filter = ('status', 'appointment_date')
    search_fields = (
        'patient__first_name', 'patient__last_name',
        'doctor__first_name', 'doctor__last_name',
    )
    ordering = ('-appointment_date', '-appointment_time')


class BlockedSlotAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'doctor', 'blocked_date', 'blocked_time',
        'reason', 'created_at',
    )
    list_filter = ('blocked_date', 'reason', 'doctor')
    search_fields = (
        'reason',
        'doctor__first_name', 'doctor__last_name', 'doctor__staff_id',
    )
    ordering = ('blocked_date', 'blocked_time')
    list_per_page = 50


class QueueAdmin(admin.ModelAdmin):
    list_display = ('queue_number', 'patient', 'doctor', 'status', 'entered_at')
    list_filter = ('status', 'entered_at')
    search_fields = ('patient__first_name', 'patient__last_name', 'queue_number')


class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ('medication_name', 'patient', 'doctor', 'prescribed_date', 'filled')
    list_filter = ('filled', 'prescribed_date')
    search_fields = ('medication_name', 'patient__first_name', 'patient__last_name')


class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ('patient', 'created_by', 'created_at', 'diagnosis')
    list_filter = ('created_at',)
    search_fields = ('patient__first_name', 'patient__last_name', 'diagnosis')


class ClinicalNoteAdmin(admin.ModelAdmin):
    list_display = ('patient', 'author', 'note_type', 'title', 'created_at')
    list_filter = ('note_type', 'created_at')
    search_fields = (
        'patient__first_name', 'patient__last_name',
        'title', 'content',
    )
    ordering = ('-created_at',)


class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        'patient', 'referring_doctor', 'referred_to',
        'specialty', 'urgency', 'status', 'referral_date',
    )
    list_filter = ('urgency', 'status', 'referral_date')
    search_fields = (
        'patient__first_name', 'patient__last_name',
        'referred_to', 'specialty', 'reason',
    )
    ordering = ('-created_at',)


class FollowUpAdmin(admin.ModelAdmin):
    list_display = (
        'patient', 'doctor', 'due_date', 'status',
        'original_appointment', 'scheduled_appointment',
    )
    list_filter = ('status', 'due_date')
    search_fields = (
        'patient__first_name', 'patient__last_name',
        'doctor__first_name', 'doctor__last_name',
        'reason',
    )
    ordering = ('due_date',)


class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('is_read', 'notification_type', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'title')


class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'model_name', 'object_id', 'timestamp')
    list_filter = ('action', 'model_name', 'timestamp')
    search_fields = ('user__first_name', 'user__last_name', 'object_id')
    ordering = ('-timestamp',)


admin.site.register(User, CustomUserAdmin)
admin.site.register(Appointment, AppointmentAdmin)
admin.site.register(BlockedSlot, BlockedSlotAdmin)
admin.site.register(Queue, QueueAdmin)
admin.site.register(Prescription, PrescriptionAdmin)
admin.site.register(MedicalRecord, MedicalRecordAdmin)
admin.site.register(ClinicalNote, ClinicalNoteAdmin)
admin.site.register(Referral, ReferralAdmin)
admin.site.register(FollowUp, FollowUpAdmin)
admin.site.register(Notification, NotificationAdmin)
admin.site.register(AuditLog, AuditLogAdmin)