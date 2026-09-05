"""The three constraint questions, and what each one is for.

"What do you want" is a hard question for someone without direction. These three are not.
Every one of them is skippable, every answer returns to the Uploader as personal data, and
every one states what it is for — a question whose purpose is hidden is a question people
answer defensively.

Q-1 is **subtractive**, because ruling paths out is cheaper than picking one. Q-2 asks about
the *pattern* of quitting rather than its reasons, and it is the question that earns its
keep in Station 3: it is the baseline that tells a growth-driven revision from an
avoidance-driven one. Q-3 forces a ranking, because everyone claims all three matter
equally, and the forced answer is what sets the Quota.

None of them is a personality question.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from services.api.domain.errors import InvalidInput

__all__ = ["QUESTIONS", "AreaChoice", "Question", "QuestionKey", "question", "parse_area"]

QuestionKey = Literal["q1", "q2", "q3"]
AreaChoice = Literal["career", "relationships", "health"]


class Question(BaseModel):
    """One constraint question, with the reason it is being asked."""

    model_config = ConfigDict(frozen=True)

    key: QuestionKey
    prompt: str
    purpose: str
    #: Q-3 is a forced choice between three areas; the others are free text.
    choices: list[AreaChoice] = []


QUESTIONS: tuple[Question, ...] = (
    Question(
        key="q1",
        prompt="What are you certain you do not want?",
        purpose="Constrains the five-year candidate set from the outside in.",
    ),
    Question(
        key="q2",
        prompt=(
            "What did you give up in the last two years? Did you hit resistance, or lose interest?"
        ),
        purpose=(
            "Establishes your own baseline for telling a growth-driven revision from an "
            "avoidance-driven one."
        ),
    ),
    Question(
        key="q3",
        prompt="If you could only keep two this quarter, which would you let go of first?",
        purpose=(
            "Sets the quota the schedule may spend, and the cut order when capacity runs short."
        ),
        choices=["career", "relationships", "health"],
    ),
)


def question(key: str) -> Question:
    """The question with that key, or `InvalidInput` — there are exactly three."""
    found = next((item for item in QUESTIONS if item.key == key), None)
    if found is None:
        raise InvalidInput(f"unknown question {key!r}; expected one of q1, q2, q3")
    return found


def parse_area(value: str) -> AreaChoice:
    """Q-3's answer is a choice, not prose: it becomes the Quota's cut order."""
    normalised = value.strip().lower()
    if normalised not in ("career", "relationships", "health"):
        raise InvalidInput(
            f"q3 must be answered with career, relationships or health, got {value!r}"
        )
    return normalised  # type: ignore[return-value]
