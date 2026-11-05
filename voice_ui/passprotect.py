from getpass import getpass
from werkzeug.security import generate_password_hash

password = getpass("Mail access password: ")
print(generate_password_hash(password))

import secrets; print(secrets.token_urlsafe(48))
