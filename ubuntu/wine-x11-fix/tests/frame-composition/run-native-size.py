#!/usr/bin/env python3
"""Check the production RECT-to-X11 dimension conversion without starting Wine or using a display."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True, help='Wine source root')
parser.add_argument('--out', type=Path, required=True, help='new evidence directory')
args = parser.parse_args()
source = args.source.resolve() / 'dlls/winex11.drv/window.c'
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=False)
text = source.read_text()
start = text.index('static int get_native_dimension(')
end = text.index('\n}', start) + 2
helper = text[start:end]
harness = out / 'native-size.c'
harness.write_text(r'''
#include <stdint.h>
#include <stdio.h>
typedef int32_t LONG;
typedef int64_t LONGLONG;
#define min(a,b) (((a) < (b)) ? (a) : (b))
#define max(a,b) (((a) > (b)) ? (a) : (b))
''' + helper + r'''
int main(void)
{
    static const struct { LONG start, end; int expected; } cases[] = {
        {0, 0, 1}, {0, 1, 1}, {1, 0, 1}, {0, -1, 1}, {0, 65535, 65535}, {0, 65536, 65535},
        {-100, 100, 200}, {INT32_MIN, INT32_MIN, 1}, {INT32_MAX, INT32_MAX, 1},
        {INT32_MIN, INT32_MAX, 65535}, {INT32_MAX, INT32_MIN, 1},
        {INT32_MIN, INT32_MIN + 1, 1}, {INT32_MAX - 200, INT32_MAX, 200},
        {INT32_MIN, INT32_MIN + 65535, 65535}, {INT32_MIN, INT32_MIN + 65536, 65535}
    };
    unsigned int i, failures = 0;
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
    {
        int actual = get_native_dimension(cases[i].start, cases[i].end);
        int passed = actual == cases[i].expected;
        printf("{\"start\":%d,\"end\":%d,\"expected\":%d,\"actual\":%d,\"passed\":%s}\n",
               cases[i].start, cases[i].end, cases[i].expected, actual, passed ? "true" : "false");
        failures += !passed;
    }
    return failures != 0;
}
''')
command = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
           '-fno-sanitize-recover=all', str(harness), '-o', str(out / 'native-size')]
build = subprocess.run(command, capture_output=True, text=True)
(out / 'build.log').write_text(build.stdout + build.stderr)
build.check_returncode()
run = subprocess.run([str(out / 'native-size')], capture_output=True, text=True, timeout=10)
report = {'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'helper_sha256': hashlib.sha256(helper.encode()).hexdigest(),
          'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'harness_sha256': hashlib.sha256(harness.read_bytes()).hexdigest(), 'compile': command,
          'cases': [json.loads(line) for line in run.stdout.splitlines()], 'stderr': run.stderr,
          'returncode': run.returncode, 'passed': run.returncode == 0,
          'scope': 'Dimension conversion only; no claim about preceding RECT arithmetic or real X11 transitions.'}
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(out / 'result.json'), 'passed': report['passed'], 'cases': len(report['cases'])}))
raise SystemExit(0 if report['passed'] else 1)
