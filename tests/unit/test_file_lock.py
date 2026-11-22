"""Unit tests for scripts/file_lock.py — one writer at a time across processes."""

from __future__ import annotations

import os
import threading
import time

import pytest

from scripts.file_lock import LockTimeout, locked

pytestmark = pytest.mark.unit


def test_the_lock_file_exists_only_while_held(tmp_path):
    lock = tmp_path / "edit.lock"

    with locked(str(lock)):
        assert lock.exists()

    assert not lock.exists()


def test_the_lock_is_released_when_the_body_raises(tmp_path):
    lock = tmp_path / "edit.lock"

    with pytest.raises(RuntimeError), locked(str(lock)):
        raise RuntimeError("boom")

    assert not lock.exists()


def test_a_held_lock_makes_the_next_writer_time_out(tmp_path):
    lock = str(tmp_path / "edit.lock")

    with locked(lock), pytest.raises(LockTimeout), locked(lock, timeout=0.2):
        pass


def test_a_stale_lock_left_by_a_crashed_writer_is_taken_over(tmp_path):
    lock = tmp_path / "edit.lock"
    lock.write_text("crashed")
    old = time.time() - 600
    os.utime(lock, (old, old))

    with locked(str(lock), timeout=0.2, stale=60):
        assert lock.read_text() != "crashed"


def test_the_lock_creates_its_folder(tmp_path):
    lock = tmp_path / "not-yet" / "edit.lock"

    with locked(str(lock)):
        assert lock.exists()


def test_concurrent_read_modify_writes_lose_nothing(tmp_path):
    counter = tmp_path / "counter.txt"
    counter.write_text("0")
    lock = str(tmp_path / "edit.lock")

    def bump():
        for _ in range(25):
            with locked(lock):
                value = int(counter.read_text())
                time.sleep(0.001)
                counter.write_text(str(value + 1))

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counter.read_text() == "100"
