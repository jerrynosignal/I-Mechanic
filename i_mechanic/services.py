"""Application services for project-scoped analysis and conversation."""
from __future__ import annotations

import json
from typing import Any, Callable

from .storage import Repository


class RaceEngineerService:
    def __init__(self, repository: Repository, coach: Any):
        self.repository = repository
        self.coach = coach

    def analyze_session(
        self,
        session_id: int,
        model: str,
        base_url: str,
        provider: str,
        ask_ai: bool = True,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"Unknown session: {session_id}")
        self.repository.update_session(session_id, status="parsing", error=None)
        if on_progress:
            on_progress("Parsing telemetry...")
        try:
            brief = self.coach.build_brief(session["telemetry_path"])
            self.repository.update_session(session_id, brief_json=brief)
            if "error" in brief:
                self.repository.update_session(session_id, status="incomplete", error=brief["error"])
                return self.repository.get_session(session_id) or {}
            if not ask_ai:
                self.repository.update_session(session_id, status="analyzed")
                return self.repository.get_session(session_id) or {}

            self.repository.update_session(session_id, status="asking_ai")
            if on_progress:
                on_progress(f"Asking {provider}...")
            project = self.repository.get_project(session["project_id"])
            context = build_project_context(self.repository, project, session_id=session_id)
            assessment = self.coach.run_engineer(
                brief,
                session["feedback"] or "Diagnose from telemetry alone.",
                model=model,
                base_url=base_url,
                provider=provider,
                project_context=context,
            )
            self.repository.update_session(session_id, assessment_json=assessment, status="complete", error=None)
        except Exception as exc:
            self.repository.update_session(session_id, status="ai_failed", error=str(exc))
            raise
        return self.repository.get_session(session_id) or {}

    def chat(
        self,
        project_id: int,
        content: str,
        model: str,
        base_url: str,
        provider: str,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ValueError("Chat content cannot be empty")
        self.repository.add_message(project_id, "user", content, session_id)
        project = self.repository.get_project(project_id)
        context = build_project_context(self.repository, project, session_id=session_id)
        response = self.coach.run_engineer(
            {"project_chat": True, "project": project},
            content,
            model=model,
            base_url=base_url,
            provider=provider,
            project_context=context,
        )
        assistant_content = response.get("session_summary") or json.dumps(response, ensure_ascii=False)
        message = self.repository.add_message(project_id, "assistant", assistant_content, session_id)
        return {"message": message, "response": response}


def build_project_context(
    repository: Repository,
    project: dict[str, Any] | None,
    session_id: int | None = None,
    session_limit: int = 5,
    message_limit: int = 12,
) -> dict[str, Any]:
    """Build bounded, explicit context so history remains useful and predictable."""
    if project is None:
        return {"project": None, "recent_sessions": [], "recent_messages": []}
    sessions = repository.list_sessions(project["id"], limit=session_limit)
    messages = repository.list_messages(project["id"], limit=message_limit)
    return {
        "project": {
            "name": project["name"],
            "game": project["game"],
            "car": project["car"],
            "track": project["track"],
            "notes": project["notes"],
        },
        "current_session_id": session_id,
        "recent_sessions": [
            {
                "id": item["id"],
                "feedback": _trim(item["feedback"], 1200),
                "status": item["status"],
                "brief": _compact_brief(item["brief_json"]),
                "assessment": _compact_assessment(item["assessment_json"]),
            }
            for item in sessions
        ],
        "recent_messages": [
            {"role": item["role"], "content": _trim(item["content"], 1200), "session_id": item["session_id"]}
            for item in messages
        ],
    }


def _compact_brief(brief: dict[str, Any] | None) -> dict[str, Any] | None:
    if not brief:
        return brief
    return {
        "file": brief.get("file"),
        "venue": brief.get("venue"),
        "driving_time_s": brief.get("driving_time_s"),
        "speed_kmh_avg": brief.get("speed_kmh_avg"),
        "speed_kmh_max": brief.get("speed_kmh_max"),
        "data_quality": brief.get("data_quality"),
        "temp_balance": brief.get("temp_balance"),
        "electronics": brief.get("electronics"),
        "wheel_slip": brief.get("wheel_slip"),
        "balance_proxy": brief.get("balance_proxy"),
    }


def _trim(value: str | None, limit: int) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[:limit] + "..."


def _compact_assessment(assessment: dict[str, Any] | None) -> dict[str, Any] | None:
    if not assessment:
        return assessment
    return {
        "session_summary": assessment.get("session_summary"),
        "issues_found": assessment.get("issues_found", [])[:4],
        "setup_changes": assessment.get("setup_changes", [])[:4],
    }
