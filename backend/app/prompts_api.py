"""Редактирование промптов ИИ из панели.

Право на scope:
  global  — только админ
  network — админ либо владелец этой сети
  studio  — админ либо владелец сети, которой принадлежит студия
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import prompts as P

from .db import get_db
from .models import PromptOverride, Studio, User
from .security import get_current_user

router = APIRouter(prefix="/prompts", tags=["prompts"])

_SCOPES = ("global", "network", "studio")


class PromptIn(BaseModel):
    scope: str = Field(pattern="^(global|network|studio)$")
    scope_key: str = Field(default="", max_length=128)
    key: str
    text: str = Field(max_length=20000)


class ScopeOut(BaseModel):
    scope: str
    scope_key: str
    title: str          # «НЕЖНО» / «Пролетарская (лазер)» / «Все сети»
    editable: bool


def _can_edit(db: Session, user: User, scope: str, scope_key: str) -> bool:
    if user.is_admin:
        return True
    net = (user.network or "").strip()
    if not net:
        return False
    if scope == "network":
        return scope_key == net
    if scope == "studio":
        if not scope_key.isdigit():
            return False
        st = db.get(Studio, int(scope_key))
        return st is not None and st.network == net
    return False


def _scopes_for(db: Session, user: User) -> list[ScopeOut]:
    out = []
    if user.is_admin:
        out.append(ScopeOut(scope="global", scope_key="", title="Все сети", editable=True))
    q = db.query(Studio).order_by(Studio.network, Studio.name)
    if not user.is_admin:
        q = q.filter(Studio.network == (user.network or ""))
    studios = q.all()
    for net in sorted({s.network for s in studios if s.network}):
        out.append(ScopeOut(scope="network", scope_key=net, title=f"Сеть «{net}»",
                            editable=_can_edit(db, user, "network", net)))
    for s in studios:
        title = (f"{s.network} / " if s.network else "") + s.name
        out.append(ScopeOut(scope="studio", scope_key=str(s.id), title=title,
                            editable=_can_edit(db, user, "studio", str(s.id))))
    return out


@router.get("")
def list_prompts(scope: str = "global", scope_key: str = "",
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Промпты выбранного уровня: собственное значение и то, что действует сейчас.

    `value` — что задано именно на этом уровне (пусто = наследуем).
    `effective` — что реально уйдёт в модель с учётом наследования.
    """
    if scope not in _SCOPES:
        raise HTTPException(status_code=400, detail="Bad scope")
    own = {r.key: r.text for r in db.query(PromptOverride)
           .filter(PromptOverride.scope == scope, PromptOverride.scope_key == scope_key).all()}

    # Что действует: собираем ту же цепочку, что и prompts.resolve.
    eff = dict(P.DEFAULTS)
    eff.update({r.key: r.text for r in db.query(PromptOverride)
                .filter(PromptOverride.scope == "global").all() if (r.text or "").strip()})
    if scope in ("network", "studio"):
        net = scope_key
        if scope == "studio" and scope_key.isdigit():
            st = db.get(Studio, int(scope_key))
            net = (st.network or "") if st else ""
        if net:
            eff.update({r.key: r.text for r in db.query(PromptOverride)
                        .filter(PromptOverride.scope == "network",
                                PromptOverride.scope_key == net).all() if (r.text or "").strip()})
    if scope == "studio":
        eff.update({k: v for k, v in own.items() if (v or "").strip()})

    return {
        "scope": scope, "scope_key": scope_key,
        "editable": _can_edit(db, user, scope, scope_key),
        "scopes": [s.model_dump() for s in _scopes_for(db, user)],
        "items": [
            {"key": k, "title": P.TITLES.get(k, k), "default": P.DEFAULTS[k],
             "value": own.get(k, ""), "effective": eff.get(k, P.DEFAULTS[k])}
            for k in P.KEYS
        ],
    }


@router.put("")
def save_prompt(body: PromptIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    if body.key not in P.KEYS:
        raise HTTPException(status_code=400, detail=f"Неизвестный промпт: {body.key}")
    if not _can_edit(db, user, body.scope, body.scope_key):
        raise HTTPException(status_code=403, detail="Нет прав на этот уровень")
    if body.key == "criteria" and body.text.strip() and not P.criteria_list(body.text):
        raise HTTPException(status_code=400,
                            detail="Критерии: нужна хотя бы одна строка вида «ключ: описание»")

    row = (db.query(PromptOverride)
           .filter(PromptOverride.scope == body.scope,
                   PromptOverride.scope_key == body.scope_key,
                   PromptOverride.key == body.key).first())
    if not body.text.strip():
        if row:                       # пустой текст = вернуть наследование
            db.delete(row)
    elif row:
        row.text, row.updated_by = body.text, user.username
    else:
        db.add(PromptOverride(scope=body.scope, scope_key=body.scope_key,
                              key=body.key, text=body.text, updated_by=user.username))
    db.commit()
    P.invalidate()                    # следующий разбор пойдёт уже по новому промпту
    return {"status": "ok"}
