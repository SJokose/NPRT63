from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.core.validators import RegexValidator


class User(AbstractUser):
    """Custom User Model for MediSync"""
    
    ROLE_CHOICES = [
        ('patient', 'Patient'),
        ('doctor', 'Doctor'),
        ('nurse', 'Nurse'),
        ('receptionist', 'Receptionist'),
        ('admin', 'Administrator'),
    ]
    
    sa_id_validator = RegexValidator(
        regex=r'^\d{13}$',
        message='SA ID Number must be exactly 13 digits'
    )
    
    staff_id_validator = RegexValidator(
        regex=r'^[A-Z0-9]{6,10}$',
        message='Staff ID must be 6-10 alphanumeric characters'
    )
    
    sa_id_number = models.CharField(
        max_length=13,
        unique=True,
        validators=[sa_id_validator],
        blank=True,
        null=True,
        verbose_name='SA ID Number'
    )
    staff_id = models.CharField(
        max_length=10,
        unique=True,
        validators=[staff_id_validator],
        blank=True,
        null=True,
        verbose_name='Staff ID'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='patient'
    )
    phone_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[RegexValidator(
            regex=r'^[0-9]{10,15}$',
            message='Phone number must be 10-15 digits'
        )]
    )
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    emergency_contact = models.CharField(max_length=15, blank=True, null=True)
    
    specialization = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Specialization',
        help_text='e.g., Cardiology, Pediatrics, General Practice'
    )
    
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def get_role_display(self):
        return dict(self.ROLE_CHOICES).get(self.role, self.role)
    
    def get_doctor_display(self):
        """Returns 'Dr. Initial. Surname' for doctors; full name for everyone else."""
        if self.role == 'doctor':
            if self.first_name:
                initial = self.first_name[0].upper() + '.'
                return f"Dr. {initial} {self.last_name}"
            return f"Dr. {self.last_name}"
        return self.get_full_name()
    
    def __str__(self):
        return f"{self.get_full_name()} - {self.get_role_display()}"
    
    class Meta:
        ordering = ['-date_joined']


class Appointment(models.Model):
    """Appointment model"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('missed', 'Missed'),
    ]
    
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments_as_patient')
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='appointments_as_doctor', limit_choices_to={'role': 'doctor'})
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    duration_minutes = models.IntegerField(default=30)
    reason_for_visit = models.TextField()
    symptoms = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.TextField(blank=True, null=True)
    reminder_sent_72h = models.BooleanField(default=False)
    reminder_sent_24h = models.BooleanField(default=False)
    reminder_sent_2h = models.BooleanField(default=False)

    # Reschedule tracking
    rescheduled_count = models.IntegerField(default=0)
    last_rescheduled_at = models.DateTimeField(blank=True, null=True)
    
    def __str__(self):
        return f"Dr. {self.doctor.get_full_name()} - {self.patient.get_full_name()} ({self.appointment_date})"
    
    class Meta:
        ordering = ['appointment_date', 'appointment_time']
        unique_together = ['doctor', 'appointment_date', 'appointment_time']


class Queue(models.Model):
    """Patient queue management"""
    
    STATUS_CHOICES = [
        ('waiting', 'Waiting'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('skipped', 'Skipped'),
    ]
    
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='queues')
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='queues_as_doctor', limit_choices_to={'role': 'doctor'})
    queue_number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, blank=True, null=True, related_name='queue_entry')
    entered_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    estimated_wait_time = models.IntegerField(default=0)
    
    def __str__(self):
        return f"Queue #{self.queue_number} - {self.patient.get_full_name()}"
    
    class Meta:
        ordering = ['entered_at']
        verbose_name_plural = 'Queues'


class Prescription(models.Model):
    """Prescription/Medication records"""
    
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prescriptions')
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prescriptions_given', limit_choices_to={'role': 'doctor'})
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, blank=True, null=True)
    medication_name = models.CharField(max_length=100)
    dosage = models.CharField(max_length=50)
    frequency = models.CharField(max_length=100)
    duration = models.CharField(max_length=100)
    instructions = models.TextField(blank=True, null=True)
    prescribed_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateField(blank=True, null=True)
    filled = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.medication_name} - {self.patient.get_full_name()}"
    
    class Meta:
        ordering = ['-prescribed_date']


class MedicalRecord(models.Model):
    """Patient medical history"""
    
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='medical_records')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='records_created')
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, blank=True, null=True)
    diagnosis = models.TextField()
    treatment_plan = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    blood_pressure = models.CharField(max_length=20, blank=True, null=True)
    heart_rate = models.IntegerField(blank=True, null=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    height = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.patient.get_full_name()} - {self.created_at.strftime('%Y-%m-%d')}"
    
    class Meta:
        ordering = ['-created_at']


class ClinicalNote(models.Model):
    """Nursing / clinical notes added by doctors and nurses."""

    NOTE_TYPE_CHOICES = [
        ('nursing', 'Nursing Note'),
        ('observation', 'Observation'),
        ('progress', 'Progress Note'),
        ('general', 'General Note'),
    ]

    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='clinical_notes',
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='clinical_notes_authored',
    )
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='clinical_notes',
    )
    note_type = models.CharField(
        max_length=20,
        choices=NOTE_TYPE_CHOICES,
        default='general',
    )
    title = models.CharField(max_length=150, blank=True, null=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_note_type_display()} — {self.patient.get_full_name()} ({self.created_at.strftime('%Y-%m-%d')})"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Clinical Note'
        verbose_name_plural = 'Clinical Notes'


class Referral(models.Model):
    """Referral letters to specialists or other facilities."""

    URGENCY_CHOICES = [
        ('routine', 'Routine'),
        ('urgent', 'Urgent'),
        ('emergency', 'Emergency'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    patient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='referrals',
    )
    referring_doctor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='referrals_made',
        limit_choices_to={'role': 'doctor'},
    )
    referred_to = models.CharField(
        max_length=200,
        help_text='Specialist name or facility',
    )
    specialty = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='e.g., Cardiology, Orthopaedics',
    )
    reason = models.TextField(
        help_text='Reason for referral',
    )
    clinical_summary = models.TextField(
        blank=True,
        null=True,
        help_text='Brief summary of patient condition',
    )
    urgency = models.CharField(
        max_length=20,
        choices=URGENCY_CHOICES,
        default='routine',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    referral_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Referral — {self.patient.get_full_name()} → {self.referred_to}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Referral'
        verbose_name_plural = 'Referrals'


class Notification(models.Model):
    """System notifications"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=100)
    message = models.TextField()
    notification_type = models.CharField(max_length=50)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=200, blank=True, null=True)
    
    def __str__(self):
        return f"{self.title} - {self.user.get_full_name()}"
    
    class Meta:
        ordering = ['-created_at']


class AuditLog(models.Model):
    """Audit trail for compliance"""
    
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('view', 'View'),
        ('export', 'Export'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50, blank=True, null=True)
    changes = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user} - {self.action} - {self.model_name}"
    
    class Meta:
        ordering = ['-timestamp']