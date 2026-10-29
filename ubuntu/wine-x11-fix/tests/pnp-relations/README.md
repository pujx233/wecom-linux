# PnP relation regression tests

`run-properties.py` compiles a synthetic Windows fixture and runs it in a private Wine prefix.
It removes the host display and D-Bus environment, points the system D-Bus address at a nonexistent
private socket, and creates only the fixture's `ROOT\WINEPNPRELATIONS` devices. It does not use the
WeCom account prefix or enumerate the host's Bluetooth devices.

```sh
python3 run-properties.py --wine /absolute/path/to/wine-runtime --out /absolute/path/to/new-result-dir --bits 64
python3 run-properties.py --wine /absolute/path/to/wine-runtime --out /absolute/path/to/another-result-dir --bits 32
```

The runtime must include both Windows architectures. The fixture pauses before creating its test
devices so the runner can identify its Linux process by the exact executable file mapping and verify
the architecture and SHA-256 of its executable `cfgmgr32.dll` and `setupapi.dll` mappings. Wine may
map relocated executable code anonymously, so identifying the fixture does not require its own file
mapping to be executable. The runner also records before/after hashes of both architectures of these
DLLs and `ntoskrnl.exe`, the fixture, its source, and the runner. A hash change fails the run.

The assertions cover both CM and SetupAPI entry points: required byte count, type, unchanged short
buffers, exact contents, property-key enumeration, empty results, absent relations, oversized Parent,
and another GUID with the same property id. After injecting a stale Siblings property, the fixture
changes Parent/Children relations and checks that query results follow the current relationships.
Running the same fixture on the old implementation must fail those assertions; passing only the
new implementation is insufficient evidence that the test detects the original problem.

The 8- and 16-child cases inspect registry value sizes and verify that queries do not create Siblings
values. This checks linear canonical storage at a small scale. It does not benchmark large device
enumerations, stress concurrent registry changes, or prove the real application's responsiveness.
The fixture sets canonical properties directly; the separate queue/PnP tests cover the producer.

Results and Wine output are saved in `result.json` and `wine.log`. The runner stops its private server
and normally removes the prefix. `--keep-prefix` retains it for another isolated test;
`--reuse-prefix /absolute/path/to/previous-result/prefix` accepts only a marked, inactive test prefix.
Reused prefixes are retained after the run and must be removed by the caller when no longer needed.
