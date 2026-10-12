"""Reserve staged mapped arrays before touching pages, avoiding fatal disk-full faults."""
import errno
import os
from pathlib import Path
import shutil
import numpy as np


def mapped_array(path,dtype,shape,raw=False):
    path=Path(path);required=int(np.prod(shape))*np.dtype(dtype).itemsize+4096
    if shutil.disk_usage(path.parent).free<required+1024*1024:
        raise ValueError(f'Insufficient temporary disk space for {required:,} bytes of staged data')
    result=(np.memmap(path,mode='w+',dtype=dtype,shape=shape) if raw else
            np.lib.format.open_memmap(path,mode='w+',dtype=dtype,shape=shape))
    try:
        if hasattr(os,'posix_fallocate'):
            with path.open('r+b') as handle:
                try:os.posix_fallocate(handle.fileno(),0,path.stat().st_size)
                except OSError as error:
                    if error.errno not in {errno.ENOSYS,errno.EOPNOTSUPP,errno.EINVAL}:raise
        return result
    except OSError as error:
        result._mmap.close();path.unlink(missing_ok=True)
        if error.errno==errno.ENOSPC:
            raise ValueError('Insufficient temporary disk space while reserving staged data') from error
        raise
