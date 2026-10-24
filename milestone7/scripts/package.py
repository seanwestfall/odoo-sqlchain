"""Package source only, excluding private runtime, vendor checkout and dependencies."""
import hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'.local/release/package';out.mkdir(parents=True,exist_ok=True,mode=0o700)
files=[]
for directory in ['chainsql',*[f'milestone{i}' for i in range(8)]]:
 for p in (ROOT/directory).rglob('*'):
  if p.is_symlink() or not p.is_file():continue
  rel=p.relative_to(ROOT)
  if str(rel)=='milestone7/evidence/package.json':continue
  if any(part.startswith('.') or part in ['node_modules','__pycache__','dist'] for part in rel.parts):continue
  if p.name in ['Makefile','chainsql.control'] or p.suffix in ['.py','.mjs','.js','.json','.sql','.xml','.csv','.yaml','.yml','.md','.txt','.lock','.example','.html']:
   files.append(p)
files += [ROOT/'README.md']
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
archive=out/'chainsql-release-candidate.tar.gz'
with tarfile.open(archive,'w:gz') as tar:
 for p in sorted(files):tar.add(p,arcname='chainsql/'+str(p.relative_to(ROOT)),recursive=False)
 payload=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('chainsql/SOURCE-MANIFEST.json');info.size=len(payload);info.mode=0o644;tar.addfile(info,io.BytesIO(payload))
(out/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(json.dumps({'archive':str(archive),'source_files':len(files),'bytes':archive.stat().st_size}))
