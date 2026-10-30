"""Матрица ролей из ТЗ, строка за строкой."""

import pytest

from app import permissions as p
from app.constants import EntityType, Role
from app.permissions import Actor

OWNER, DIRECTOR, TEAM, GUEST = (Actor(i, r) for i, r in enumerate(Role, start=1))
SHOT = EntityType.SHOT


def test_everyone_sees_but_guest_has_no_journal():
    assert all(p.can_view(a) for a in (OWNER, DIRECTOR, TEAM, GUEST))
    assert [p.can_view_journal(a) for a in (OWNER, DIRECTOR, TEAM, GUEST)] == [
        True,
        True,
        True,
        False,
    ]


@pytest.mark.parametrize(
    ("actor", "expected"), [(OWNER, True), (DIRECTOR, True), (TEAM, True), (GUEST, False)]
)
def test_upload_and_export(actor, expected):
    assert p.can_upload(actor) is expected
    assert p.can_export(actor) is expected


def test_owner_edits_everything_including_users():
    assert p.can_edit(OWNER, SHOT, owner_id=99, fields={"description"})
    assert p.can_edit(OWNER, EntityType.USER, owner_id=None, fields={"role"})


def test_director_edits_everything_except_participants():
    assert p.can_edit(DIRECTOR, SHOT, owner_id=99, fields={"description"})
    assert not p.can_edit(DIRECTOR, EntityType.USER, owner_id=None, fields={"role"})


def test_team_edits_status_of_any_card_but_content_only_of_own():
    assert p.can_edit(TEAM, SHOT, owner_id=99, fields={"status"})
    assert not p.can_edit(TEAM, SHOT, owner_id=99, fields={"description"})
    assert not p.can_edit(TEAM, SHOT, owner_id=99, fields={"status", "description"})
    assert p.can_edit(TEAM, SHOT, owner_id=TEAM.id, fields={"description", "status"})
    assert not p.can_edit(TEAM, EntityType.USER, owner_id=None, fields={"role"})


def test_guest_edits_nothing_but_may_comment():
    assert not p.can_edit(GUEST, SHOT, owner_id=GUEST.id, fields={"status"})
    assert p.can_create(GUEST, EntityType.COMMENT)
    assert not p.can_create(GUEST, SHOT)


def test_participants_are_never_created_by_hand():
    assert not any(p.can_create(a, EntityType.USER) for a in (OWNER, DIRECTOR, TEAM, GUEST))


def test_delete_rules():
    assert p.can_delete(OWNER, owner_id=99)
    assert p.can_delete(DIRECTOR, owner_id=99)
    assert p.can_delete(TEAM, owner_id=TEAM.id)
    assert not p.can_delete(TEAM, owner_id=99)
    assert not p.can_delete(GUEST, owner_id=GUEST.id)


def test_only_owner_restores_and_manages_users():
    assert [p.can_restore(a) for a in (OWNER, DIRECTOR, TEAM, GUEST)] == [True, False, False, False]
    assert [p.can_manage_users(a) for a in (OWNER, DIRECTOR, TEAM, GUEST)] == [
        True,
        False,
        False,
        False,
    ]
