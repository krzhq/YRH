import re
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

hasher = PasswordHasher(type=Type.ID)
RESERVED = ('matveikrutoi228', 'aruzhan9mice')

def valid_username(value: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9_]{3,32}', value)) and not value.isdecimal() and value.lower() not in RESERVED

def valid_password(value: str) -> bool:
    return 8 <= len(value) <= 128

def valid_age(value: str) -> bool:
    return bool(re.fullmatch(r'[0-9]+', value)) and 13 <= int(value) <= 100

def verify(encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False
