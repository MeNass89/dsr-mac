"""Build the included mod pack on the user's Mac: extract each included mod (PC files, as released on Nexus), convert it onto the user's own
Switch files and stack the results, so mods that change the same archive (menu textures, menu text) all keep their part.
usage: python3 -I build_pack.py <pack.tsv> <folder of the included mod archives> <RomFS> <out folder>
Output: <out>/_stack/ = every included mod merged (archive-path layout, used by the launcher like one converted mod), <out>/pack.tsv (what each did)."""
import sys, os, subprocess, shutil, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import port_mod

def read_pack(path):
    rows = []
    for l in open(path, encoding='utf-8'):
        if l.startswith('#') or not l.strip(): continue
        f = l.rstrip('\n').split('\t')
        rows.append(dict(id=f[0], name=f[1], author=f[2], status=f[3], nexus=f[4], file=f[5], folder=f[6], what=f[7]))
    return rows

def extract(archive, dest):
    """.zip, .7z and .rar all open with macOS's bsdtar (libarchive)"""
    os.makedirs(dest, exist_ok=True)
    r = subprocess.run(['/usr/bin/bsdtar', '-xf', archive, '-C', dest], capture_output=True)
    if r.returncode: raise ValueError(f'could not extract {os.path.basename(archive)}: {r.stderr.decode()[-200:]}')

def main(pack, arcs, R, out):
    rows = [r for r in read_pack(pack) if r['status'] == 'included']
    stack = os.path.join(out, '_stack'); shutil.rmtree(out, ignore_errors=True); os.makedirs(stack)
    report = []
    with tempfile.TemporaryDirectory() as t:
        for r in reversed(rows):   # lowest priority first, so the first line of pack.tsv is applied last and wins
            src = os.path.join(t, r['id']); extract(os.path.join(arcs, r['file']), src)
            conv = os.path.join(t, 'c' + r['id'])
            rep = port_mod.main(src, R, conv, base=stack)
            for dp, _, fs in os.walk(conv):
                for f in fs:
                    if f == 'port.tsv': continue
                    rel = os.path.relpath(os.path.join(dp, f), conv); dst = os.path.join(stack, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copyfile(os.path.join(dp, f), dst)
            for x in rep: report.append((r['name'],) + tuple(x))
    with open(os.path.join(out, 'pack.tsv'), 'w') as f:
        for x in report: f.write('\t'.join(x) + '\n')
    return report

if __name__ == '__main__':
    if len(sys.argv) != 5: sys.exit(__doc__)
    for x in main(*sys.argv[1:]): print('\t'.join(x)[:200])
