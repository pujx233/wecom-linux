#!/usr/bin/env python3
"""Exercise Wine's reference-counted Bluetooth name cache under LeakSanitizer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
source, output = args.source.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
text = (source / 'dlls/winebth.sys/unixlib.c').read_text()
functions = text[text.index('static int compare_string('):text.index('static void *dbus_connection;')]
header = (source / 'dlls/winebth.sys/unixlib_priv.h').read_text()
structure = header[header.index('struct unix_name\n'):header.index('\n};', header.index('struct unix_name\n')) + 3]
probe = '''#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include "wine/rbtree.h"
typedef size_t SIZE_T;
''' + structure + '\n' + functions + '''
static void *worker(void *arg)
{
    char key[64];
    for (int i = 0; i < 10000; ++i)
    {
        snprintf(key, sizeof(key), "name-%ld-%d", (long)arg, i);
        struct unix_name *a = unix_name_get_or_create(key);
        struct unix_name *b = unix_name_get_or_create(key);
        assert(a == b && !strcmp(a->str, key));
        unix_name_dup(a);
        unix_name_free(a);
        unix_name_free(b);
        unix_name_free(a);
    }
    return NULL;
}
int main(void)
{
    pthread_t threads[4];
    for (long i = 0; i < 4; ++i) assert(!pthread_create(&threads[i], NULL, worker, (void *)i));
    for (int i = 0; i < 4; ++i) assert(!pthread_join(threads[i], NULL));
    assert(!names.root);
    return 0;
}
'''
(output / 'cache.c').write_text(probe)
executable = output / 'cache'
subprocess.run(['cc', '-g', '-O1', '-fsanitize=address', '-fno-omit-frame-pointer', '-pthread',
                '-I' + str(source / 'include'), str(output / 'cache.c'), '-o', str(executable)], check=True)
result = subprocess.run([str(executable)], capture_output=True, text=True)
(output / 'sanitizer.log').write_text(result.stdout + result.stderr)
report = {'passed': result.returncode == 0, 'exit_code': result.returncode, 'threads': 4,
          'distinct_names': 40000, 'source_sha256': hashlib.sha256(text.encode()).hexdigest()}
(output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(result.returncode)
