from core.models import User, Patient, Staff
from django.contrib.auth.hashers import check_password

# EDIT these two lines to match exactly what you're typing into the login form
test_identifier = "DOC001"
test_password = "Doctor1234"

print("--- Checking as Patient ---")
patient = Patient.objects.filter(saidnumber=test_identifier).select_related('userid').first()
if patient:
    print(f"Found patient: {patient.userid.name} {patient.userid.surname}")
    print(f"Stored hash: {patient.userid.passwordhash[:30]}...")
    print(f"Password matches: {check_password(test_password, patient.userid.passwordhash)}")
else:
    print("No patient found with that SA ID.")

print("--- Checking as Staff ---")
staff = Staff.objects.filter(staffid=test_identifier).select_related('userid').first()
if staff:
    print(f"Found staff: {staff.userid.name} {staff.userid.surname}, role={staff.userid.role}")
    print(f"Stored hash: {staff.userid.passwordhash[:30]}...")
    print(f"Password matches: {check_password(test_password, staff.userid.passwordhash)}")
else:
    print("No staff found with that Staff ID.")