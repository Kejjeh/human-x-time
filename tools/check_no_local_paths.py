#!/usr/bin/env python
"""Refuse to commit an absolute path out of somebody's home directory.

This exists because one nearly shipped. A UX review was written by agents that
had been handed absolute paths in their brief, and one survived into the prose:
a citation reading `C:\\Users\\<name>\\Documents\\...\\src\\00_head.html:336`,
staged for two public repositories. It was caught by hand, which is not a
control. This is the control.

What it costs to get wrong is small but permanent: a public repo that names your
account and your directory layout, in history, after the file is fixed.

Run it on what is staged (the pre-commit hook does this):

    python tools/check_no_local_paths.py --staged

or over every tracked file, which is what you want from CI or a build gate -
tools/build.py runs this before it writes anything:

    python tools/check_no_local_paths.py --all

and the patterns have a test of their own, because a gate nobody tests is a
gate nobody knows the shape of:

    python tools/check_no_local_paths.py --self-test

Exits non-zero on any hit and prints file:line. It is a gate, not a formatter -
it never edits anything.
"""

import re
import subprocess
import sys

# The patterns are assembled from fragments on purpose. Written out whole, this
# file would match itself on every run, and the usual fix - excluding the
# checker from its own scan - carves out the one file where a leak could then
# hide forever. Fragments keep the scan total.
_U = 'Users'
_H = 'home'
_SEP = '[\\\\/]'

# Case-insensitive, deliberately.
#
# Windows and macOS filesystems are themselves case-insensitive, so the same
# home directory comes out of different shells and tools with the drive letter
# and the directory segment in whatever case that tool happened to use. Only the
# canonical spelling was being caught: of eleven ways a real path can be
# written, three walked straight through - a lowercased Windows one, an
# uppercased one, and a lowercased macOS one.
#
# The cost is a theoretical false positive on prose about a REST route whose
# first segment is the same word as the macOS home directory. The cost of a miss
# is an account name in a public history, permanently. A gate should fail the
# safe way.
#
# Note the care taken not to write any of those examples out in full here. This
# file is scanned like every other, on purpose - see the note above - so a
# worked example with a plausible account name in it would make the checker
# refuse its own source. Which it duly did, when this comment was first drafted.
_RX = re.IGNORECASE

PATTERNS = [
    # C:\Users\name  /  C:/Users/name  - any drive letter, any slash style
    ('windows home', re.compile(r'[A-Za-z]:' + _SEP + r'+' + _U + _SEP + r'+([A-Za-z0-9_.\-]+)', _RX)),
    # /Users/name - macOS
    ('macos home',   re.compile(r'(?<![A-Za-z0-9_.\-])/' + _U + r'/([A-Za-z0-9_.\-]+)', _RX)),
    # /home/name - linux
    ('linux home',   re.compile(r'(?<![A-Za-z0-9_.\-])/' + _H + r'/([A-Za-z0-9_.\-]+)', _RX)),
    # /mnt/c/Users/name (WSL) and /c/Users/name (git-bash, msys). The lookbehind
    # above is there to stop `something/Users/x` inside a longer identifier, and
    # it blocked these too: the character before `/Users` is the drive letter.
    # A Windows home reached through a POSIX mount is still a Windows home, and
    # WSL is where a good deal of this kind of path gets pasted from.
    ('mounted windows home',
     re.compile(r'(?<![A-Za-z0-9_.\-])(?:/mnt)?/[A-Za-z]/' + _U + r'/([A-Za-z0-9_.\-]+)', _RX)),
]

# Obvious stand-ins in documentation. A real account name is the thing we are
# stopping; `/home/you/project` in a README is fine and should stay writable.
PLACEHOLDERS = {
    'you', 'user', 'username', 'name', 'me', 'someone', 'yourname',
    'your-name', 'your_name', '<user>', '<username>', '<you>', '<name>',
    'USER', 'USERNAME', 'HOME', 'root', 'runner', 'ubuntu',
}
# Matching is case-insensitive now, so `/home/You/...` has to read as the same
# placeholder as `/home/you/...` rather than as a real account called You.
PLACEHOLDERS_LC = {p.lower() for p in PLACEHOLDERS}

SKIP_SUFFIXES = (
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.zip', '.gz', '.bz2', '.xz', '.7z',
    '.mp4', '.webm', '.mp3', '.wav',
)

MAX_BYTES = 8 * 1024 * 1024


def _git(args):
    """Run git, and refuse to treat a failure as an empty file.

    staged_blob used to swallow the return code, so a path git could not show
    scanned as b'' and passed clean - a gate reporting success on a file it
    never read.
    """
    r = subprocess.run(['git'] + args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(
            'git %s failed (%d): %s' % (' '.join(args[:2]), r.returncode,
                                        r.stderr.decode('utf-8', 'replace').strip()[:200]))
    return r.stdout


def staged_paths():
    out = _git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'])
    return [p.decode('utf-8') for p in out.split(b'\x00') if p]


def tracked_paths():
    out = _git(['ls-files', '-z'])
    return [p.decode('utf-8') for p in out.split(b'\x00') if p]


def staged_blob(path):
    return _git(['show', ':' + path])


def worktree_blob(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return b''


def scan(path, raw, skipped=None):
    """Yield (lineno, kind, offending_text) for each hit in one file.

    A file too large to scan is recorded in `skipped` rather than passed over in
    silence. The largest tracked file today is src/events.json at 4.9 MB, and
    the corpus is the one thing here designed to grow - the roadmap in the
    README talks about 50-100k events, which takes it past this limit. A gate
    that quietly stops covering the biggest file in the repo is worse than no
    gate, because it still reports success.
    """
    if len(raw) > MAX_BYTES:
        if skipped is not None:
            skipped.append((path, len(raw)))
        return
    if b'\x00' in raw[:8192]:
        return                     # binary; nothing readable to leak
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return  # not text; nothing readable to leak

    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, rx in PATTERNS:
            for m in rx.finditer(line):
                if m.group(1).lower() in PLACEHOLDERS_LC:
                    continue
                yield lineno, kind, m.group(0)


# What the patterns are supposed to do, written down. Every one of the "flagged"
# rows below was checked by hand; three of them - a lowercased Windows path, an
# uppercased one, and a lowercased macOS one - used to walk straight through,
# and the two mounted-drive rows did too. The "clean" rows are the false
# positives that would make this gate untrustworthy: placeholders in prose, the
# CI account names, an ordinary repo-relative citation, and a URL whose first
# path segment happens to collide with the macOS home directory.
def _cases():
    U, H = _U, _H
    return [
        ('windows, canonical', 'C:\\%s\\jbloggs\\x.html:12' % U, True),
        ('windows, lowercased', 'c:\\%s\\jbloggs\\x.html:12' % U.lower(), True),
        ('windows, uppercased', 'C:\\%s\\JBLOGGS\\x.html' % U.upper(), True),
        ('windows, forward slashes', 'C:/%s/jbloggs/x.html' % U, True),
        ('macos', '/%s/jbloggs/src/x.html:12' % U, True),
        ('macos, lowercased', '/%s/jbloggs/src/x.html:12' % U.lower(), True),
        ('linux', '/%s/jbloggs/src/x.html:12' % H, True),
        ('wsl mount', '/mnt/c/%s/jbloggs/x.html' % U, True),
        ('git-bash mount', '/c/%s/jbloggs/x.html' % U, True),
        ('file URL', 'file:///%s/jbloggs/x.html' % U, True),
        ('placeholder, lowercase', '/%s/you/src/x.html' % H, False),
        ('placeholder, capitalised', '/%s/You/src/x.html' % H, False),
        ('angle-bracket placeholder', 'C:\\%s\\<name>\\x.html' % U, False),
        ('CI account', '/%s/runner/work/repo' % H, False),
        ('repo-relative citation', 'src/00_head.html:336', False),
        ('URL path segment', 'https://example.com/%s/123' % U.lower(), False),
    ]


def self_test():
    bad = 0
    for name, text, want in _cases():
        got = bool(list(scan('t.md', text.encode())))
        if got != want:
            bad += 1
            print('  FAIL %-28s %s, wanted %s'
                  % (name, 'flagged' if got else 'clean', 'flagged' if want else 'clean'))
    total = len(_cases())
    print('  %d/%d pattern cases as expected' % (total - bad, total))
    return 1 if bad else 0


def main(argv):
    mode = argv[1] if len(argv) > 1 else '--staged'
    if mode == '--self-test':
        return self_test()
    if mode not in ('--staged', '--all'):
        print(__doc__)
        return 2

    if mode == '--staged':
        paths, read = staged_paths(), staged_blob
    else:
        paths, read = tracked_paths(), worktree_blob

    hits, skipped = [], []
    for path in paths:
        if path.lower().endswith(SKIP_SUFFIXES):
            continue
        for lineno, kind, text in scan(path, read(path), skipped):
            hits.append((path, lineno, kind, text))

    for path, size in skipped:
        print('  NOT SCANNED: %s is %.1f MB, over the %.0f MB limit.'
              % (path, size / 1e6, MAX_BYTES / 1e6))
    if skipped:
        print('  Raise MAX_BYTES or split the file; this gate is not covering it.')

    if not hits:
        return 0

    print('')
    print('  Refusing: %d absolute home-directory path%s in %s content.'
          % (len(hits), '' if len(hits) == 1 else 's',
             'staged' if mode == '--staged' else 'tracked'))
    print('  These repos are public. A path like this publishes an account')
    print('  name and a directory layout, and history keeps it.')
    print('')
    for path, lineno, kind, text in hits:
        print('    %s:%d  (%s)' % (path, lineno, kind))
        print('        %s' % text)
    print('')
    print('  Rewrite them repo-relative, e.g. src/00_head.html:336 - which is')
    print('  what every other citation in these repos already does.')
    print('')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
