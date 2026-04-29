from enum import StrEnum


class UserRole(StrEnum):
    CEO = "CEO"
    ADMIN = "Admin"
    MANAGER = "Manager"
    ASSISTANT = "Assistant"
    MEMBER = "Member"
    APPLICANT = "Applicant"
    CLIENT = "Client"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProjectStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
