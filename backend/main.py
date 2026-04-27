import uuid
import json
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os

from database import init_db, get_db, User, Group, GroupMember, Expense, ExpenseParticipant
from services import categorize_expense, calculate_balances, get_settlement_instructions

# ─── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Smart Expense Splitter", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ─── WebSocket Manager ────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, group_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(group_id, []).append(websocket)

    def disconnect(self, group_id: str, websocket: WebSocket):
        if group_id in self.connections:
            self.connections[group_id].remove(websocket)

    async def broadcast(self, group_id: str, message: dict):
        for ws in self.connections.get(group_id, []):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/{group_id}")
async def websocket_endpoint(websocket: WebSocket, group_id: str):
    await manager.connect(group_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(group_id, websocket)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: Optional[str] = None

class GroupCreate(BaseModel):
    name: str
    created_by: Optional[str] = None

class MemberAdd(BaseModel):
    user_id: str

class ParticipantIn(BaseModel):
    user_id: str
    amount: Optional[float] = None
    percentage: Optional[float] = None

class ExpenseCreate(BaseModel):
    group_id: str
    description: str
    amount: float
    paid_by: str
    split_type: str = "equal"  # equal | custom | percentage
    participants: List[ParticipantIn]
    category: Optional[str] = None

class ExpenseUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    paid_by: Optional[str] = None
    split_type: Optional[str] = None  # equal | custom | percentage
    participants: Optional[List[ParticipantIn]] = None
    category: Optional[str] = None


# ─── Helper ───────────────────────────────────────────────────────────────────
def user_dict(u: User):
    return {"id": u.id, "name": u.name, "email": u.email}

def expense_dict(e: Expense):
    return {
        "id": e.id,
        "group_id": e.group_id,
        "description": e.description,
        "amount": e.amount,
        "paid_by": e.paid_by,
        "payer_name": e.payer.name if e.payer else "",
        "category": e.category,
        "split_type": e.split_type,
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "participants": [
            {"user_id": p.user_id, "user_name": p.user.name if p.user else "", "amount": p.amount}
            for p in e.participants
        ]
    }


# ─── Users ────────────────────────────────────────────────────────────────────
@app.post("/api/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    # Deduplicate by name (case-insensitive) for simplicity
    existing = db.query(User).filter(User.name.ilike(body.name)).first()
    if existing:
        return user_dict(existing)
    user = User(id=str(uuid.uuid4()), name=body.name, email=body.email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_dict(user)


@app.get("/api/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    return user_dict(u)


@app.get("/api/users/{user_id}/summary")
def user_summary(user_id: str, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    # Find all groups this user is in
    memberships = db.query(GroupMember).filter(GroupMember.user_id == user_id).all()
    result = []
    for m in memberships:
        grp = db.query(Group).filter(Group.id == m.group_id).first()
        expenses = db.query(Expense).filter(Expense.group_id == m.group_id).all()
        exp_data = [expense_dict(e) for e in expenses]
        members = db.query(GroupMember).filter(GroupMember.group_id == m.group_id).all()
        user_map = {mm.user_id: mm.user.name for mm in members}
        bals = calculate_balances(exp_data)
        net = bals.get(user_id, 0)
        result.append({
            "group_id": grp.id,
            "group_name": grp.name,
            "net_balance": round(net, 2)
        })
    return {"user": user_dict(u), "groups": result}


# ─── Groups ───────────────────────────────────────────────────────────────────
@app.post("/api/groups", status_code=201)
def create_group(body: GroupCreate, db: Session = Depends(get_db)):
    grp = Group(id=str(uuid.uuid4()), name=body.name, created_by=body.created_by)
    db.add(grp)
    db.commit()
    db.refresh(grp)
    # Auto-add creator as member
    if body.created_by:
        member = GroupMember(group_id=grp.id, user_id=body.created_by)
        db.add(member)
        db.commit()
    return {"id": grp.id, "name": grp.name, "created_at": grp.created_at.isoformat()}


@app.get("/api/groups/{group_id}")
def get_group(group_id: str, db: Session = Depends(get_db)):
    grp = db.query(Group).filter(Group.id == group_id).first()
    if not grp:
        raise HTTPException(404, "Group not found")
    members = [{"user_id": m.user_id, "name": m.user.name} for m in grp.members]
    return {"id": grp.id, "name": grp.name, "created_at": grp.created_at.isoformat(), "members": members}


@app.post("/api/groups/{group_id}/members", status_code=201)
def add_member(group_id: str, body: MemberAdd, db: Session = Depends(get_db)):
    grp = db.query(Group).filter(Group.id == group_id).first()
    if not grp:
        raise HTTPException(404, "Group not found")
    user = db.query(User).filter(User.id == body.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    existing = db.query(GroupMember).filter(
        GroupMember.group_id == group_id, GroupMember.user_id == body.user_id
    ).first()
    if existing:
        return {"message": "Already a member"}
    db.add(GroupMember(group_id=group_id, user_id=body.user_id))
    db.commit()
    return {"message": "Member added", "user_id": body.user_id, "name": user.name}


@app.get("/api/groups/{group_id}/members")
def list_members(group_id: str, db: Session = Depends(get_db)):
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    return [{"user_id": m.user_id, "name": m.user.name} for m in members]


# ─── Expenses ─────────────────────────────────────────────────────────────────
@app.post("/api/expenses", status_code=201)
async def add_expense(body: ExpenseCreate, db: Session = Depends(get_db)):
    grp = db.query(Group).filter(Group.id == body.group_id).first()
    if not grp:
        raise HTTPException(404, "Group not found")

    # Auto-categorize if not provided
    category = body.category or categorize_expense(body.description)

    # Resolve participant amounts
    parts = body.participants
    if body.split_type == "equal":
        share = round(body.amount / len(parts), 2)
        amounts = {p.user_id: share for p in parts}
    elif body.split_type == "percentage":
        amounts = {p.user_id: round((p.percentage or 0) / 100 * body.amount, 2) for p in parts}
    else:  # custom
        amounts = {p.user_id: p.amount or 0 for p in parts}

    exp = Expense(
        id=str(uuid.uuid4()),
        group_id=body.group_id,
        description=body.description,
        amount=body.amount,
        paid_by=body.paid_by,
        category=category,
        split_type=body.split_type,
    )
    db.add(exp)
    db.flush()

    for user_id, amt in amounts.items():
        db.add(ExpenseParticipant(expense_id=exp.id, user_id=user_id, amount=amt))

    db.commit()
    db.refresh(exp)
    data = expense_dict(exp)
    await manager.broadcast(body.group_id, {"event": "expense_added", "expense": data})
    return data


@app.get("/api/groups/{group_id}/expenses")
def get_expenses(group_id: str, db: Session = Depends(get_db)):
    expenses = db.query(Expense).filter(Expense.group_id == group_id)\
        .order_by(Expense.created_at.desc()).all()
    return [expense_dict(e) for e in expenses]


@app.put("/api/expenses/{expense_id}")
async def update_expense(expense_id: str, body: ExpenseUpdate, db: Session = Depends(get_db)):
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp:
        raise HTTPException(404, "Expense not found")

    # ── Scalar fields ──────────────────────────────────────────────────────────
    if body.description is not None:
        exp.description = body.description
    if body.amount is not None:
        exp.amount = body.amount
    if body.paid_by is not None:
        exp.paid_by = body.paid_by
    if body.split_type is not None:
        exp.split_type = body.split_type
    # Auto-categorize: prefer explicit category, then re-detect from new description
    if body.category is not None:
        exp.category = body.category
    elif body.description is not None:
        exp.category = categorize_expense(body.description)

    # ── Participants: full replace when provided ────────────────────────────────
    if body.participants is not None:
        # Delete all existing participant rows
        db.query(ExpenseParticipant).filter(
            ExpenseParticipant.expense_id == expense_id
        ).delete()
        db.flush()

        # Compute new amounts
        parts = body.participants
        split_type = body.split_type or exp.split_type
        amount = body.amount if body.amount is not None else exp.amount

        if split_type == "equal":
            share = round(amount / len(parts), 2)
            amounts = {p.user_id: share for p in parts}
        elif split_type == "percentage":
            amounts = {p.user_id: round((p.percentage or 0) / 100 * amount, 2) for p in parts}
        else:  # custom
            amounts = {p.user_id: p.amount or 0 for p in parts}

        for user_id, amt in amounts.items():
            db.add(ExpenseParticipant(expense_id=expense_id, user_id=user_id, amount=amt))

    db.commit()
    db.refresh(exp)
    data = expense_dict(exp)
    await manager.broadcast(exp.group_id, {"event": "expense_updated", "expense": data})
    return data


@app.delete("/api/expenses/{expense_id}", status_code=204)
async def delete_expense(expense_id: str, db: Session = Depends(get_db)):
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp:
        raise HTTPException(404, "Expense not found")
    group_id = exp.group_id
    db.delete(exp)
    db.commit()
    await manager.broadcast(group_id, {"event": "expense_deleted", "expense_id": expense_id})


# ─── Balances & Settlements ───────────────────────────────────────────────────
@app.get("/api/groups/{group_id}/balances")
def get_balances(group_id: str, db: Session = Depends(get_db)):
    expenses = db.query(Expense).filter(Expense.group_id == group_id).all()
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    user_map = {m.user_id: m.user.name for m in members}

    exp_data = [expense_dict(e) for e in expenses]
    raw = calculate_balances(exp_data)

    # Ensure all members appear (even if 0)
    result = []
    for uid, name in user_map.items():
        bal = round(raw.get(uid, 0), 2)
        result.append({"user_id": uid, "name": name, "balance": bal})
    return result


@app.get("/api/groups/{group_id}/settlements")
def get_settlements(group_id: str, db: Session = Depends(get_db)):
    expenses = db.query(Expense).filter(Expense.group_id == group_id).all()
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    user_map = {m.user_id: m.user.name for m in members}

    exp_data = [expense_dict(e) for e in expenses]
    balances = calculate_balances(exp_data)
    return get_settlement_instructions(balances, user_map)


# ─── Analytics ────────────────────────────────────────────────────────────────
@app.get("/api/analytics/groups/{group_id}")
def group_analytics(group_id: str, db: Session = Depends(get_db)):
    expenses = db.query(Expense).filter(Expense.group_id == group_id).all()
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    member_count = len(members)

    total = sum(e.amount for e in expenses)
    by_category: Dict[str, float] = {}
    for e in expenses:
        by_category[e.category] = round(by_category.get(e.category, 0) + e.amount, 2)

    # Per-person spending
    per_person: Dict[str, float] = {}
    for e in expenses:
        per_person[e.paid_by] = round(per_person.get(e.paid_by, 0) + e.amount, 2)

    user_map = {m.user_id: m.user.name for m in members}
    per_person_named = [{"name": user_map.get(k, k), "amount": v} for k, v in per_person.items()]

    top_category = max(by_category, key=by_category.get) if by_category else "none"

    return {
        "total_spending": round(total, 2),
        "expense_count": len(expenses),
        "member_count": member_count,
        "avg_per_person": round(total / member_count, 2) if member_count else 0,
        "by_category": by_category,
        "per_person": per_person_named,
        "top_category": top_category,
    }


# ─── Static Frontend ──────────────────────────────────────────────────────────
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
