"""The accounts a preview signs you in as. All fake; `seed.py` creates them, in the state each
description promises. A slug is the only thing `/_preview/enter` accepts, so a link can never
reach any other account."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PERSONAS", "PERSONAS_BY_SLUG", "Persona"]


@dataclass(frozen=True)
class Persona:
    """`login` is the username (learner and staff accounts) or email (teacher, volunteer)."""

    slug: str
    login: str
    name: str
    description: str


PERSONAS: tuple[Persona, ...] = (
    Persona("learner-new", "preview-learner-new", "Amira New", "Learner who has not taken the placement test"),
    Persona("learner-midpath", "preview-learner-midpath", "Yusuf Midpath", "Learner part way along the path, with XP"),
    Persona("learner-matched", "preview-learner-matched", "Zahra Matched", "Learner matched with the volunteer"),
    Persona("volunteer", "volunteer@preview.test", "Nikos Volunteer", "Volunteer tutoring the matched learner"),
    Persona("teacher", "teacher@preview.test", "Eleni Teacher", "Teacher of every learner and volunteer"),
    Persona("school-admin", "preview-school-admin", "Sofia SchoolAdmin", "Admin of the preview school"),
    Persona("admin", "preview-admin", "Petra Admin", "Platform administrator"),
)

PERSONAS_BY_SLUG: dict[str, Persona] = {persona.slug: persona for persona in PERSONAS}
