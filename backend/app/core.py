import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic_settings import BaseSettings, SettingsConfigDict
from pwdlib import PasswordHash
from sqlalchemy import create_engine, String, DateTime, JSON, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    demo_password: str
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:1.7b"
    ollama_embed_model: str = "nomic-embed-text"
    ai_mode: str = "ollama"
    frontend_origin: str = "http://localhost:5173"
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)


class Audit(Base):
    __tablename__ = "activity_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


password_hasher = PasswordHash.recommended()
bearer = HTTPBearer()


def session():
    with Session() as db:
        yield db


def current_user(token: HTTPAuthorizationCredentials = Depends(bearer), db=Depends(session)):
    try:
        data = jwt.decode(token.credentials, settings.jwt_secret, algorithms=["HS256"])
        user = db.get(User, data["sub"])
        if not user:
            raise ValueError("Unknown user")
        return user
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token")


def roles(*allowed):
    def dep(user=Depends(current_user)):
        if user.role not in allowed:
            raise HTTPException(403, "Role not permitted")
        return user

    return dep


def audit(db, user, action, entity, metadata=None):
    db.add(Audit(actor_id=user.id, action=action, entity_id=entity, metadata_json=metadata or {}))


def get(db, model, id):
    obj = db.get(model, id)
    if obj is None:
        raise HTTPException(404, "Record not found")
    return obj


def dump(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def login(db, email, password):
    user = db.scalar(select(User).where(User.email == email))
    if not user or not password_hasher.verify(password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    token = jwt.encode(
        {"sub": user.id, "exp": now() + timedelta(minutes=60)}, settings.jwt_secret, algorithm="HS256"
    )
    audit(db, user, "LOGIN", user.id)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "role": user.role, "email": user.email}


def seed_users(db, names):
    for role in names:
        email = role + "@local.demo"
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(email=email, password_hash=password_hasher.hash(settings.demo_password), role=role))
    db.commit()


def owned(obj, user):
    if hasattr(obj, "owner_id") and obj.owner_id != user.id and user.role not in ("manager", "commander"):
        raise HTTPException(403, "This object belongs to another user")
