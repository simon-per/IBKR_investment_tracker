"""
The scheduler job store has to be a file the container can actually open.

It was not, from 2026-07-30 to 08-01. `docker-compose.yml` bind-mounted
`./scheduler_jobs.db:/app/scheduler_jobs.db`, nothing ever created that file on the
host, and Docker creates a missing bind-mount source **as a directory** — so both
sides became an empty directory and sqlite answered `unable to open database file`
on every boot.

What made it survive two days is the shape of the failure, not the failure itself:
the fallback to an in-memory store re-registers all five jobs, so
`/api/scheduler/status` listed a fully-armed scheduler exactly as it would with a
working store. The feature whose entire purpose is surviving a restart was inert,
and the only symptom was a log line nobody had reason to read.

So the tests below are in two halves:

- the *path* half, that a job store addressed inside a directory works;
- the *structural* half, that the compose mount and the configured URL still agree.

The second is the one that would have caught the original bug, and it is the one to
keep if these ever have to be trimmed: no runtime assertion can see a compose file.

Offline: filesystem and YAML only, no network and no container.
"""

from pathlib import Path, PurePosixPath

import pytest
import yaml

from app.config import Settings
from app.services.scheduler_service import _sqlite_path, ensure_jobstore_parent

BACKEND_DIR = Path(__file__).resolve().parent.parent
COMPOSE_FILE = BACKEND_DIR / "docker-compose.yml"


def shipped_jobstore_url() -> str:
    """
    The declared default, not `settings.scheduler_jobstore_url`.

    `conftest.py` blanks that on the live instance for the whole suite so one
    module's scheduler cannot write a `scheduler_jobs.db` into the repo — which
    would make these assertions read an empty string and pass vacuously. The
    default is what actually ships in the container.
    """
    return Settings.model_fields["scheduler_jobstore_url"].default


class TestSqlitePath:
    def test_reads_a_relative_path(self):
        assert _sqlite_path("sqlite:///./scheduler-data/jobs.db") == Path("./scheduler-data/jobs.db")

    def test_memory_has_no_path(self):
        # conftest runs the whole suite on this; creating a ":memory:" directory
        # would litter the repo.
        assert _sqlite_path("sqlite:///:memory:") is None

    @pytest.mark.parametrize("url", ["", "postgresql://localhost/x", "mysql://x"])
    def test_a_non_sqlite_url_has_no_path(self, url):
        assert _sqlite_path(url) is None


class TestEnsureJobstoreParent:
    def test_creates_a_missing_parent_directory(self, tmp_path):
        target = tmp_path / "scheduler-data" / "scheduler_jobs.db"
        assert not target.parent.exists()

        ensure_jobstore_parent(f"sqlite:///{target}")

        assert target.parent.is_dir()

    def test_is_idempotent(self, tmp_path):
        target = tmp_path / "scheduler-data" / "scheduler_jobs.db"
        ensure_jobstore_parent(f"sqlite:///{target}")
        ensure_jobstore_parent(f"sqlite:///{target}")
        assert target.parent.is_dir()

    def test_leaves_an_existing_directory_alone(self, tmp_path):
        target = tmp_path / "scheduler-data" / "scheduler_jobs.db"
        target.parent.mkdir()
        (target.parent / "keep.txt").write_text("x")

        ensure_jobstore_parent(f"sqlite:///{target}")

        assert (target.parent / "keep.txt").read_text() == "x"

    @pytest.mark.parametrize("url", ["sqlite:///:memory:", "", "postgresql://localhost/x"])
    def test_a_url_with_no_path_is_a_no_op(self, url):
        ensure_jobstore_parent(url)  # must not raise

    def test_an_unwritable_target_does_not_raise(self, tmp_path, monkeypatch):
        """
        The caller's fallback to an in-memory store is strictly better than refusing
        to boot: losing misfire recovery costs one late sync, and an exception out of
        the lifespan handler costs the whole site.
        """
        def boom(*args, **kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(Path, "mkdir", boom)
        ensure_jobstore_parent(f"sqlite:///{tmp_path}/nope/jobs.db")


class TestSqliteCanActuallyOpenIt:
    def test_a_store_inside_a_created_directory_opens(self, tmp_path):
        """
        The end the bug was at: sqlite makes the file but never its parent, so this
        is the difference between a usable store and `unable to open database file`.
        """
        import sqlite3

        target = tmp_path / "scheduler-data" / "scheduler_jobs.db"
        ensure_jobstore_parent(f"sqlite:///{target}")

        conn = sqlite3.connect(target)
        conn.execute("create table t (a int)")
        conn.close()

        assert target.is_file()

    def test_a_directory_at_the_db_path_is_what_failed(self, tmp_path):
        """
        Pins the actual production symptom, so the reason for the directory mount
        stays legible: this is what Docker had created on both sides.
        """
        import sqlite3

        target = tmp_path / "scheduler_jobs.db"
        target.mkdir()

        with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
            sqlite3.connect(target).execute("create table t (a int)")


class TestComposeMountMatchesTheConfiguredUrl:
    """
    The structural half. A runtime test cannot see docker-compose.yml, which is where
    the bug lived — the code was correct and the mount was the wrong shape.
    """

    @staticmethod
    def _backend_mounts():
        compose = yaml.safe_load(COMPOSE_FILE.read_text())
        service = compose["services"]["portfolio-backend"]
        return [v.split(":")[1] for v in service["volumes"]]

    def test_the_jobstore_lives_under_a_mounted_directory(self):
        """
        The job store must sit *inside* a mounted path, not *be* one. Docker creates a
        missing mount source as a directory, so a mount naming the .db file itself can
        only ever produce the failure this test exists to prevent.
        """
        path = _sqlite_path(shipped_jobstore_url())
        assert path is not None, "the default job store URL must be a sqlite path"

        # PurePosixPath, not Path: the container is Linux and the suite also runs on
        # Windows, where `Path("/app") / ...` yields backslashes that match no mount.
        container_path = PurePosixPath("/app") / PurePosixPath(path.as_posix())
        mounts = self._backend_mounts()

        assert str(container_path) not in mounts, (
            f"docker-compose mounts {container_path} directly. Docker creates a missing "
            f"source as a DIRECTORY, so sqlite will fail with 'unable to open database "
            f"file' — mount the parent directory instead."
        )

        parents = {str(p) for p in container_path.parents}
        assert parents & set(mounts), (
            f"{container_path} is not inside any mounted path {mounts}, so the job "
            f"store would not survive the rebuild it exists to survive."
        )

    def test_the_jobstore_is_not_in_the_portfolio_database(self):
        """The store is synchronous SQLAlchemy while the app is aiosqlite in WAL mode;
        one file invites lock contention on the database holding the actual portfolio."""
        path = _sqlite_path(shipped_jobstore_url())
        assert path.name != "portfolio.db"
