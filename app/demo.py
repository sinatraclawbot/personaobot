"""Optional local-only sample data. No credentials, outgoing jobs, or enabled profiles."""

import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import engine
from .models import Connection, Conversation, Draft, Memory, Message, Profile
from .schemas import ProfileConfig


def seed():
    with Session(engine()) as db, db.begin():
        if db.scalar(select(Profile.id).limit(1)):
            raise SystemExit("Demo requires an empty profile database")
        for i, name in enumerate(("Sofia", "Anna", "Maya", "Alina")):
            cfg = ProfileConfig(
                languages=("English · French", "English · Russian", "English · Hebrew", "English · Spanish")[i],
                personality="Warm, thoughtful, and curious.",
                pricing="Coffee conversation: 60 per hour, currency and availability to be confirmed by a human.",
                availability="Weekday afternoons, subject to human confirmation.",
            ).model_dump()
            p = Profile(name=name, owner_telegram_id=900000000 + i, config=cfg, mode="approval", enabled=False)
            db.add(p)
            db.flush()
            connection = Connection(
                id=f"demo-{i}",
                profile_id=p.id,
                owner_id=p.owner_telegram_id,
                user_chat_id=p.owner_telegram_id,
                enabled=False,
                rights={},
            )
            db.add(connection)
            db.flush()
            c = Conversation(
                profile_id=p.id,
                connection_id=connection.id,
                chat_id=800000000 + i,
                client_name=("Daniel", "James", "Alex", "Oliver")[i],
                state="escalated" if i == 2 else "paused",
                reason="demo_only",
                last_incoming=time.time() - i * 600,
            )
            db.add(c)
            db.flush()
            db.add(
                Message(
                    profile_id=p.id,
                    conversation_id=c.id,
                    telegram_id=1,
                    direction="incoming",
                    text=(
                        "Hi! Could you tell me more about your coffee conversations?",
                        "Hello, which languages do you speak?",
                        "Could I speak with someone about next Tuesday?",
                        "I enjoy art galleries. Is that something you offer?",
                    )[i],
                    created=time.time() - i * 600,
                )
            )
            if i != 2:
                db.add(
                    Draft(
                        profile_id=p.id,
                        conversation_id=c.id,
                        revision=0,
                        profile_version=1,
                        text=f"Hi! I'm {name}'s AI assistant. I can share information about non-sexual social meetings in public places. What would you like to know?",
                    )
                )
            db.add(Memory(profile_id=p.id, conversation_id=c.id, text="Sample note: prefers a quiet public café."))
    print("Four paused sample profiles created. No messages or jobs were sent.")
