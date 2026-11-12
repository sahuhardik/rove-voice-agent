# Knowledge pack review checklist

Produced by an independent audit on 2026-11-12: an auditor sampled 20-30 claims per pack and checked each against the
raw source text (`v2/knowledge/clean/`). Every entry below is a pack statement the auditor could NOT fully support.
The automated fact-check passes all packs; it only proves a number appears *somewhere* in the source, not that it is attached to the right thing.

How to use: for each item, open the pack line, read the quoted source evidence, then correct or delete the pack line.
Sampling means more problems than these almost certainly exist, especially in the Troubleshooting sections of the Dual and R3 packs,
whose sources are tiny (Dual pack is 3.4x its source, R3 pack 2.0x), so most of their playbook is not in the sources at all.

**75 claims need attention; 21 "Not covered by the sources" items are actually covered.**

## R2-4K (10 items)

- **UNSUPPORTED / HARMFUL** (Troubleshooting playbook): Firmware: something stopped working after update > reset to defaults, reformat card
  - Source says: R2-4K.txt — no post-firmware-update guidance; reformat erases footage
- **PARTIAL / MISLEADING** (Key facts): Parking mode requirements: Requires hard-wire kit for continuous power; uses internal battery for 1-min recording on G-sensor trigger
  - Source says: R2-4K.txt:1179-1186 — parking mode records 1 min 'on internal battery'; hard-wire requirement is stated only for Motion Detection (1172, 1655-1662), not Parking Mode. Pack attaches the hard-wire requirement to parking mode (Key facts, How-to line 198, troubleshooting 'No hard-wire kit (insufficient power for standby)')
- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Wi-Fi password rejected: no changes possible per sources; if customer changed it via app, check app settings or reset camera to defaults
  - Source says: R2-4K.txt:858,1420 — only default password 12345678; nothing about changing password in app (pack also contradicts itself)
- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Firmware won't boot after update (stuck on logo): press RESET once with paper clip while connected to power
  - Source says: R2-4K.txt:1565-1572 — reset button is for a frozen camera; no mention of boot logo or firmware-update failure
- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Nothing recorded while parked: cause G-sensor set too low; fix 'Lower G-sensor threshold (set to 1 or 5)'
  - Source says: R2-4K.txt:1237-1240 — 1=Low Impact Detection, 5=Medium (default), 9=High; no parked-not-recording troubleshooting exists; 'lower threshold' vs '1 or 5' is ambiguous/inverted
- **PARTIAL / HARMLESS** (Key facts): Built-in Li-ion battery 250mAh — NOT a supercapacitor
  - Source says: R2-4K.txt:334 — 'Built-in Li-ion battery 250mAh'; 'supercapacitor' appears nowhere in source (pack added the negation)
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Power: doesn't power down / drains car battery: hard-wired always-hot; use ACC/ON-only fuse; Motion Detection or Parking Mode left ON
  - Source says: R2-4K.txt:569-581 — ACC/ON fuse remedy supported; 'drains car battery' symptom and 'MD/Parking Mode left ON' as cause not stated
- **UNSUPPORTED / HARMLESS** (Key facts): Built-in WiFi, single band (no 5G mentioned)
  - Source says: R2-4K.txt — no WiFi band/GHz statement anywhere; 'single band' is the pack's inference
- **UNSUPPORTED / HARMLESS** (Troubleshooting playbook): Wi-Fi not in list: check if WiFi LED or indicator is active
  - Source says: R2-4K.txt:646-660 — LED section lists red/green LEDs only, no WiFi LED
- **UNSUPPORTED / HARMLESS** (Key facts): Mini-USB slot located on bottom right side of the camera
  - Source says: R2-4K.txt:398 — 'Mini-USB Power Input / Data output slot' is only a diagram label; no location stated

  *Listed as "Not covered" but the sources do cover it:*
  - Specific firmware version numbers — R2-4K.txt:1556 — 'ROVE-R2-4K-06102017 (First - Original Firmware)'

## R2-4K-DUAL (13 items)

- **PARTIAL / MISLEADING** (Format the card): Format steps: press MENU, arrows to format option, OK to confirm
  - Source says: R2-4K-DUAL.txt:106,135 give only generic MENU/arrow/OK navigation and 'format within settings'; no format path. general.txt:~120 (How To Format) says press DOWN to highlight FORMAT then OK; steps are synthesised, and monthly vs general's 'every 2-3 weeks'
- **PARTIAL / MISLEADING** (Power: drains car battery): Hardwire kit may have voltage cutoff; for long parking consider disconnecting hardwire or using cigarette lighter power only
  - Source says: Voltage monitoring is in general.txt:153 (cited to manual instead -> BAD_CITATION); general.txt:37 says cigarette socket may be 'always hot', so cigarette-lighter-only advice is not a safe fix and is unsourced
- **PARTIAL / MISLEADING** (Memory card too slow): card below Class 10 / U3 speed Rove requires for all models; format may temporarily help but replacement likely needed
  - Source says: general.txt:304 'Replace with a Class 10 U3 ... recommended'; 809 'basic requirement ... Class 10 or U3'; general.txt:292 'In most cases, formatting or replacing ... resolves the issue immediately' - pack downplays format
- **UNSUPPORTED / MISLEADING** (Troubleshooting Wi-Fi not in list): Press MENU, navigate to Wi-Fi settings, ensure enabled
  - Source says: Manual has no Wi-Fi menu path. general.txt:675 says System Settings > WiFi Mode 5GHz->2.4GHz for this model, and 558 'turn the WIFI ON from the Dashcam' - the actual useful fix (2.4GHz switch) is missed
- **UNSUPPORTED / MISLEADING** (Firmware won't boot): If stuck on logo: format microSD via menu or PC; contact Rove for recovery firmware
  - Source says: No boot-stuck guidance in R2-4K-DUAL.txt; formatting erases footage and is not sourced as a fix for this symptom
- **BAD_CITATION / HARMLESS** (Power on/off): Power off: disconnect power cable, or ignition off; Power on automatically with ignition
  - Source says: Power-on at R2-4K-DUAL.txt:101 supported; power-off behaviour is in general.txt:35 ('shut down automatically when power is removed'), not the cited manual
- **PARTIAL / HARMLESS** (How to recognise): 5G Wi-Fi (not stated as present on other models)
  - Source says: clean/general.txt:654-665 — other models also dual-band 5GHz & 2.4GHz; so 5G is not a distinguishing cue
- **PARTIAL / HARMLESS** (Loop recording): Records in 1, 3, or 5-minute segments
  - Source says: clean/R2-4K-DUAL.txt:116 — '(e.g., 1, 3, or 5-minute segments)' is an example; general.txt:207 says 1,3,5 or 10 and loop can be turned off
- **PARTIAL / HARMLESS** (App: broke after OS update / permissions): Clear app cache/data; phone Settings > Apps > ROVE > Permissions enable all
  - Source says: Manual silent; general.txt:558,583 say reinstall app and ALLOW ALL PERMISSIONS, but no cache-clear or Android path
- **PARTIAL / HARMLESS** (Power: date/time): Supercapacitor doesn't hold charge long-term; re-set date/time
  - Source says: Manual silent on this; general.txt:234 'My R2-4K PRO does not hold a charge' discusses supercapacitor; GPS time zone setting at general.txt:110,123 exists, pack says steps not specified
- **UNSUPPORTED / HARMLESS** (Troubleshooting Wi-Fi slow): Likely causes include using 2.4GHz band; fix: download smaller clips; try alternative band (2.4G vs 5G) for drops
  - Source says: R2-4K-DUAL.txt:157-158 only lists password/proximity/app/restart; no band-switching or smaller-clip advice
- **UNSUPPORTED / HARMLESS** (Safety): Do not operate menu or app while driving; set up before departure
  - Source says: No such statement in R2-4K-DUAL.txt
- **UNSUPPORTED / HARMLESS** (Recording: stops): Cause includes overheating protection; check for temperature warnings
  - Source says: R2-4K-DUAL.txt:151-152 lists full/corrupted card and power interruption only; overheating is a general.txt:327 topic

  *Listed as "Not covered" but the sources do cover it:*
  - Wi-Fi default SSID and password — clean/general.txt:597,639 — 'ROVE_R***_*******' network, default password '12345678' also shown on camera screen
  - Reset to factory defaults — clean/general.txt:367-368,557 — System Settings > Default Settings (back up footage first); reset button at bottom general.txt:64,93
  - Date/time setting procedure — clean/general.txt:123 — two ways: manually or GPS time zone (UTC/GMT offset); general.txt:110
  - Manual firmware update (SD card flash) — clean/general.txt:534 — 'insert the memory card ... press power button once ... blinking RED LED'; also update-firmware-r2-4k.html section
  - Loop recording interval selection / LED meanings — clean/general.txt:207 — loop 1,3,5 or 10 min, can be turned off; 534 blinking RED LED = firmware updating

## R2-4K-DUAL-PRO (8 items)

- **BAD_CITATION / MISLEADING** (Troubleshooting: restarts randomly): If still occurring, format memory card [manual: B0F9SX3JB9]
  - Source says: B0F9SX3JB9 (R2-4K-DUAL-PRO.txt:3665-3680) lists format only for Recording stops unexpectedly; main manual :3330 for on/off says reset your camera, try updating firmware - no format step; format erases footage
- **PARTIAL / HARMLESS** (Format the card): Recommended: format every 3 months
  - Source says: R2-4K-DUAL-PRO.txt:1654 says every 3 months, but second cited source B0F9SX3JB9 (same file :157) says at least once a month; conflict not flagged
- **PARTIAL / HARMLESS** (Troubleshooting: restarts randomly): Use ONLY ROVE supplied USB car charger or hardwire kit; then reset to factory defaults
  - Source says: R2-4K-DUAL-PRO.txt:931-934 supports ROVE charger; :3330 says reset your camera (ambiguous), pack escalates to DESTRUCTIVE factory reset
- **PARTIAL / HARMLESS** (Troubleshooting: nothing recorded while parked): Cause: hardwire kit installed with wrong fuse type (not constant power)
  - Source says: B0F9SX3JB9 :3686 connected to a constant power source supports; wrong fuse type phrasing unsourced
- **PARTIAL / HARMLESS** (Recognise): Both suction AND sticky mount included (most Rove models include only one)
  - Source says: R2-4K-DUAL-PRO.txt:579,751 supports both mounts; 'most Rove models include only one' not in source
- **UNSUPPORTED / HARMLESS** (Troubleshooting: permission screen): iOS may need Local Network permission enabled in iPhone Settings
  - Source says: No 'Local Network' or permissions guidance in R2-4K-DUAL-PRO.txt
- **UNSUPPORTED / HARMLESS** (Troubleshooting: sign-in error): Try Forgot Password
  - Source says: No 'forgot' in R2-4K-DUAL-PRO.txt; only :1826 says internet needed to log in
- **UNSUPPORTED / HARMLESS** (Troubleshooting: won't boot after update): Press RESET once; if stuck contact customer care; may require manual reflash
  - Source says: No stuck-on-logo guidance; RESET documented for freezing (:2954) and no-power (:3283) only

  *Listed as "Not covered" but the sources do cover it:*
  - Cloud storage options or subscription services — clean/R2-4K-DUAL-PRO.txt:1757-1759 - NOT a cloud or IP camera; general.txt Is there any monthly/annual subscription: NO NEED to purchase any subscription
  - Exact factory default values for each setting — clean/R2-4K-DUAL-PRO.txt:2160,2276-2290,2750-2790 - (Default) marked on loop 1-MIN, bitrate Standard, brightness High, voice ON
  - Warranty claim procedures beyond contact customer care — clean/R2-4K-DUAL-PRO.txt:3150-3162,130,249 - 1-year limited warranty terms; general.txt: register dash cam via app/website to activate warranty
  - Specific fuse/wiring instructions for hardwire kit — clean/R2-4K-DUAL-PRO.txt:2299-2304 - connect to car's fuse box, NOT battery terminals; step-down circuit

## R2-4K-PRO (11 items)

- **CONTRADICTED / MISLEADING** (How-to procedures): Daylight savings: use one hour less when DST active (March-Nov), one hour more when DST ends (Nov-March)
  - Source says: R2-4K-PRO.txt:998-1015 table — Pacific is GMT (-8:00) Nov-March and GMT (-7:00) March-Nov, i.e. one hour MORE (-7) when DST begins and one hour LESS (-8) when it ends; pack states the reverse
- **PARTIAL / MISLEADING** (Troubleshooting playbook): Wi-Fi drops repeatedly: try 5.0GHz for faster/shorter range or 2.4GHz for longer range; reset with RESET button; escalate if drops persist within 3M clear line of sight
  - Source says: R2-4K-PRO.txt:1882-1887 — band trade-off supported, but never offered as a drop fix (5.0GHz has LESS coverage); RESET for Wi-Fi drops, 'interference from other devices' and the '3M' escalation threshold are not in source (range is 10M, 1054-1057)
- **PARTIAL / MISLEADING** (Troubleshooting playbook): Firmware stalled / stopped working after update: restart update, reset DEFAULT SETTING, retry; 'explicitly stated to reach out to customer care'
  - Source says: R2-4K-PRO.txt:488-490 — only 'reach out to customer care if you are having trouble installing firmware'; restart-update and default-reset steps are the pack's own, presented as sourced
- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Firmware stuck on logo: failed/corrupted install; press RESET once; try firmware update again
  - Source says: R2-4K-PRO.txt — RESET only described for a frozen camera (hardware reset section); no boot-logo or failed-update text. Only firmware guidance is OTA steps + 'reach out to customer care' (488-490)
- **PARTIAL / HARMLESS** (How-to procedures): Reset to defaults does NOT delete video files; hardware RESET button 'no data lost'
  - Source says: R2-4K-PRO.txt:2065 — 'camera's all settings to be set back to the factory default settings'; no explicit statement that videos are kept (reasonable inference)
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Wi-Fi playback/download slow: causes 2.4GHz band, large 4K files, phone/app compatibility; fix switch to 5.0GHz
  - Source says: R2-4K-PRO.txt:1883-1887 — 5.0GHz transmits faster (and suggested by default); causes (2)/(3) not stated
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Power: doesn't power down: Option 1 (Recommended) ROVE's 3-Lead Auto Trigger Hardwire Kit; Option 2 ACC/ON fuse
  - Source says: R2-4K-PRO.txt:701-706 — names '3-Lead Auto Trigger Hardwire Kit' (supported) but does not label it 'Recommended'; elsewhere (1448, 1480) source requires 'ROVE Ultimate USB Type-C Hardwire Kit' for this PRO, so pack carries an inconsistent kit name from the source without flagging it
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Manually power off camera when parking: press and hold power button 3 seconds
  - Source says: R2-4K-PRO.txt:691-692 — 'at least 2-3 seconds'; pack's own How-to (line 36) says 2-3
- **UNSUPPORTED / HARMLESS** (Key facts): LED indicator: Red LED on top
  - Source says: R2-4K-PRO.txt:532 — 'LED Indicator 7' is only a diagram label; no 'on top' location. Colour meanings (826-830) are supported
- **UNSUPPORTED / HARMLESS** (Troubleshooting playbook): App broke after OS update: likely cause app compatibility issue with new OS version (cited [manual])
  - Source says: R2-4K-PRO.txt — no OS-compatibility statement (only 1886 about older devices supporting only 2.4GHz)
- **UNSUPPORTED / HARMLESS** (Troubleshooting playbook): App stuck on permission screen: grant all requested app permissions
  - Source says: R2-4K-PRO.txt — no app-permission guidance; registration-needs-internet part is supported (Key 'First Time Users')

  *Listed as "Not covered" but the sources do cover it:*
  - Cloud storage or remote viewing capabilities (explicitly stated NOT available) — R2-4K-PRO.txt:1038-1042 — 'NOT made to broadcast footage over the cloud or internet'
  - Waterproof/dustproof ratings (only stated not damp-proof) — R2-4K-PRO.txt:323-324 'not designed to be damp-proof'; 346 'Do not expose ... to dust'; 355 'For indoor use ONLY' (no IP rating, but guidance exists)

## R2-4K-USB-C (9 items)

- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Firmware update stalled: causes Wi-Fi lost / power interruption; restart camera and retry; may need manual firmware installation
  - Source says: R2-4K-USB-C.txt:362-364 — only 'reach out to customer care if you are having trouble installing firmware'; no stall guidance, no manual install path
- **UNSUPPORTED / MISLEADING** (Troubleshooting playbook): Firmware stuck on logo: corrupted firmware; RESET once; remove card, power cycle, try booting
  - Source says: R2-4K-USB-C.txt — no boot-logo/corrupted-firmware text; reset only described for frozen camera (2010 area)
- **PARTIAL / HARMLESS** (How-to procedures): Auto power off within 1-2 seconds when power disconnects
  - Source says: R2-4K-USB-C.txt:587-588 — 'OFF automatically within a few seconds'; no '1-2 seconds' figure
- **PARTIAL / HARMLESS** (How-to procedures): Manual power off: press and hold Power for 3 seconds
  - Source says: R2-4K-USB-C.txt:606-607 — 'hold the power button for at least 2-3 seconds'
- **PARTIAL / HARMLESS** (How-to procedures): Reset to defaults: System Settings > DEFAULT SETTINGS > OK; 'Videos are NOT deleted'
  - Source says: R2-4K-USB-C.txt:1960-1964 — 'restore all the settings to the factory default settings'; no statement about videos being kept
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Hot: built-in temperature sensor shuts camera down above 140F (60C)
  - Source says: R2-4K-USB-C.txt:1459-1463 — sensor shuts down when temperature 'exceed[s] the recommended guidelines'; the 140F figure is the operating-range limit (348), not stated as the shutdown trigger
- **PARTIAL / HARMLESS** (Troubleshooting playbook): Playback/download slow: lower Video Bit Rate to Standard or Low; lower to 1080P; replace card if not U3
  - Source says: R2-4K-USB-C.txt:1414-1424 — high bitrates mean longer app downloads; 2289 — record at lower resolution for PC lag. Pack's 'Standard' is the default (1423), so 'Standard or Low' adds nothing; card-speed cause not tied to slowness
- **UNSUPPORTED / HARMLESS** (Troubleshooting playbook): App stuck on permission screen: ensure location permissions granted
  - Source says: R2-4K-USB-C.txt — 'permission' appears only in copyright text (2146); no app permission guidance
- **UNSUPPORTED / HARMLESS** (Troubleshooting playbook): App broke after OS update: uninstall and reinstall ROVE app (cited [manual])
  - Source says: R2-4K-USB-C.txt — no 'reinstall/uninstall' or OS-compat text; pack even says 'Not covered' yet attaches a manual citation

  *Listed as "Not covered" but the sources do cover it:*
  - Bluetooth functionality (explicitly stated NOT Bluetooth — uses Wi-Fi) — R2-4K-USB-C.txt:945-947 — 'cameras use a WiFi signal (instead of Bluetooth)'
  - Cloud storage or remote viewing capabilities (explicitly stated NOT supported) — R2-4K-USB-C.txt:957-959 — 'NOT made to broadcast footage over the cloud or internet'
  - Whether CPL filter is included or must be purchased — R2-4K-USB-C.txt:142 — 'Pre Threaded for Optional CPL Filter (Not Included, Purchase Separately)'
  - Specific video codec details beyond H.264/H.265 — R2-4K-USB-C.txt:1402-1412 — H.265 HEVC explained, H.264 default, H.265 lag warning (the pack itself uses this)

## R3 (14 items)

- **PARTIAL / MISLEADING** (Reset to defaults / Safety): Reset to defaults: no reset exists; only unplug/replug. Factory reset: No dedicated reset
  - Source says: general.txt:367-368 (r3-no-gps-live-speed help page, R3-specific) - Go to the camera's SYSTEM SETTINGS, then set to DEFAULT SETTINGS, back up footage first; pack omits the software factory reset that does exist on R3
- **PARTIAL / MISLEADING** (Firmware: can't update / won't boot): R3 updates via ROVE APP only, not manual file download; stuck on logo: unplug/replug then contact customer care for manual firmware update
  - Source says: R3.txt:37,44 support OTA via app; R3.txt:40-41 explicitly says contact care for 'a manual firmware update' so manual route exists; stuck-on-logo symptom itself not described (only :42 touch/icons failed update)
- **UNSUPPORTED / MISLEADING** (Troubleshooting: password rejected / Safety): If WiFi password changed and forgotten: no reset method documented; customer must contact support for manual firmware update option
  - Source says: R3.txt has no WiFi-password-change or recovery text (grep password finds only default 12345678 at :24,27); general.txt:164 has a change-WiFi-password page and :557/573 System Settings > Default Settings; manual firmware link is invented
- **UNSUPPORTED / MISLEADING** (Troubleshooting: nothing recorded while parked): Adjust Parking Mode G-sensor level (9 levels, -2.0 to +2.2) - lower number for higher sensitivity
  - Source says: clean/R3.txt:33 gives 9 levels from -2.0 to +2.2 and says tapping the LCD or closing a door can trigger; it never says which direction is more sensitive
- **UNSUPPORTED / MISLEADING** (Firmware: something stopped working): Reformat card in camera after ensuring firmware is latest (DESTRUCTIVE)
  - Source says: No source ties card format to post-update problems (R3.txt:42,44); erases all footage
- **UNSUPPORTED / MISLEADING** (Troubleshooting: drains battery): Verify HWK on correct fuse (switched, not constant, if wanting auto-off); consider accessory-only fuse or unplug when parked
  - Source says: Not in R3.txt; R3.txt:30-31 says parking mode needs hardwiring to the fuse box; an accessory-only fuse would disable parking mode (cf. DUAL-PRO source:1233 only for cigarette outlet)
- **PARTIAL / HARMLESS** (Recognise): Wi-Fi network name appears as 'ROVE R3'
  - Source says: R3.txt:24 says 'ROVE R3 WiFi'; general.txt:663 gives pattern 'ROVE_R3_' or 'Rove_R3_' followed by characters
- **PARTIAL / HARMLESS** (Key facts): microSDXC Class 10 or U3 only; max 512GB; ROVE Ultimate recommended; format as MS-DOS (FAT) on Mac or FAT32 on Windows
  - Source says: R3.txt:4-6,20 support Class 10/U3, 512GB, MS-DOS (FAT) [Mac OS]; the Windows format name is cut off in source (:4 'formatted [Windows] or') and FAT32 appears nowhere
- **PARTIAL / HARMLESS** (Set date/time): Time Zone Setting: three options in System Settings > Time Zone Setting; manual in System Settings > Date/Time
  - Source says: clean/R3.txt:22 - 'Time Zone Setting: Choose from three options ... Manually ... System Settings > Date/Time or automatic ... GMT/UTC when GPS lock'; 'System Settings > Time Zone Setting' path is inferred
- **PARTIAL / HARMLESS** (Troubleshooting: Wi-Fi drops): Apple devices disconnect due to priority switching; reinstall app, sign in, reconnect; also disable Auto-Join/turn off cellular data
  - Source says: R3.txt:43-44 supports Apple priority switching and reinstall; Auto-Join/cellular-off steps are not in the source
- **PARTIAL / HARMLESS** (Troubleshooting: GPS / speed): Fix: enable GPS stamp in video stamps; GPS Player for PC/Mac; update firmware for compass bug
  - Source says: R3.txt:34,37,44 support the pieces; omits the R3 help page steps (mount gap check, placement away from vehicle GPS antenna, set to DEFAULT SETTINGS) at general.txt:357-368; compass bug is not a GPS speed fix
- **PARTIAL / HARMLESS** (Troubleshooting: Wi-Fi not in list): Wait 10-15 seconds after enabling WiFi for network to broadcast
  - Source says: R3.txt:24 - 10-15 s wait is for the notification pop-up after joining the network, not for the SSID to appear
- **UNSUPPORTED / HARMLESS** (Safety / Power hot): Heat damage not covered by warranty (warranty may not cover)
  - Source says: R3.txt:38-39 give one-year limited warranty for defects; nothing about heat exclusions
- **UNSUPPORTED / HARMLESS** (Troubleshooting: app permissions): Settings > Apps > ROVE > Permissions; iOS Local Network permission
  - Source says: No permissions guidance in R3.txt

  *Listed as "Not covered" but the sources do cover it:*
  - Specific Wi-Fi frequency band (2.4GHz vs 5GHz) — clean/general.txt:661-665 - R3: Dual-band 5GHz & 2.4GHz, up to 30MB/s over 5GHz; :675 System Settings > WiFi Mode 5GHz to 2.4GHz applies to R3
  - Manual lock procedure (How-to says Not specified) — clean/general.txt:680 - 'tap the lock icon (R3)'; :667 Emergency lock short press locks
  - Warranty claim process details beyond email customer care — clean/R3.txt:38-39 - one year limited warranty from purchase, save warranty/serial number card as evidence, replacement units new or refurbished; general.txt: registration activates warranty

## general (10 items)

- **PARTIAL / HARMFUL** (Loop recording overwrote): Locked/protected videos aren't overwritten by loop recording [official: connect-rove-to-phone]
  - Source says: general.txt:680 says it, but R2-4K-DUAL-PRO.txt:2183-2190 says locked videos are also deleted (oldest first) once the event folder hits 30%; R3.txt:29 says loop does not affect locked videos. Blanket statement may make a DUAL PRO customer think locked footage is permanent
- **PARTIAL / HARMFUL** (Firmware: after update): After any firmware update: format memory card immediately or camera keeps updating firmware every restart (DESTRUCTIVE)
  - Source says: general.txt:803-805 (manual card-copy method) and :858-859 only; the OTA steps (:758-780, :680-690) say nothing about formatting. 'Any firmware update' would make OTA users erase their footage needlessly
- **BAD_CITATION / MISLEADING** (Support contacts): Email: [email protected]; Text 1-844-768-3226 [help: repeatedly-on-off]
  - Source says: general.txt:390-418 (repeatedly-on-off) has no contact block (contacts are in random-restarting/others). The source email is an obfuscated placeholder '[email protected]' (e.g. general.txt:385), so the agent is given no real address; real address help@rovedashcam.com appears only at general.txt:815. R3.txt:5,47 also lists a different text number (401) 484-7683
- **BAD_CITATION / MISLEADING** (Repeatedly on/off): Press RESET button; this clears glitches and returns the camera to factory settings [help: repeatedly-on-off]
  - Source says: repeatedly-on-off (general.txt:403-405) says only 'clear temporary glitches'; 'return to factory settings' is in random-restarting (:380). R2-4K-DUAL-PRO.txt:2953-2960 says RESET only restarts and settings default is a separate menu item
- **PARTIAL / MISLEADING** (Sign-in error): Search spam for sender [email protected]; add to Safe Senders
  - Source says: general.txt:430-433 - the sender address is obfuscated in the source too, so the agent cannot tell the customer which address to whitelist
- **WRONG_MODEL / MISLEADING** (Safety): Designed to operate between -4F and 140F (-20C to 60C); beyond this device may slow down, shut off or stop recording
  - Source says: general.txt:332 (overheating) says it, but R2-4K-DUAL-PRO.txt:562 gives 14F (-10C) to 131F (55C) for that model; pack applies one range to all models
- **WRONG_MODEL / MISLEADING** (Firmware: manual update): Manual update: insert card in PC, or connect camera via USB and select Connect as USB Flash Drive [official: firmware-update-downloads]
  - Source says: USB flash-drive option is in update-firmware-r2-4k (general.txt:830-831), for the R2-4K only with 2.5ft cable, not in firmware-update-downloads (:790-810); general.txt:697 says DUAL PRO can't connect to a computer directly; R3.txt:40-44 says manual updates go through customer care
- **BAD_CITATION / HARMLESS** (Power: drains battery): 24-hour parking without draining battery requires 3-Lead Hardwire Kit with voltage monitoring [help: overheating]
  - Source says: overheating (general.txt:345) says 'built-in protection for your dash cam and your vehicle's battery'; 'voltage monitoring' is in know-your-dashcam-how-to (general.txt:153)
- **PARTIAL / HARMLESS** (Overheating / Memory card): Format in-camera every 1-2 weeks (overheating) and every 2-3 weeks (know-your-dashcam)
  - Source says: general.txt:339 '1-2 weeks'; know-your-dashcam 'every 2-3 weeks'; model manuals say monthly (R2-4K-DUAL.txt:135) or every 3 months (R2-4K-DUAL-PRO.txt:1654); pack lists two figures without reconciling
- **PARTIAL / HARMLESS** (Firmware: check version): Check firmware version: camera system settings > firmware version [official: update-firmware-r2-4k]
  - Source says: general.txt:861 is the R2-4K (mini-USB) page; applied to all models

  *Listed as "Not covered" but the sources do cover it:*
  - Video/Audio: GPS/speed not showing (non-R3 models) - specific fixes — clean/general.txt:134-135 (view GPS route via orange icon in app), :183 (Enable/Disable Date/Time, Speed, GPS Stamps in settings), :111 (GPS Time Zone); R2-4K-DUAL-PRO.txt:2636 speed stamp menu
  - Memory card: Card full and stopped instead of looping - specific camera setting adjustments — clean/general.txt:207 - 1, 3, 5 or 10 minute loop chunks, with the option to turn loop cycle recording on/off; R2-4K-DUAL-PRO.txt:3290-3296 gives menu path
