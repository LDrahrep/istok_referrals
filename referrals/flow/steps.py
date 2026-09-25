"""Имена шагов диалога (хранятся в sessions.step) и общие константы."""
LANG = "lang"
AUTH_WAIT_ID = "auth_wait_id"
AUTH_ADMIN_NAME = "auth_admin_name"
MENU = "menu"
REF_FIRST_NAME = "ref_first_name"
REF_LAST_NAME = "ref_last_name"
REF_PHONE = "ref_phone"
REF_EMAIL = "ref_email"
REF_WORKED = "ref_worked"
REF_PHOTO = "ref_photo"
REF_CONFIRM = "ref_confirm"

AUTH_STEPS = frozenset({AUTH_WAIT_ID, AUTH_ADMIN_NAME})
FORM_STEPS = (REF_FIRST_NAME, REF_LAST_NAME, REF_PHONE, REF_EMAIL, REF_WORKED, REF_PHOTO, REF_CONFIRM)

ADMIN_BUTTON_AFTER_FAILS = 3
MAX_FILE_BYTES = 20 * 1024 * 1024
