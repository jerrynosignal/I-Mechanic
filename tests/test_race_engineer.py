import io
import json
import tempfile
from threading import Thread
import unittest
from pathlib import Path
from unittest.mock import patch

from i_mechanic import coach
from i_mechanic.desktop.qt_app import PROVIDER_LABELS
from i_mechanic.services import RaceEngineerService, build_project_context
from i_mechanic.storage import Repository


class FakeCoach:
    def build_brief(self, telemetry_path):
        return {"file": Path(telemetry_path).name, "data_quality": {"status": "ready"}}

    def run_engineer(self, brief, feedback, **kwargs):
        context = kwargs["project_context"]
        return {
            "session_summary": f"{context['project']['track']}: {feedback}",
            "issues_found": [],
            "setup_changes": [],
        }


class StorageAndServiceTests(unittest.TestCase):
    def test_qt_provider_choices_match_coach_providers(self):
        self.assertEqual({provider for provider, _label in PROVIDER_LABELS}, set(coach.PROVIDERS))

    def test_hosted_provider_defaults_and_environment_overrides(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "custom-model"}):
            defaults = coach.provider_defaults("openai")
        self.assertEqual(defaults["base_url"], "https://api.openai.com/v1")
        self.assertEqual(defaults["model"], "custom-model")
        self.assertEqual(defaults["api_key_env"], "OPENAI_API_KEY")
        self.assertIn("openrouter", coach.PROVIDERS)
        self.assertIn("groq", coach.PROVIDERS)
        self.assertIn("together", coach.PROVIDERS)

    def test_hosted_model_discovery_uses_bearer_key(self):
        response = io.BytesIO(json.dumps({"data": [{"id": "test-model"}]}).encode())
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "urllib.request.urlopen", return_value=response
        ) as open_url:
            models = coach.list_models("openai")
        request = open_url.call_args.args[0]
        self.assertEqual(models, ["test-model"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_project_metadata_can_be_updated(self):
        with tempfile.TemporaryDirectory() as folder, Repository(Path(folder) / "project.sqlite3") as repository:
            project = repository.create_project("Draft", "ACC", "", "")
            updated = repository.update_project(project["id"], name="Monza Porsche", car="992 GT3 R", track="Monza")
            self.assertEqual(updated["name"], "Monza Porsche")
            self.assertEqual(repository.get_project(project["id"])["track"], "Monza")

    def test_repository_supports_worker_thread_access(self):
        with tempfile.TemporaryDirectory() as folder, Repository(Path(folder) / "thread.sqlite3") as repository:
            project = repository.create_project("Thread test")
            errors = []

            def worker():
                try:
                    session = repository.create_session(project["id"], "run.ld", "feedback")
                    self.assertEqual(repository.get_session(session["id"])["feedback"], "feedback")
                except Exception as exc:
                    errors.append(exc)

            thread = Thread(target=worker)
            thread.start()
            thread.join()
            self.assertEqual(errors, [])

    def test_project_session_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "race-engineer.sqlite3"
            with Repository(path) as repository:
                project = repository.create_project("Monza test", "ACC", "992 GT3 R", "Monza")
                session = repository.create_session(project["id"], "run.ld", "Entry understeer")
                repository.update_session(session["id"], status="analyzed", brief_json={"speed": 200})
                repository.add_message(project["id"], "user", "What should I test next?", session["id"])
            with Repository(path) as repository:
                saved = repository.list_sessions(project["id"])[0]
                self.assertEqual(saved["brief_json"], {"speed": 200})
                self.assertEqual(repository.list_messages(project["id"])[0]["content"], "What should I test next?")

    def test_analysis_and_chat_keep_project_context(self):
        with tempfile.TemporaryDirectory() as folder, Repository(Path(folder) / "test.sqlite3") as repository:
            project = repository.create_project("Porsche", track="Spa")
            session = repository.create_session(project["id"], "run.ld", "Nervous over kerbs")
            service = RaceEngineerService(repository, FakeCoach())
            saved = service.analyze_session(session["id"], "model", "url", "lmstudio")
            self.assertEqual(saved["status"], "complete")
            self.assertIn("Spa", saved["assessment_json"]["session_summary"])
            result = service.chat(project["id"], "What changed?", "model", "url", "lmstudio")
            self.assertIn("Spa", result["response"]["session_summary"])
            context = build_project_context(repository, project, message_limit=1)
            self.assertEqual(len(context["recent_messages"]), 1)

    def test_project_context_bounds_long_text(self):
        with tempfile.TemporaryDirectory() as folder, Repository(Path(folder) / "context.sqlite3") as repository:
            project = repository.create_project("Bounded context")
            session = repository.create_session(project["id"], "run.ld", "x" * 5000)
            repository.add_message(project["id"], "user", "y" * 5000, session["id"])
            context = build_project_context(repository, project)
            self.assertLessEqual(len(context["recent_sessions"][0]["feedback"]), 1203)
            self.assertLessEqual(len(context["recent_messages"][0]["content"]), 1203)


if __name__ == "__main__":
    unittest.main()
