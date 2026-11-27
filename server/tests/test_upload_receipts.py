from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from inky_web.db import connection, photos_dir
from inky_web.services import photos, queue


def upload(client, content, key):
    return client.post("/api/queue", headers={"Idempotency-Key": key},
                       files={"file": ("synthetic.png", content, "image/png")})


def test_accepted_upload_receipt_survives_queue_consumption(client, png_factory):
    data, key = png_factory(), str(uuid4())
    accepted = upload(client, data, key)
    assert accepted.status_code == 201
    assert queue.pop_next() is not None
    replay = upload(client, data, key)
    assert replay.status_code == 201
    assert replay.json() == accepted.json()
    assert queue.count() == 0
    assert upload(client, png_factory(color=(0, 24, 255)), key).status_code == 409
    assert len(list(photos_dir().glob("*.png"))) == 1


def test_concurrent_upload_replay_has_one_photo_and_one_entry(client, png_factory):
    data, key = png_factory(), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(upload, client, data, key)
        b = pool.submit(upload, client, data, key)
        first, second = a.result(), b.result()
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert queue.count() == 1
    assert len(list(photos_dir().iterdir())) == 1


@pytest.mark.parametrize("after_queue", [False, True])
def test_failed_upload_transaction_discards_file_photo_row_and_entry(client, png_factory, monkeypatch, after_queue):
    add = queue.add_in_transaction

    def abort(photo_id, conn):
        if after_queue:
            add(photo_id, conn)
        raise OSError("synthetic local write failure")

    with monkeypatch.context() as patch:
        patch.setattr(queue, "add_in_transaction", abort)
        with pytest.raises(OSError, match="synthetic local write failure"):
            upload(client, png_factory(), str(uuid4()))
    assert not list(photos_dir().iterdir())
    with connection() as conn:
        for table in ("photos", "queue", "upload_receipts"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_startup_reconciles_uncommitted_upload_files(png_factory):
    committed, _ = photos.save(content=png_factory(), original_filename="kept.png")
    png = photos_dir() / "012345abcdef.png"
    temp = photos_dir() / ".inky-upload-interrupted"
    png.write_bytes(b"synthetic uncommitted final file")
    temp.write_bytes(b"synthetic interrupted temporary file")
    photos.recover_upload_files()
    assert not png.exists()
    assert not temp.exists()
    assert photos.path_for(committed.id).exists()
