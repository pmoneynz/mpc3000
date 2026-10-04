; Stock-OS profile for the shared F07D cave.  Exactly one profile is used:
;
;   -DPROFILE_316             profile_316.inc       OS 3.16 (skeleton)
;   -DWAVE_CAPTURE_20261001   profile_capture.inc   2026-10-01 physical capture
;   neither                   profile_vailixi.inc   generic Vailixi 3.50
;
; A profile defines every stock address the cave uses: DGROUP objects,
; segment values, and the far CALL/JMP targets T_SSSS_OOOO.  A target keeps
; the name of its generic Vailixi 3.50 CS:IP even where the value differs.
; Each profile also defines:
;   FCALL t / FJMP t  far CALL/JMP to target t, its segment word marked.
;   RELOC_PREV        marks the last two bytes emitted as a segment word.
;                     That word must end the preceding instruction or dw, so
;                     a pushed or compared segment is `strict word`: a small
;                     value would otherwise become a sign-extended byte.
; Offsets, DGROUP data offsets included, are never marked.

%ifdef PROFILE_316
 %ifdef WAVE_CAPTURE_20261001
  %fatal "PROFILE_316 and WAVE_CAPTURE_20261001 select different profiles"
 %endif
 %include "profile_316.inc"
%elifdef WAVE_CAPTURE_20261001
 %include "profile_capture.inc"
%else
 %include "profile_vailixi.inc"
%endif
