"""Extract the source archive into a fresh directory and verify every declared file."""
import ast,hashlib,json,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];archive=ROOT/'.local/release/package/chainsql-release-candidate.tar.gz'
with tempfile.TemporaryDirectory(prefix='chainsql-package-check-') as directory:
 with tarfile.open(archive) as tar:
  names=tar.getnames()
  assert all(not any(part in ['.local','.git','node_modules','__pycache__'] for part in Path(n).parts) for n in names)
  assert not any(n.endswith(('.key','.pem','.dump','.sqlite','.env')) for n in names)
  tar.extractall(directory,filter='data')
 root=Path(directory)/'chainsql';manifest=json.loads((root/'SOURCE-MANIFEST.json').read_text())
 for name,digest in manifest.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
 for p in root.rglob('*.py'):ast.parse(p.read_text())
 assert (root/'milestone7/scripts/bootstrap.py').exists() and (root/'milestone7/scripts/fetch_odoo.py').exists()
 result={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'verified_source_files':len(manifest),'fresh_extraction':True,'private_runtime_excluded':True,'python_sources_parse':True,'independent_developer_installation':False}
 (ROOT/'milestone7/evidence/package.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
