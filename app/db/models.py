"""
TitanCode Technologies — Database Models
==========================================
This module defines all SQLAlchemy ORM models that map to PostgreSQL tables.
Each class below corresponds to one database table.

Models defined:
    - Department:  Company departments (Frontend, Backend, etc.)
    - User:        All platform users (CEO, Admin, Manager, Member, Client, etc.)
    - Application: Membership applications from users wanting to join a department.
    - Project:     Client projects managed by the company.
    - Task:        Individual tasks within a project, assigned to team members.

Relationships:
    - A Department has many Users.
    - A User belongs to one Department.
    - A Project has many Tasks.
    - A Task belongs to one Project.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric, DateTime, Table, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


def utcnow():
    """Return the current UTC time as a timezone-aware datetime.

    This replaces the deprecated `datetime.utcnow()` which returns a
    naive datetime (no timezone info). Timezone-aware timestamps are
    essential for correct time comparisons across different servers.
    """
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# DEPARTMENT MODEL
# ═══════════════════════════════════════════════════════════════════════
class Department(Base):
    """
    Represents a company department (e.g. Frontend, Backend, UI/UX).

    Columns:
        id:           Primary key, auto-incremented.
        name:         Unique department name (e.g. "Backend").
        description:  Optional description of the department's purpose.
        manager_id:   FK → users.id — the user who manages this department.
        assistant_id: FK → users.id — the user who assists the manager.
        created_at:   Timestamp when the department was created.
    """
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assistant_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # One-to-many: a department has many users
    users = relationship("User", back_populates="department", foreign_keys="User.department_id")


# ═══════════════════════════════════════════════════════════════════════
# USER MODEL
# ═══════════════════════════════════════════════════════════════════════
class User(Base):
    """
    Represents every person on the platform — team members, admins, and clients.

    Roles (enforced by RBAC):
        CEO, Admin, Manager, Assistant, Member, Applicant, Client

    Status:
        pending   → newly registered, awaiting approval
        approved  → active user
        rejected  → application denied

    Columns:
        id, full_name, email, password_hash:  Core identity fields.
        country, phone_number:                Contact info.
        github_url, portfolio_url:            Developer profile links.
        role:           The user's RBAC role (default: "Member").
        department_id:  FK → departments.id — which department they belong to.
        experience_years, skills, tools:      Developer metadata.
        bank_name, bank_account_number:       Payment info for salary payouts.
        status:         Account approval status.
        created_at:     Registration timestamp.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)   # Never store plain text!
    country = Column(String(100), nullable=True)
    phone_number = Column(String(50), nullable=True)
    github_url = Column(String(255), nullable=True)
    portfolio_url = Column(String(255), nullable=True)
    role = Column(String(50), default="Member", nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    experience_years = Column(Integer, default=0)
    skills = Column(Text, nullable=True)                  # Comma-separated list
    tools = Column(Text, nullable=True)                   # Comma-separated list
    bank_name = Column(String(255), nullable=True)
    bank_account_number = Column(String(255), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    # ── Magic link fields (Client onboarding) ──────────────────────────
    magic_link_token = Column(String(512), nullable=True, index=True)
    magic_link_expires_at = Column(DateTime(timezone=True), nullable=True)
    onboarded = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Many-to-one: a user belongs to one department
    department = relationship("Department", back_populates="users", foreign_keys=[department_id])


# ═══════════════════════════════════════════════════════════════════════
# APPLICATION MODEL
# ═══════════════════════════════════════════════════════════════════════
class Application(Base):
    """
    Represents a membership application submitted by a user to join a department.

    Workflow:
        1. User submits application (status = "pending").
        2. A Manager/Admin reviews it.
        3. Status changes to "approved" or "rejected".

    Columns:
        id:            Primary key.
        user_id:       FK → users.id — the applicant.
        department_id: FK → departments.id — target department.
        github_url:    Applicant's GitHub profile for review.
        portfolio:     Applicant's portfolio link.
        status:        pending | approved | rejected
        reviewed_by:   FK → users.id — who reviewed the application.
        reviewed_at:   When the review happened.
    """
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    github_url = Column(String(255), nullable=True)
    portfolio = Column(String(255), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)


# ═══════════════════════════════════════════════════════════════════════
# PROJECT & MEMBERS ASSOCIATION
# ═══════════════════════════════════════════════════════════════════════

project_members = Table(
    "project_members",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("projects.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


# ═══════════════════════════════════════════════════════════════════════
# PROJECT MODEL
# ═══════════════════════════════════════════════════════════════════════
class Project(Base):
    """
    Represents a client project managed by the company.

    Status lifecycle:
        pending → active → completed
                        ↘ cancelled

    Columns:
        id:          Primary key.
        name:        Project title.
        description: What the project is about.
        client_id:   FK → users.id — the client who requested the project.
        budget:      Total budget (stored as Numeric for precision).
        deadline:    When the project is due.
        status:      pending | active | completed | cancelled
        created_at:  Timestamp.
    """
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    budget = Column(Numeric(10, 2), default=0.00)         # Up to 99,999,999.99
    deadline = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # One-to-many: a project has many tasks
    tasks = relationship("Task", back_populates="project")
    
    # Many-to-many: a project has many assigned members
    members = relationship("User", secondary=project_members, backref="assigned_projects")


# ═══════════════════════════════════════════════════════════════════════
# TASK MODEL
# ═══════════════════════════════════════════════════════════════════════
class Task(Base):
    """
    Represents an individual task within a project, assigned to a team member.

    Status lifecycle:
        open → in_progress → completed

    Columns:
        id:            Primary key.
        project_id:    FK → projects.id — the parent project.
        assigned_user: FK → users.id — who is working on this task.
        task_title:    Short title for the task.
        description:   Detailed description of what needs to be done.
        status:        open | in_progress | completed
        deadline:      When this task is due.
        created_at:    Timestamp.
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    assigned_user = Column(Integer, ForeignKey("users.id"), nullable=False)
    task_title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="open", nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Many-to-one: a task belongs to one project
    project = relationship("Project", back_populates="tasks")


# ═══════════════════════════════════════════════════════════════════════
# WALLET MODEL
# ═══════════════════════════════════════════════════════════════════════
class Wallet(Base):
    """
    Represents a user's financial wallet on the platform.

    Each user has exactly one wallet. The balance tracks their
    current available earnings. All balance changes are logged
    as Transaction records for a full audit trail.

    Columns:
        id:         Primary key.
        user_id:    FK → users.id — one wallet per user (unique constraint).
        balance:    Current balance in the wallet (Numeric for precision).
        currency:   Currency code (default: "USD").
        created_at: When the wallet was created.
        updated_at: Last time the balance was modified.
    """
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Numeric(12, 2), default=0.00)          # Up to 9,999,999,999.99
    currency = Column(String(10), default="USD", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    owner = relationship("User", backref="wallet", foreign_keys=[user_id])
    transactions = relationship("Transaction", back_populates="wallet")


# ═══════════════════════════════════════════════════════════════════════
# TRANSACTION MODEL
# ═══════════════════════════════════════════════════════════════════════
class Transaction(Base):
    """
    Represents a single financial transaction (credit or debit)
    on a user's wallet. Provides a full audit trail of all balance changes.

    Transaction types:
        credit  → Money added to wallet (e.g., project payment, bonus).
        debit   → Money removed from wallet (e.g., withdrawal, fee).

    Columns:
        id:               Primary key.
        wallet_id:        FK → wallets.id — which wallet this belongs to.
        amount:           The transaction amount (always positive).
        transaction_type: "credit" or "debit".
        description:      Human-readable reason for the transaction.
        reference_id:     Optional — links to a project or task ID for context.
        created_at:       When the transaction occurred.
    """
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)          # Always positive
    transaction_type = Column(String(20), nullable=False)    # "credit" or "debit"
    description = Column(String(500), nullable=True)         # e.g., "Payment for Project #12"
    reference_id = Column(String(100), nullable=True)        # Optional link to project/task
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Many-to-one: a transaction belongs to one wallet
    wallet = relationship("Wallet", back_populates="transactions")


# ═══════════════════════════════════════════════════════════════════════
# REVENUE & PRODUCT MODELS
# ═══════════════════════════════════════════════════════════════════════

class Product(Base):
    """
    Represents an external or internal tool (e.g. SaaS) that generates revenue.
    Each product has a secret API key used to report earnings automatically.
    The raw key is never stored; we persist a key-id + hash.

    Columns:
        id:               Primary key.
        name:             Product name (e.g. "TitanChat", "CodeGuard").
        product_type:     SaaS | Internal Tool | API Service.
        api_key_id:       Public key identifier prefix for lookup.
        api_key_hash:     HMAC-SHA256 digest used for API key verification.
        revenue_endpoint: URL where the product sends revenue data.
        product_url:      The public URL of the product.
        created_by:       FK → users.id — the admin who registered the product.
        created_at:       Timestamp.
    """
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    product_type = Column(String(100), nullable=True)
    api_key_id = Column(String(64), unique=True, index=True, nullable=False)
    api_key_hash = Column(String(255), unique=True, index=True, nullable=False)
    revenue_endpoint = Column(String(500), nullable=True)
    product_url = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    revenues = relationship("Revenue", back_populates="product")


# ═══════════════════════════════════════════════════════════════════════
# REVENUE MODEL
# ═══════════════════════════════════════════════════════════════════════
class Revenue(Base):
    """
    Tracks incoming revenue reported by external TitanCode products.
    Each entry is a historical snapshot of earnings.

    Columns:
        id:          Primary key.
        product_id:  FK → products.id — which product generated this revenue.
        amount:      The amount of money generated.
        source:      Description of the source (e.g. "Subscription", "Ad Revenue").
        date:        The date the revenue was generated/reported.
        created_at:  Internal system timestamp.
    """
    __tablename__ = "revenues"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    source = Column(String(255), nullable=True)
    date = Column(DateTime(timezone=True), default=utcnow)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    product = relationship("Product", back_populates="revenues")


# ═══════════════════════════════════════════════════════════════════════
# FINANCIAL MODELS
# ═══════════════════════════════════════════════════════════════════════

class CompanyWallet(Base):
    """
    Represents the central company treasury. All product revenue
    flows here before being distributed or withdrawn.

    Columns:
        id:         Primary key.
        balance:    Total company funds (across all products).
        currency:   Default currency is "USD".
        updated_at: Last time the treasury balance was modified.
    """
    __tablename__ = "company_wallets"

    id = Column(Integer, primary_key=True, index=True)
    balance = Column(Numeric(15, 2), default=0.00)
    currency = Column(String(10), default="USD", nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Withdrawal(Base):
    """
    Tracks payout requests from team members/users.
    Funds are moved from corporate holdings to private accounts.

    Workflow:
        pending → approved → paid (Success)
               ↘ rejected (Funds returned to user wallet)

    Columns:
        id:          Primary key.
        user_id:     FK → users.id — who is requesting the payout.
        amount:      The requested amount of money.
        status:      Current state (pending/approved/etc).
        bank_info:   Optional override of user's default bank details.
        reviewed_by: FK → users.id — the admin who processed this.
        created_at:  Timestamp.
    """
    __tablename__ = "withdrawals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    bank_info = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    external_payout_idempotency_key = Column(String(128), nullable=True, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════════════════════════════════════
# MEETING MODEL
# ═══════════════════════════════════════════════════════════════════════
class Meeting(Base):
    """
    Represents a scheduled meeting between team members and clients.

    Columns:
        id:             Primary key.
        title:          Meeting subject.
        description:    Agenda or notes.
        meeting_type:   video | audio | in_person
        meeting_link:   External link (Agora, WebRTC, Zoom).
        scheduled_at:   When the meeting is set to happen.
        created_by:     FK → users.id — who scheduled it.
        department_id:  FK → departments.id — which department this relates to.
        client_id:      FK → users.id — the client involved (optional).
        status:         scheduled | cancelled | completed
        created_at:     Timestamp.
    """
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    meeting_type = Column(String(50), default="video", nullable=False)
    meeting_link = Column(String(500), nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(50), default="scheduled", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ═══════════════════════════════════════════════════════════════════════
# PAYOUT INVOICE MODEL
# ═══════════════════════════════════════════════════════════════════════
class PayoutInvoice(Base):
    """
    Represents an internal invoice for project profit distribution.
    
    This record is created when a project is COMPLETED. It calculates
    the 70/30 split between team members and company operations.
    
    Idempotency: One PayoutInvoice per Project (unique constraint on project_id).
    
    Columns:
        id:                  Primary key.
        project_id:          FK → projects.id — unique to prevent double-payout.
        total_payout_amount: The 70% fraction distributed to members.
        is_approved:         Admin toggle before final record locking.
        processed_at:        Timestamp of when the payout was finalized.
        created_at:          Initial creation timestamp.
    """
    __tablename__ = "payout_invoices"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True, nullable=False)
    total_payout_amount = Column(Numeric(12, 2), nullable=False)
    team_payout_amount = Column(Numeric(12, 2), nullable=False)
    company_payout_amount = Column(Numeric(12, 2), nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    project = relationship("Project", backref="payout_invoice")


# ═══════════════════════════════════════════════════════════════════════
# CLIENT INQUIRY MODEL (Hire Us Form)
# ═══════════════════════════════════════════════════════════════════════
class ClientInquiry(Base):
    """
    Stores submissions from the public "Hire Us" contact form.
    Each record represents a potential client who wants to work with TitanCode.

    Workflow:
        1. Prospect submits public form → status = "new"
        2. HR contacts them manually → status = "contacted"
        3. Admin sends magic link    → status = "converted" (client account created)

    Columns:
        id:               Primary key.
        full_name:        Prospect's full name.
        email:            Contact email (unique per inquiry).
        company:          Their company or project name.
        phone:            Contact phone number.
        service_interest: What service they're interested in (e.g. "Web App").
        message:          Their message / project description.
        status:           new | contacted | converted
        created_at:       Timestamp of submission.
    """
    __tablename__ = "client_inquiries"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    service_interest = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(50), default="new", nullable=False)  # new | contacted | converted
    created_at = Column(DateTime(timezone=True), default=utcnow)
