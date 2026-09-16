"""Copy completed route logs outside the rotating recorder directory.

Archives contain diagnostic logs, not camera video. Source files are never
changed. Unlike a preservation-priority marker, these copies are not managed
by loggerd's route deleter. They must be removed manually after retrieval.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

LOG_FILES = frozenset(('rlog', 'qlog', 'rlog.zst', 'qlog.zst', 'rlog.bz2', 'qlog.bz2'))
ROUTE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{1,100}\Z')
MIN_FREE = 5 * 1024**3


def routes(log_root):
  found = {}
  for path in Path(log_root).iterdir():
    route, sep, segment = path.name.rpartition('--')
    if sep and ROUTE_NAME.fullmatch(route) and segment.isdigit() and path.is_dir() and not path.is_symlink():
      found.setdefault(route, []).append(path)
  return {route: sorted(paths, key=lambda p: int(p.name.rpartition('--')[2])) for route, paths in found.items()}


def export_route(log_root, output_dir, route=None):
  root = Path(log_root).resolve()
  destination = Path(output_dir).resolve()
  if destination == root or root in destination.parents:
    raise ValueError('Choose an archive folder outside the rotating route directory.')
  available = routes(root)
  if route is None:
    if not available:
      raise ValueError('No recorded drives are available.')
    route = max(available, key=lambda name: max(p.stat().st_mtime_ns for p in available[name]))
  if not ROUTE_NAME.fullmatch(route) or route not in available:
    raise ValueError('Recorded drive not found.')
  segments = available[route]
  files = []
  for segment in segments:
    if any(segment.glob('*.lock')):
      raise ValueError('This drive is still being recorded. Try again after recording stops.')
    for name in sorted(LOG_FILES):
      path = segment / name
      if path.is_symlink():
        raise ValueError('Refusing to archive a linked log file.')
      if path.is_file():
        files.append(path)
  if not files:
    raise ValueError('No diagnostic logs remain for this drive.')
  destination.mkdir(parents=True, exist_ok=True)
  archive = destination / f'{route}-logs.tar'
  if archive.exists() or archive.is_symlink():
    raise FileExistsError('Logs for this drive have already been saved.')
  size = sum(p.stat().st_size for p in files)
  usage = shutil.disk_usage(destination)
  # Leave the same minimum free space as the recorder's cleanup policy, plus
  # archive headers and a margin for normal background writes.
  if usage.free < size + max(MIN_FREE, usage.total // 10) + 64 * 1024**2:
    raise ValueError('Not enough free space to save this drive. Retrieve older saved logs first.')
  fd, temporary = tempfile.mkstemp(prefix='.route-', suffix='.partial', dir=destination)
  try:
    with os.fdopen(fd, 'wb') as output, tarfile.open(fileobj=output, mode='w') as tar:
      entries = []
      for path in files:
        # No symlink following even if a file changes after directory scanning.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source:
          before = os.fstat(source.fileno())
          name = f'{path.parent.name}/{path.name}'
          info = tarfile.TarInfo(name)
          info.size, info.mtime, info.mode = before.st_size, int(before.st_mtime), 0o600
          tar.addfile(info, source)
          after = os.fstat(source.fileno())
          current = path.stat(follow_symlinks=False)
          if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns) or \
             (before.st_ino, before.st_size, before.st_mtime_ns) != (current.st_ino, current.st_size, current.st_mtime_ns):
            raise ValueError('A log changed during export. Wait for recording to stop and try again.')
          entries.append({'path': name, 'bytes': before.st_size})
      if any(any(segment.glob('*.lock')) for segment in segments):
        raise ValueError('Recording restarted during export. Try again after it stops.')
      manifest = json.dumps({'route': route, 'files': entries, 'videos_included': False}, indent=2).encode()
      info = tarfile.TarInfo('manifest.json')
      info.size, info.mode = len(manifest), 0o600
      tar.addfile(info, io.BytesIO(manifest))
    with open(temporary, 'rb') as output:
      os.fsync(output.fileno())
    # Link fails if another export won the race; never replace an existing copy.
    os.link(temporary, archive)
    directory_fd = os.open(destination, os.O_RDONLY)
    try:
      os.fsync(directory_fd)
    finally:
      os.close(directory_fd)
    return archive
  finally:
    Path(temporary).unlink(missing_ok=True)


def main():
  from openpilot.common.hardware.hw import Paths
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--log-root', default=Paths.log_root())
  parser.add_argument('--output-dir', default='/data/diagnostics/routes')
  parser.add_argument('--route', help='Route ID; defaults to the most recently recorded drive')
  parser.add_argument('--list', action='store_true', help='List route IDs without exporting')
  args = parser.parse_args()
  try:
    if args.list:
      print('\n'.join(sorted(routes(args.log_root))))
    else:
      print(export_route(args.log_root, args.output_dir, args.route))
  except (OSError, ValueError) as error:
    parser.exit(1, f'{error}\n')


if __name__ == '__main__':
  main()
