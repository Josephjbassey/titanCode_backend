try:
    from enum import StrEnum
except ImportError:  # Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)
        pass


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
