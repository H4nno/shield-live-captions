# Getting TV audio into the server

Android does not allow on-device capture of DRM-protected playback (Netflix,
Prime, Disney+, …), so the audio has to be tapped **after** it leaves the box.
Any of the following works; the cheap ones are listed first.

## Option A: AVR / receiver pre-out → USB audio interface

If an AVR sits between the TV box and the TV:

```
[TV box] --HDMI--> [AVR] --HDMI--> [TV]
                     │
                     +-- front L/R pre-out (RCA)
                                  │
                          [USB audio interface] --> GPU host
```

- Use the **main-zone front L/R pre-out** (usually next to the subwoofer out).
  It carries every source, including HDMI, and follows the main volume.
- Beware **Zone 2 pre-outs**: on many receivers (Marantz/Denon of the x011
  era, others) Zone 2 only plays *analog and network* sources — HDMI audio
  never reaches it, not even in "All Zone Stereo" mode. Test before wiring.
- Front-panel headphone jacks usually mute the speakers; REC-OUTs on older
  units often carry analog inputs only.

## Option B: HDMI audio extractor (no AVR required)

An inline HDCP-2.2-passive extractor between TV box and TV/AVR (~35–60 €),
with analog RCA or TOSLINK out into your interface. Decodes DD+/Atmos to PCM
stereo — fine for ASR, no impact on the video path.

## Option C: TV optical out

If the TV has TOSLINK and can be set to PCM output, a USB/TOSLINK interface
on the host works too.

## USB audio interfaces on Linux — check before you blame the software

Some DSP-based interfaces (Focusrite Scarlett 4th gen confirmed) expose
several ALSA altsettings, and **not all of them carry the real inputs**:

```bash
arecord -l                          # find the card
arecord -D hw:1,0 -c 18 -f S32_LE -r 44100 -d 5 t.wav   # may be noise-only!
arecord -D hw:1,0 -c 10 -f S32_LE -r 176400 -d 5 t.wav  # Scarlett 16i16: real inputs
ffmpeg -i t.wav -map_channel 0.0.0 -af volumedetect -f null -   # level check
```

Symptoms of a wrong altsetting or rate: identical low-level noise on *every*
channel, or "silence" that is actually chipmunk-speed audio (the device
silently records at a rate it supports instead of the requested one — check
arecord's stderr). The Scarlett 16i16 4th Gen works at `-c 10 -f S32_LE -r
176400` (or the 14-channel altsetting at 88.2/96 kHz); simple USB sound cards
with line-in usually just work at any setting.

The server also accepts plain `--device <sounddevice index>` (PortAudio) if
your interface behaves there. A `--gain` multiplier is available for quiet
lines.
