"""The question of the day: one light music question for both members.

* The day is the UTC date; the question comes from a fixed list, in turn.
* A member sees the other's answer only after answering too, so no answer is
  shaped by the other one. Nobody is told whether the other has answered.
* Answers are short plain text (the UI renders them as text) and are deleted
  after ``RETENTION``.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.models import DailyAnswer
from app.services.accounts import InvalidInput
from app.services.members import load_room_members

MAX_ANSWER = 140
RETENTION = timedelta(days=7)

QUESTIONS: tuple[str, ...] = (
    "A song you know every word to?",
    "The first album you loved?",
    "A song for a rainy day?",
    "What's on repeat this week?",
    "A song that sounds like summer?",
    "The best song for a long drive?",
    "A song you never skip?",
    "An artist you'd love to see live?",
    "A song that always lifts your mood?",
    "A song from your childhood?",
    "A song in a language you don't speak?",
    "A song that deserves to be more famous?",
    "Your song for cooking?",
    "A song you found by accident?",
    "An album worth hearing start to finish?",
    "A song for late at night?",
    "A song that takes you back to school?",
    "One song to wake up to?",
    "A cover better than the original?",
    "A favourite film soundtrack?",
    "A song for walking around the city?",
    "An instrument you'd like to play?",
    "A song that makes you want to dance?",
    "Your favourite song this year?",
    "A song for a quiet morning?",
    "Which decade had the best music?",
    "A song that tells a good story?",
    "The last song that stuck in your head?",
    "A song you'd play for someone new to your country?",
    "A calm song for the end of the day?",
)


@dataclass(frozen=True, slots=True)
class QuestionView:
    day: date
    question: str
    my_answer: str | None
    partner_answer: str | None


def question_for(day: date) -> str:
    return QUESTIONS[day.toordinal() % len(QUESTIONS)]


def clean_answer(text: str) -> str:
    answer = " ".join(text.split())
    if (
        not answer
        or len(answer) > MAX_ANSWER
        or any(unicodedata.category(char) == "Cc" for char in answer)
    ):
        raise InvalidInput(f"Answers are 1-{MAX_ANSWER} characters.", code="invalid_answer")
    return answer


async def today(db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID) -> QuestionView:
    members = await load_room_members(db, user_id)
    day = ctx.clock().date()
    rows = (
        (
            await db.execute(
                select(DailyAnswer).where(
                    DailyAnswer.room_id == members.room_id, DailyAnswer.day == day
                )
            )
        )
        .scalars()
        .all()
    )
    mine = next((r.answer for r in rows if r.user_id == user_id), None)
    theirs = next((r.answer for r in rows if r.user_id != user_id), None)
    return QuestionView(
        day=day,
        question=question_for(day),
        my_answer=mine,
        partner_answer=theirs if mine is not None else None,
    )


async def answer(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, text: str
) -> QuestionView:
    value = clean_answer(text)
    members = await load_room_members(db, user_id)
    now = ctx.clock()
    for _ in range(2):  # a second try only if another tab inserted first
        row = (
            await db.execute(
                select(DailyAnswer).where(
                    DailyAnswer.user_id == user_id, DailyAnswer.day == now.date()
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                DailyAnswer(
                    id=uuid.uuid4(),
                    room_id=members.room_id,
                    user_id=user_id,
                    day=now.date(),
                    answer=value,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.answer = value
            row.updated_at = now
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
    return await today(db, ctx, user_id=user_id)


async def purge_old_answers(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(DailyAnswer).where(DailyAnswer.day < (now - RETENTION).date()))
