# Windows preview runtime notices

Original Punctora code is Apache-2.0; adapted Cloud2BIM routines retain MIT. The portable package includes `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `ATTRIBUTIONS.md`, full retained texts in `third_party`, wheel-supplied licence files in `worker/packages`, Python's complete licence in `worker/python/LICENSE.txt`, and a version/hash manifest. No AI code, model weights or scan examples are redistributed.

| Component | Version | Notice/source location |
| --- | --- | --- |
| Avalonia desktop packages | 12.1.3 | MIT; `third_party/licenses/Avalonia-12.1.3-MIT.txt`; source commit `8eeda4f6f546165b3f72e63c9f42247abb306905` at https://github.com/AvaloniaUI/Avalonia |
| ANGLE Windows native library | 2.1.27548.20260419 | Full BSD and bundled notices from its NuGet `LICENSE`; https://github.com/AvaloniaUI/angle/tree/1c89805903c1482166356d3b950d474973180e61 |
| SkiaSharp / native Skia | 3.119.4 | MIT wrapper and full native third-party notices retained from Win32 package; https://github.com/mono/SkiaSharp/tree/f568ac94dd768ef9a2f593537cfde2dd0d348ef5 |
| HarfBuzzSharp / native HarfBuzz | 8.3.1.3 | MIT wrapper and full native third-party notices retained from Win32 package; https://github.com/mono/SkiaSharp/tree/2888c737ad016d584c74525e2d35db5097ea8576 |
| MicroCom.Runtime | 0.11.6 | MIT; source/licence retained at commit `76785efcafd91b5902fd19dd11145f6dd655b7b4`; https://github.com/kekekeks/MicroCom |
| Avalonia.BuildServices | 11.3.2 | Build dependency, MIT; source/licence retained at commit `777f975b0a0cecf0311273711d56697212c558c0`; https://github.com/AvaloniaUI/Avalonia.BuildServices |
| Tmds.DBus.Protocol | 0.94.1 | Linux desktop dependency, MIT; source/licence retained at commit `b4a7fed0b878f74cb54f7cca84d2889af4e596ba`; https://github.com/tmds/Tmds.DBus |
| .NET runtime | 10.0.0 | MIT and complete runtime-pack `THIRD-PARTY-NOTICES.TXT` retained; https://github.com/dotnet/runtime/tree/v10.0.0 |
| CPython Windows embedded runtime | 3.12.10 | PSF and bundled notices retained from the exact archive; https://www.python.org/downloads/release/python-31210/ |
| Microsoft C++ runtime | MSVCP140 14.44.35215.0; Python-bundled VCRUNTIME140 14.42.34438.0 | Microsoft Corporation; the unmodified MSVCP DLL supplied by the Shapely Windows wheel is copied to the embedded Python application directory. Exact wheel-supplied MSVC notice remains in `worker/packages/shapely-2.1.2.dist-info/licenses/LICENSE_win32`; source/destination/hash are recorded in the package manifest. |
| Python and native worker dependencies | Exact versions in `windows-wheel-hashes.json` | Wheel-provided licences remain installed; Windows licence snapshots and archive hashes are retained in `third_party/LICENCE_SOURCES.json`. Source links and credits are in `ATTRIBUTIONS.md`. |

IfcOpenShell 0.8.3 is an external, unmodified LGPL-3.0-or-later library. The package retains LGPL/GPL texts even though its wheel does not supply standalone licence files. Library source is available at https://github.com/IfcOpenShell/IfcOpenShell/tree/d7cf803fdfb38df1e3eb37879cc04f733339b704 and build instructions at https://docs.ifcopenshell.org/ifcopenshell/installation.html. The exact distributed wheel and hash are listed in `windows-wheel-hashes.json`; its upstream distribution is https://pypi.org/project/ifcopenshell/0.8.3/#files. Shapely's GEOS library retains its own LGPL text and installed replacement interface; source: https://libgeos.org/ and https://github.com/libgeos/geos. pye57's libE57Format, Xerces-C++ and CRC++ notices are retained separately.

These libraries are not merged into a Punctora executable. Their Python packages/native binaries remain separate in `worker/packages`; replacing a compatible library does not require relinking original Punctora code. To use a replacement worker environment, install the core and compatible dependencies in Python 3.11/3.12 and set `PUNCTORA_PYTHON` to its executable. Changes made for debugging an LGPL library are not prohibited by Punctora's licence. The retained third-party licences remain authoritative.

This document records the preview build's runtime/notices work. Clean-machine installation, independent IFC-viewer acceptance and the final installer audit remain M4 checks.

IfcOpenShell EXPRESS validation uses the unmodified pytest 8.4.2 assertion rewriter at runtime. The Windows worker also retains its pinned iniconfig, packaging, pluggy, pygments and colorama dependencies, complete wheel-supplied notices and hashes. See the validation-runtime table in `ATTRIBUTIONS.md`; these are runtime dependencies, not optional test-only files.
