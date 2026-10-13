from core.models import User
from django.contrib.auth.hashers import make_password, is_password_usable

fixed = []
skipped = []

for user in User.objects.all():
    if is_password_usable(user.passwordhash):
        skipped.append(user.email or user.userid)
    else:
        plain_text_password = user.passwordhash
        user.passwordhash = make_password(plain_text_password)
        user.save()
        fixed.append(user.email or user.userid)

print(f"Fixed {len(fixed)} accounts: {fixed}")
print(f"Already OK, skipped {len(skipped)} accounts: {skipped}")