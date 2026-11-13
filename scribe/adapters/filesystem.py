"""FileStore on a local folder (a bind mount in Docker).

    inbox/     drop audio here
    .work/     <job id>/<file>: staged while queued or processing
    output/    transcripts
    archive/   originals that were transcribed
    failed/    originals that could not be transcribed, each with a .error.txt

Everything sits under one folder so that taking a file out of the inbox is a
single atomic rename. Stored paths are relative to that folder.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from scribe.application.ports import InboxFile, OutOfSequence
from scribe.domain.job import Job

ERROR_NOTE_SUFFIX = ".error.txt"


class LocalFileStore:
    def __init__(self, data_dir: Path, archive_originals: bool = True) -> None:
        self._root = Path(data_dir)
        self._archive_originals = archive_originals
        self.inbox = self._root / "inbox"
        self.work = self._root / ".work"
        self.output = self._root / "output"
        self.archive = self._root / "archive"
        self.failed = self._root / "failed"
        for folder in (self.inbox, self.work, self.output, self.archive, self.failed):
            self._mkdir(folder)

    # ------------------------------------------------------------- intake

    def inbox_files(self) -> list[InboxFile]:
        found = []
        for folder, _, names in os.walk(self.inbox):
            for name in names:
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except OSError:  # vanished while we were looking
                    continue
                found.append(InboxFile(path.relative_to(self.inbox).as_posix(), stat.st_size, stat.st_mtime))
        return sorted(found, key=lambda f: f.path)

    def stage_from_inbox(self, inbox_path: str, job_id: str) -> str:
        target = self.work / job_id / _safe_name(inbox_path)
        self._move(self.inbox / inbox_path, target)
        return self._relative(target)

    def return_to_inbox(self, stored_path: str, inbox_path: str) -> None:
        source = self.local_path(stored_path)
        self._move(source, _unique(self.inbox / inbox_path))
        if source.parent.parent == self.work:
            shutil.rmtree(source.parent, ignore_errors=True)

    def stage_upload(self, job_id: str, filename: str, content: BinaryIO) -> tuple[str, int]:
        target = self.work / job_id / _safe_name(filename)
        self._mkdir(target.parent)
        with open(target, "wb") as out:
            shutil.copyfileobj(content, out)
        self._own(target)
        return self._relative(target), target.stat().st_size

    def append_audio(self, stored_path: str, offset: int, content: BinaryIO) -> int:
        path = self.local_path(stored_path)
        size = path.stat().st_size if path.is_file() else 0
        if offset > size or not path.is_file():
            raise OutOfSequence(expected=size)
        # Writing at the stated offset, rather than at the end, is what makes
        # a piece that is sent twice harmless.
        with open(path, "r+b") as out:
            out.seek(offset)
            shutil.copyfileobj(content, out)
            return max(size, out.tell())

    def recover_orphans(self, known_job_ids: set[str]) -> list[str]:
        recovered = []
        for folder in self.work.iterdir():
            if not folder.is_dir() or folder.name in known_job_ids:
                continue
            for file in folder.iterdir():
                if file.is_file():
                    target = _unique(self.inbox / file.name)
                    self._move(file, target)
                    recovered.append(target.name)
            shutil.rmtree(folder, ignore_errors=True)
        return recovered

    # ------------------------------------------------------------- lookup

    def local_path(self, stored_path: str) -> Path:
        return self._root / stored_path

    def exists(self, stored_path: str) -> bool:
        return self.local_path(stored_path).is_file()

    # ------------------------------------------------------------ outputs

    def write_outputs(self, job: Job, documents: dict[str, str]) -> list[str]:
        folder = self.output / _safe_rel_dir(job.rel_dir)
        stem = Path(job.filename).stem or "audio"
        targets = {fmt: folder / f"{stem}.{fmt}" for fmt in documents}
        # Never overwrite another job's transcript; re-running a job may
        # overwrite its own.
        if any(t.exists() and self._relative(t) not in job.outputs for t in targets.values()):
            targets = {fmt: folder / f"{stem}-{job.id[:8]}.{fmt}" for fmt in documents}
        for fmt, target in targets.items():
            self._write_text(target, documents[fmt])
        return [self._relative(t) for t in targets.values()]

    def rewrite_outputs(self, job: Job, render: Callable[[str], str]) -> None:
        for stored in job.outputs:
            path = self.local_path(stored)
            if path.is_file():
                self._write_text(path, render(path.suffix.lstrip(".")))

    # ----------------------------------------------------------- originals

    def archive_original(self, job: Job) -> str:
        source = self.local_path(job.stored_path)
        if not source.is_file() or self.archive in source.parents:
            return job.stored_path
        self._error_note(source).unlink(missing_ok=True)  # a re-run of a failed file
        if self._archive_originals:
            target = _unique(self.archive / _safe_rel_dir(job.rel_dir) / _safe_name(job.filename))
            self._move(source, target)
        else:
            source.unlink()
            target = source
        self.discard(job)
        return self._relative(target)

    def fail_original(self, job: Job, error: str) -> str:
        source = self.local_path(job.stored_path)
        if not source.is_file():
            return job.stored_path
        target = source
        if self.work in source.parents:
            target = _unique(self.failed / _safe_rel_dir(job.rel_dir) / _safe_name(job.filename))
            self._move(source, target)
            self.discard(job)
        if self.failed in target.parents:
            self._write_text(self._error_note(target), f"{job.filename}\n\n{error}\n")
        return self._relative(target)

    def discard(self, job: Job) -> None:
        shutil.rmtree(self.work / job.id, ignore_errors=True)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _error_note(path: Path) -> Path:
        return path.with_name(path.name + ERROR_NOTE_SUFFIX)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _move(self, source: Path, target: Path) -> None:
        self._mkdir(target.parent)
        try:
            os.replace(source, target)
        except OSError:  # across filesystems
            shutil.move(str(source), str(target))
        self._own(target)

    def _write_text(self, path: Path, text: str) -> None:
        self._mkdir(path.parent)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
        self._own(path)

    def _mkdir(self, path: Path) -> None:
        created = []
        probe = path
        while not probe.exists():
            created.append(probe)
            probe = probe.parent
        path.mkdir(parents=True, exist_ok=True)
        for folder in created:
            self._own(folder)

    def _own(self, path: Path) -> None:
        """When running as root (the default in a container), hand new files to
        whoever owns the data folder, so they are not root-owned on the host."""
        try:
            if os.geteuid() != 0:
                return
            owner = self._root.stat()
            if (owner.st_uid, owner.st_gid) != (0, 0):
                os.chown(path, owner.st_uid, owner.st_gid)
        except OSError:
            pass


def _safe_name(name: str) -> str:
    name = PurePosixPath(name.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f]", "", name)
    return name if name not in ("", ".", "..") else "audio"


def _safe_rel_dir(rel_dir: str) -> Path:
    parts = [p for p in PurePosixPath(rel_dir.replace("\\", "/")).parts if p not in ("", ".", "..", "/")]
    return Path(*parts) if parts else Path()


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate
