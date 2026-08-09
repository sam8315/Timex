"""امنیت و هش رمز عبور - استفاده مستقیم از bcrypt"""
import bcrypt


def hash_password(password: str) -> str:
    """هش رمز عبور با bcrypt"""
    # bcrypt حداکثر 72 بایت قبول می‌کند
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """بررسی صحت رمز عبور"""
    try:
        password_bytes = plain_password.encode('utf-8')[:72]
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False