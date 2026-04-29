import secrets
from typing import Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.models import Project, User, project_members
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectRequest
from app.core.security import get_password_hash
from app.core.tasks import enqueue_email_task, enqueue_websocket_task
from app.tasks.financials import process_payout_calculation
from app.core.email import send_email

class ProjectService:
    @staticmethod
    async def create_project(db: AsyncSession, project_in: ProjectCreate) -> Project:
        project_data = project_in.model_dump(exclude={"member_ids"})
        project = Project(**project_data)

        if project_in.member_ids:
            res = await db.execute(select(User).where(User.id.in_(project_in.member_ids)))
            project.members = res.scalars().all()

        db.add(project)
        await db.commit()
        await db.refresh(project, attribute_names=["members"])
        return project

    @staticmethod
    async def update_project(db: AsyncSession, project: Project, project_in: ProjectUpdate) -> Project:
        update_data = project_in.model_dump(exclude_unset=True, exclude={"member_ids"})

        trigger_payout = False
        if project_in.status == "completed" and project.status != "completed":
            trigger_payout = True

        for field, value in update_data.items():
            setattr(project, field, value)

        if project_in.member_ids is not None:
            res = await db.execute(select(User).where(User.id.in_(project_in.member_ids)))
            project.members = res.scalars().all()

        await db.commit()
        await db.refresh(project, attribute_names=["members"])

        if trigger_payout:
            process_payout_calculation.delay(project.id)

        if project_in.status and project.client_id:
            await ProjectService._notify_status_change(db, project)

        if project_in.member_ids is not None:
            for member_id in project_in.member_ids:
                enqueue_websocket_task(
                    user_id=member_id,
                    message={
                        "type": "project_assigned",
                        "title": "Added to Project 🚀",
                        "message": f"You've been added to the project: {project.name}",
                        "project_id": project.id,
                    },
                )
        return project

    @staticmethod
    async def request_project(db: AsyncSession, project_in: ProjectRequest) -> Project:
        stmt = select(User).where(User.email == project_in.client_email)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            temp_password = secrets.token_urlsafe(16)
            user = User(
                email=project_in.client_email,
                full_name=project_in.client_full_name,
                phone_number=project_in.client_phone,
                password_hash=get_password_hash(temp_password),
                role="Client",
                status="approved",
            )
            db.add(user)
            await db.flush()

        project_data = project_in.model_dump(exclude={"client_email", "client_full_name", "client_phone"})
        project = Project(
            **project_data,
            client_id=user.id,
            status="pending"
        )
        db.add(project)
        await db.commit()
        await db.refresh(project, attribute_names=["members"])

        await send_email(
            recipient_email="hr@titancode.tech",
            subject=f"🔥 NEW LEAD: {project.name}",
            body=(
                f"Hello HR Team,\n\n"
                f"A new client has used the Unified Hire Us form!\n\n"
                f"CLIENT DETAILS:\n"
                f"- Name: {project_in.client_full_name}\n"
                f"- Email: {project_in.client_email}\n"
                f"- Phone: {project_in.client_phone or 'Not provided'}\n\n"
                f"PROJECT DETAILS:\n"
                f"- Title: {project.name}\n"
                f"- Budget: ${project.budget}\n"
                f"- Description: {project.description}\n\n"
                "ACTION REQUIRED:\n"
                "Please contact the client via WhatsApp/Email to finalize the project scope."
            )
        )
        return project

    @staticmethod
    async def _notify_status_change(db: AsyncSession, project: Project):
        client_result = await db.execute(select(User).where(User.id == project.client_id))
        client = client_result.scalars().first()

        status_display = project.status.upper()
        status_messages = {
            "active": "Great news! Work on your project has officially started.",
            "completed": "Your project has been completed. Our team will follow up shortly.",
            "cancelled": "Your project has been cancelled. Please contact us for details.",
            "pending": "Your project is now under review.",
        }
        status_note = status_messages.get(project.status, f"Status changed to: {project.status}")

        enqueue_websocket_task(
            user_id=project.client_id,
            message={
                "type": "project_update",
                "title": f"Project Update: {project.name}",
                "message": status_note,
                "project_id": project.id,
                "status": project.status,
            },
        )

        if client and client.email:
            enqueue_email_task(
                recipient_email=client.email,
                subject=f"Project Update: {project.name} — {status_display}",
                body=(f"Hi {client.full_name},\n\n{status_note}\n\n"
                      f"Project: {project.name}\nStatus:  {status_display}\n\n"
                      f"If you have any questions, just reply to this email.\n\n— The TitanCode Team"),
                html_content=(f"<p>Hi <strong>{client.full_name}</strong>,</p><p>{status_note}</p>"
                             f"<table style='border-collapse:collapse;font-family:sans-serif;'>"
                             f"<tr><td style='padding:6px;font-weight:bold;'>Project</td><td style='padding:6px;'>{project.name}</td></tr>"
                             f"<tr><td style='padding:6px;font-weight:bold;'>Status</td><td style='padding:6px;'>{status_display}</td></tr>"
                             f"</table><p>If you have any questions, just reply to this email.</p><br><p>— The TitanCode Team</p>"),
            )
