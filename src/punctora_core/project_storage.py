"""Read-only byte accounting, without deleting saved generations or evidence."""
from pathlib import Path


def storage_report(root):
    root=Path(root)
    categories={name:{'logical_bytes':0,'unique_file_bytes':0,'files':0} for name in
        ('source_cache','recognition','evidence','preview','staging','other')}
    seen=set();shared=0
    files=sorted((p for p in root.rglob('*') if p.is_file() and not p.is_symlink()),
                 key=lambda p:('working-cache' not in p.parts,str(p)))
    for path in files:
        parts=path.relative_to(root).parts;stat=path.stat()
        category=('staging' if parts[0]=='staging' else 'source_cache' if 'working-cache' in parts
                  else 'recognition' if 'recognition' in parts or 'hybrid-recognition' in parts
                  else 'evidence' if 'evidence' in parts else 'preview' if path.name=='preview.bin' else 'other')
        item=categories[category];item['files']+=1;item['logical_bytes']+=stat.st_size
        key=(stat.st_dev,stat.st_ino) if stat.st_ino else str(path)
        if key not in seen:item['unique_file_bytes']+=stat.st_size;seen.add(key)
        else:shared+=stat.st_size
    return {'schema_version':1,'categories':categories,
        'total_logical_bytes':sum(v['logical_bytes'] for v in categories.values()),
        'total_unique_file_bytes':sum(v['unique_file_bytes'] for v in categories.values()),
        'shared_hardlink_bytes':shared,'scope':'file payload bytes, hardlinks counted once; filesystem allocation/compression not estimated'}
