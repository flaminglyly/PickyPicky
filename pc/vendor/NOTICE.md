# Third-party source notices

The local tool integrates GPL-3.0 components. Applicable license texts are retained in each vendor directory.

## jackotom/hongguo-drama

Source: https://github.com/jackotom/hongguo-drama
Commit: c67e423ea23656dad27845b9da09d68e246a2ab1
Files: app-source.js, sm3.js, download-quality.js, playback-device.js.
Playback update source tree: cd71e3ea7405d94b2de5c1b7e697c9dc5716c872 (2026-10-28). Registration attribution: tsukiyo-zero/hongguoTV commit 388931852ddc614db8b00775a3dc54c5ede6307f, DeviceRegister.kt; original source headers retained.
License: GPL-3.0-only, original source headers retained.
Local changes include anonymous playback registration, direct video-model parsing, bounded errors and registered identity handoff from the Python service. A separate app-worker.cjs adds a bounded local transport bridge. Original signing/Spade attribution to woshishiq1/drpys and N3urda/hongguoTV remains in app-source.js.

## zhenyong97/hongguo-downloader

Source: https://github.com/zhenyong97/hongguo-downloader
Commit: 85e024dba5e4187fbbc20ddcb173ba367a9840d7
Original upstream: 327044572/hongguo-downloader.
License: GPL-3.0, see LICENSE.
media.js extracts aes128EcbEncrypt, decryptSample, parseBoxes, rebuildMoov, and decryptMp4Buffer from src/native/hongguo.js. Network code, fixed device identifiers, key derivation, filesystem wrapper and original exports are excluded. The extracted media functions are unchanged; a crypto import and a minimal export are added.

Integration and extraction performed 2026-10-23. No captured user credentials are included. Axios and its dependencies retain their own licenses in node_modules and the dependency lock.
