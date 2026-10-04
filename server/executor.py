"""Skill execution.

Turns a routed command into a real run: assemble the prompt from the
shared core contract plus the routed skill, hand it to the engine
adapter, and write the result into the vault.

Three rules shape this:

- The vault is the source of truth, so a run that produces something
  writes it to the vault and reports where.
- A skill's `writes:` frontmatter is a contract, not documentation. A run
  may only write inside the paths its skill declares.
- Nothing is overwritten and nothing is deleted. Each run creates a new
  timestamped note.

Runs happen on a background thread: a local model can take a minute, and
the HUD must not block on it.
"""

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engine import EngineError

MAX_JOBS = 200
PREFERRED_WRITE_ROOT = "/output"


def strip_frontmatter(text):
    """Return a skill's body, without its YAML-ish frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text.strip()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return text.strip()


def build_prompt(core_body, skill_body, command, context=None):
    """Assemble the prompt: shared contract, the skill, state, the ask."""
    parts = [
        "# Operating contract",
        core_body,
        "# Active skill",
        skill_body,
    ]
    if context:
        lines = [f"- {key}: {value}" for key, value in context.items()]
        parts += ["# Current state", "\n".join(lines)]
    parts += [
        "# Request",
        f"The operator ran: {command}",
        "Carry out the active skill for this request. Follow its output "
        "contract. Report only what you can support; say plainly when "
        "something is unknown.",
    ]
    return "\n\n".join(parts)


def _write_root(skill, vault_dir):
    """The vault directory this skill is allowed to write into."""
    declared = [str(path) for path in (skill.get("writes") or []) if str(path).strip()]
    if not declared:
        return None
    chosen = next((p for p in declared if p.startswith(PREFERRED_WRITE_ROOT)), declared[0])
    root = (Path(vault_dir) / chosen.lstrip("/")).resolve()
    vault_root = Path(vault_dir).resolve()
    # A skill cannot grant itself a path outside the vault.
    if not root.is_relative_to(vault_root):
        return None
    return root


def output_path(skill, vault_dir, now=None):
    """Where this run's note goes, or None when the skill writes nothing."""
    root = _write_root(skill, vault_dir)
    if root is None:
        return None
    now = now or datetime.now()
    stem = skill.get("name") or Path(skill.get("file", "skill")).stem
    stamp = now.strftime("%Y-%m-%d-%H%M%S")
    candidate = root / stem / f"{stamp}-{stem}.md"
    # Never overwrite: a second run in the same second gets its own file.
    counter = 2
    while candidate.exists():
        candidate = root / stem / f"{stamp}-{stem}-{counter}.md"
        counter += 1
    return candidate


def write_output(path, skill, command, engine_label, body):
    """Write the run's note, with provenance, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"---\n"
        f"skill: {skill.get('name', '')}\n"
        f"command: {command}\n"
        f"engine: {engine_label}\n"
        f"generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"---\n\n"
    )
    path.write_text(header + body.strip() + "\n", encoding="utf-8")
    return path


class Job:
    """One skill run."""

    def __init__(self, command, skill):
        self.id = uuid.uuid4().hex[:12]
        self.command = command
        self.skill = skill.get("file")
        self.status = "running"
        self.reply = None
        self.error = None
        self.output = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at = None

    def as_dict(self):
        return {
            "job_id": self.id,
            "command": self.command,
            "skill": self.skill,
            "status": self.status,
            "reply": self.reply,
            "error": self.error,
            "output": self.output,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Runner:
    """Starts skill runs and keeps their results readable."""

    def __init__(self, vault_dir, skills_dir, adapter):
        self.vault_dir = vault_dir
        self.skills_dir = Path(skills_dir)
        self.adapter = adapter
        self._jobs = {}
        self._order = []
        self._lock = threading.Lock()

    # --- job book-keeping ---------------------------------------------

    def _remember(self, job):
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        return job.as_dict() if job else None

    def recent(self, limit=10):
        with self._lock:
            ids = self._order[-limit:][::-1]
            return [self._jobs[i].as_dict() for i in ids if i in self._jobs]

    # --- running ------------------------------------------------------

    def _core_body(self):
        core = self.skills_dir / "assistant_core.md"
        try:
            return strip_frontmatter(core.read_text(encoding="utf-8"))
        except OSError:
            return ""

    def _skill_body(self, skill):
        try:
            return strip_frontmatter(
                (self.skills_dir / skill["file"]).read_text(encoding="utf-8")
            )
        except OSError:
            return ""

    def _execute(self, job, skill, command, context):
        try:
            prompt = build_prompt(
                self._core_body(), self._skill_body(skill), command, context
            )
            reply = self.adapter.run(prompt)
        except EngineError as exc:
            job.status, job.error = "failed", str(exc)
            job.finished_at = datetime.now(timezone.utc).isoformat()
            return
        except Exception as exc:  # noqa: BLE001 - a run must never kill the server
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            return

        job.reply = reply
        target = output_path(skill, self.vault_dir)
        if target is not None:
            try:
                write_output(
                    target, skill, command, self.adapter.describe(), reply
                )
                job.output = "/" + str(
                    target.relative_to(Path(self.vault_dir).resolve())
                ).replace("\\", "/")
            except OSError as exc:
                # The run succeeded even if the note did not land; say so
                # rather than reporting a write that did not happen.
                job.error = f"ran, but could not write to the vault: {exc}"
        job.status = "done"
        job.finished_at = datetime.now(timezone.utc).isoformat()

    def start(self, skill, command, context=None):
        """Begin a run and return the job immediately."""
        job = Job(command, skill)
        self._remember(job)
        thread = threading.Thread(
            target=self._execute,
            args=(job, skill, command, context),
            name=f"skill-{job.id}",
            daemon=True,
        )
        thread.start()
        return job

    def run_sync(self, skill, command, context=None):
        """Run inline and return the finished job. Used by tests."""
        job = Job(command, skill)
        self._remember(job)
        self._execute(job, skill, command, context)
        return job
