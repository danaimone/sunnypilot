import json
from types import SimpleNamespace
import tarfile

import pytest
from openpilot.sunnypilot.diagnostics import route_archive as archive


@pytest.fixture
def drive(tmp_path, monkeypatch):
  monkeypatch.setattr(archive.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=30 * 1024**3))
  root = tmp_path / 'realdata'
  for n in (0, 1):
    segment = root / f'00000381--33b85e7320--{n}'
    segment.mkdir(parents=True)
    (segment / 'qlog.zst').write_bytes(b'query-log')
    (segment / 'rlog.zst').write_bytes(b'raw-log')
    (segment / 'fcamera.hevc').write_bytes(b'video')
  return root, tmp_path / 'saved'


def test_export_copies_logs_and_manifest_not_video(drive):
  root, saved = drive
  result = archive.export_route(root, saved)
  with tarfile.open(result) as tar:
    names = tar.getnames()
    assert len(names) == 5
    assert not any('camera' in name for name in names)
    manifest = json.load(tar.extractfile('manifest.json'))
    assert manifest['route'] == '00000381--33b85e7320'
    assert len(manifest['files']) == 4
    assert tar.extractfile(names[0]).read() == b'query-log'
  assert len(list(root.glob('*/rlog.zst'))) == 2
  assert not list(saved.glob('*.partial'))
  with pytest.raises(FileExistsError):
    archive.export_route(root, saved)


def test_refuses_active_drive(drive):
  root, saved = drive
  next(root.iterdir()).joinpath('rlog.lock').touch()
  with pytest.raises(ValueError, match='still being recorded'):
    archive.export_route(root, saved)
  assert not saved.exists()


def test_rejects_inside_rotating_directory_and_bad_route(drive):
  root, saved = drive
  with pytest.raises(ValueError, match='outside'):
    archive.export_route(root, root / 'archives')
  with pytest.raises(ValueError, match='not found'):
    archive.export_route(root, saved, '../other')


def test_space_reserve(drive, monkeypatch):
  root, saved = drive
  monkeypatch.setattr(archive.shutil, 'disk_usage', lambda _: SimpleNamespace(total=100 * 1024**3, free=1024))
  with pytest.raises(ValueError, match='free space'):
    archive.export_route(root, saved)
  assert not list(saved.iterdir())


def test_failure_never_leaves_completed_archive(drive, monkeypatch):
  root, saved = drive
  def fail(*args, **kwargs):
    raise OSError('disk write failed')
  monkeypatch.setattr(tarfile.TarFile, 'addfile', fail)
  with pytest.raises(OSError, match='disk write failed'):
    archive.export_route(root, saved)
  assert not list(saved.iterdir())


def test_rejects_symlinked_logs(drive, tmp_path):
  root, saved = drive
  log = next(root.glob('*/qlog.zst'))
  log.unlink()
  target = tmp_path / 'unrelated'
  target.write_text('not a route log')
  log.symlink_to(target)
  with pytest.raises(ValueError, match='linked'):
    archive.export_route(root, saved)


def test_log_changed_during_copy_is_not_published(drive, monkeypatch):
  root, saved = drive
  original = tarfile.TarFile.addfile
  def change_after_copy(self, info, source=None):
    original(self, info, source)
    if source is not None:
      with (root / info.name).open('ab') as log:
        log.write(b'new recording bytes')
  monkeypatch.setattr(tarfile.TarFile, 'addfile', change_after_copy)
  with pytest.raises(ValueError, match='changed during export'):
    archive.export_route(root, saved)
  assert not list(saved.iterdir())
